// PayPal sends the buyer back to /?paypal=return&token=<order id>&PayerID=...
// Read it once at startup, clean the URL, and send the app to the Upgrade page.
const params = new URLSearchParams(window.location.search);
let pending = params.get('paypal') ? { result: params.get('paypal'), token: params.get('token') } : null;
if (pending) window.history.replaceState(null, '', `${window.location.pathname}#/upgrade`);

export function takePaypalReturn() {
  const p = pending;
  pending = null;
  return p;
}