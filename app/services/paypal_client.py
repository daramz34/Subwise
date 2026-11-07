"""The only file that talks to PayPal (REST API; sandbox by default).
Never logs the client secret, tokens, or payer details."""
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class PayPalError(Exception):
    """Message is safe to show the user. `issue` is PayPal's machine-readable reason, if any."""

    def __init__(self, message: str, *, issue: str | None = None):
        super().__init__(message)
        self.issue = issue


_token = {"value": None, "expires_at": 0.0}


def _base() -> str:
    return settings.PAYPAL_BASE_URL.rstrip("/")


def _access_token() -> str:
    if not (settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET):
        raise PayPalError("Payments aren't configured on this server.")
    if _token["value"] and time.time() < _token["expires_at"]:
        return _token["value"]
    try:
        r = httpx.post(
            f"{_base()}/v1/oauth2/token",
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
            timeout=20,
        )
    except httpx.HTTPError:
        raise PayPalError("Couldn't reach PayPal. Please try again.")
    if r.status_code != 200:
        logger.warning("PayPal token request failed with status %s", r.status_code)
        raise PayPalError("PayPal rejected the server credentials.")
    data = r.json()
    _token["value"] = data["access_token"]
    _token["expires_at"] = time.time() + int(data.get("expires_in", 300)) - 60
    return _token["value"]


def _request(method: str, path: str, *, body: dict | None = None, request_id: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"}
    if request_id:
        headers["PayPal-Request-Id"] = request_id
    try:
        r = httpx.request(method, f"{_base()}{path}", headers=headers, json=body, timeout=30)
    except httpx.TimeoutException:
        raise PayPalError("PayPal took too long to respond. Please try again.")
    except httpx.HTTPError:
        raise PayPalError("Couldn't reach PayPal. Please try again.")
    if r.status_code // 100 != 2:
        issue = None
        try:
            err = r.json()
            details = err.get("details") or []
            issue = details[0].get("issue") if details else err.get("name")
            logger.warning("PayPal %s %s -> %s issue=%s debug_id=%s",
                           method, path, r.status_code, issue, err.get("debug_id"))
        except ValueError:
            logger.warning("PayPal %s %s -> %s", method, path, r.status_code)
        raise PayPalError("PayPal couldn't process the payment.", issue=issue)
    try:
        return r.json()
    except ValueError:
        raise PayPalError("PayPal returned an unexpected response.")


def create_order(*, amount: str, currency: str, description: str, reference_id: str, request_id: str) -> dict:
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": reference_id,
            "description": description,
            "amount": {"currency_code": currency, "value": amount},
        }],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": settings.APP_NAME,
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
            "return_url": settings.PAYPAL_RETURN_URL,
            "cancel_url": settings.PAYPAL_CANCEL_URL,
        }}},
    }
    return _request("POST", "/v2/checkout/orders", body=body, request_id=request_id)


def capture_order(order_id: str, request_id: str | None = None) -> dict:
    return _request("POST", f"/v2/checkout/orders/{order_id}/capture", body={}, request_id=request_id)


def get_order(order_id: str) -> dict:
    return _request("GET", f"/v2/checkout/orders/{order_id}")


def approval_url(order: dict) -> str | None:
    for link in order.get("links") or []:
        if link.get("rel") in ("payer-action", "approve"):
            return link.get("href")
    return None


def verify_webhook(headers, event: dict) -> bool:
    """Asks PayPal to verify the webhook signature. Returns True only on SUCCESS."""
    body = {
        "auth_algo": headers.get("paypal-auth-algo"),
        "cert_url": headers.get("paypal-cert-url"),
        "transmission_id": headers.get("paypal-transmission-id"),
        "transmission_sig": headers.get("paypal-transmission-sig"),
        "transmission_time": headers.get("paypal-transmission-time"),
        "webhook_id": settings.PAYPAL_WEBHOOK_ID,
        "webhook_event": event,
    }
    if not all(body[k] for k in ("auth_algo", "cert_url", "transmission_id", "transmission_sig", "transmission_time")):
        return False
    result = _request("POST", "/v1/notifications/verify-webhook-signature", body=body)
    return result.get("verification_status") == "SUCCESS"