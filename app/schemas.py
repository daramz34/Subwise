"""Pydantic v2 request/response schemas for every module.

Conventions
- *In  schemas validate input: extra fields are rejected, strings are trimmed.
- *Out schemas read from ORM objects (from_attributes) and never include secrets
  (no password_hash, token hashes, storage paths, raw webhook payloads).
- Clients never send: user_id, source, verified, archived_at, status of imports/orders.
  The server sets those.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints,
    field_validator, model_validator,
)


# ==========================================================================
# Shared building blocks
# ==========================================================================
class InModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OutModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _check_timezone(v: str) -> str:
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown timezone, use an IANA name like 'Africa/Lagos'")
    return v


def _check_url(v: str) -> str:
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Must be a valid http(s) URL")  # blocks javascript: and data: links
    return v


def _check_password(v: str) -> str:
    if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one letter and one number")
    return v


CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$", to_upper=True)]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
Percent = Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]
Timezone = Annotated[str, StringConstraints(max_length=60), AfterValidator(_check_timezone)]
WebUrl = Annotated[str, StringConstraints(max_length=2048), AfterValidator(_check_url)]
Password = Annotated[str, Field(min_length=8, max_length=128), AfterValidator(_check_password)]

SubscriptionStatus = Literal["active", "paused", "cancelled", "trial"]
BillingInterval = Literal["day", "week", "month", "year"]
Pagination = Annotated[int, Field(ge=1)]


class DetailOut(OutModel):
    detail: str


# ==========================================================================
# GROUP A: AUTH & ACCOUNT
# ==========================================================================
class RegisterIn(InModel):
    full_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: Password
    default_currency: CurrencyCode = "USD"
    timezone: Timezone = "UTC"

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class LoginIn(InModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class TokenOut(OutModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds until the access token expires


class RefreshIn(InModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class ForgotPasswordIn(InModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class ResetPasswordIn(InModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: Password


class ChangePasswordIn(InModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password


class UserUpdate(InModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    default_currency: CurrencyCode | None = None
    timezone: Timezone | None = None


class UserOut(OutModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    default_currency: str
    timezone: str
    is_demo: bool
    email_verified_at: datetime | None
    created_at: datetime


# ==========================================================================
# GROUP B: CATEGORIES, TAGS, SUBSCRIPTIONS
# ==========================================================================
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class CategoryCreate(InModel):
    name: str = Field(min_length=1, max_length=60)
    color: HexColor | None = None
    icon: str | None = Field(default=None, max_length=40)


class CategoryUpdate(InModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    color: HexColor | None = None
    icon: str | None = Field(default=None, max_length=40)


class CategoryOut(OutModel):
    id: uuid.UUID
    name: str
    color: str | None
    icon: str | None
    is_default: bool


class TagCreate(InModel):
    name: str = Field(min_length=1, max_length=40)


class TagOut(OutModel):
    id: uuid.UUID
    name: str


class SubscriptionBase(InModel):
    name: str = Field(min_length=1, max_length=150)
    merchant: str | None = Field(default=None, max_length=150)
    category_id: uuid.UUID | None = None
    amount: Money
    currency: CurrencyCode
    billing_interval: BillingInterval = "month"
    interval_count: int = Field(default=1, ge=1, le=36)
    start_date: date | None = None
    next_renewal_date: date | None = None
    status: SubscriptionStatus = "active"
    trial_end_date: date | None = None
    trial_converts_amount: Money | None = None
    commitment_end_date: date | None = None
    is_shared: bool = False
    my_share_percent: Percent = Decimal("100.00")
    website_url: WebUrl | None = None
    cancel_url: WebUrl | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def check_rules(self):
        if self.status == "trial" and self.trial_end_date is None:
            raise ValueError("trial_end_date is required when status is 'trial'")
        if self.start_date and self.next_renewal_date and self.next_renewal_date < self.start_date:
            raise ValueError("next_renewal_date cannot be before start_date")
        if not self.is_shared and self.my_share_percent != Decimal("100"):
            raise ValueError("my_share_percent must be 100 unless is_shared is true")
        return self


class SubscriptionCreate(SubscriptionBase):
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    acknowledge_duplicate: bool = False  # set true to save despite a duplicate warning


# Fields that exist as NOT NULL columns: sending an explicit null for them is an error
_NON_NULLABLE = {
    "name", "amount", "currency", "billing_interval", "interval_count",
    "status", "is_shared", "my_share_percent",
}


class SubscriptionUpdate(InModel):
    """Partial update. Only fields the client actually sends are changed."""
    name: str | None = Field(default=None, min_length=1, max_length=150)
    merchant: str | None = Field(default=None, max_length=150)
    category_id: uuid.UUID | None = None
    amount: Money | None = None
    currency: CurrencyCode | None = None
    billing_interval: BillingInterval | None = None
    interval_count: int | None = Field(default=None, ge=1, le=36)
    start_date: date | None = None
    next_renewal_date: date | None = None
    status: SubscriptionStatus | None = None
    trial_end_date: date | None = None
    trial_converts_amount: Money | None = None
    commitment_end_date: date | None = None
    is_shared: bool | None = None
    my_share_percent: Percent | None = None
    website_url: WebUrl | None = None
    cancel_url: WebUrl | None = None
    notes: str | None = Field(default=None, max_length=2000)
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    price_effective_date: date | None = None  # when a changed price took effect (default: today)

    @model_validator(mode="after")
    def reject_null_for_required(self):
        for field in self.model_fields_set & _NON_NULLABLE:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class SubscriptionStatusIn(InModel):
    status: SubscriptionStatus


class SubscriptionBulkIn(InModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    action: Literal["activate", "pause", "cancel", "archive", "set_category"]
    category_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def category_needed(self):
        if self.action == "set_category" and self.category_id is None:
            raise ValueError("category_id is required for set_category")
        return self


class SubscriptionOut(OutModel):
    id: uuid.UUID
    name: str
    merchant: str | None
    merchant_id: uuid.UUID | None
    category_id: uuid.UUID | None
    category: CategoryOut | None
    amount: Decimal
    currency: str
    billing_interval: str
    interval_count: int
    start_date: date | None
    next_renewal_date: date | None
    status: str
    trial_end_date: date | None
    trial_converts_amount: Decimal | None
    commitment_end_date: date | None
    is_shared: bool
    my_share_percent: Decimal
    cancelled_on: date | None
    archived_at: datetime | None
    last_confirmed_active_at: datetime | None
    cancel_url: str | None
    source: str
    website_url: str | None
    notes: str | None
    tags: list[TagOut]
    created_at: datetime
    updated_at: datetime


class SubscriptionFilters(InModel):
    """Use as query params: filters: Annotated[SubscriptionFilters, Query()]"""
    q: str | None = Field(default=None, max_length=100)
    status: SubscriptionStatus | None = None
    category_id: uuid.UUID | None = None
    tag_id: uuid.UUID | None = None
    include_archived: bool = False
    sort: Literal["name", "amount", "next_renewal_date", "created_at"] = "next_renewal_date"
    order: Literal["asc", "desc"] = "asc"
    page: Pagination = 1
    page_size: int = Field(default=20, ge=1, le=100)


class SubscriptionPage(OutModel):
    items: list[SubscriptionOut]
    total: int
    page: int
    page_size: int


class DuplicateWarningOut(OutModel):
    """Returned with HTTP 409 when a similar subscription exists and acknowledge_duplicate is false."""
    detail: str
    similar_subscription_ids: list[uuid.UUID]


class PriceHistoryOut(OutModel):
    id: uuid.UUID
    amount: Decimal
    previous_amount: Decimal | None
    currency: str
    effective_date: date
    recorded_at: datetime
    source: str


class PaymentCreate(InModel):
    amount: Money
    currency: CurrencyCode
    payment_date: date
    status: Literal["recorded", "paid", "failed", "refunded"] = "recorded"
    external_reference: str | None = Field(default=None, max_length=255)


class PaymentOut(OutModel):
    id: uuid.UUID
    subscription_id: uuid.UUID
    amount: Decimal
    currency: str
    payment_date: date
    status: str
    source: str
    verified: bool
    external_reference: str | None
    created_at: datetime


# ==========================================================================
# GROUP C: AI IMPORT
# ==========================================================================
ImportInterval = Literal["day", "week", "month", "year"]


class CsvColumnMappingCreate(InModel):
    name: str = Field(min_length=1, max_length=100)
    mapping: dict[str, str]  # {"date": "Txn Date", "description": "Narration", "amount": "Debit"}

    @field_validator("mapping")
    @classmethod
    def required_keys(cls, v: dict[str, str]) -> dict[str, str]:
        missing = {"date", "description", "amount"} - v.keys()
        if missing:
            raise ValueError(f"mapping must include: {', '.join(sorted(missing))}")
        unknown = v.keys() - {"date", "description", "amount", "currency"}
        if unknown:
            raise ValueError(f"unknown mapping keys: {', '.join(sorted(unknown))}")
        return v


class CsvColumnMappingOut(OutModel):
    id: uuid.UUID
    name: str
    mapping: dict[str, str]
    created_at: datetime


class EmailPasteIn(InModel):
    text: str = Field(min_length=20, max_length=20000)


class ImportJobOut(OutModel):
    id: uuid.UUID
    file_name: str | None
    file_type: str
    status: str
    redaction_applied: bool
    items_detected: int
    items_confirmed: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    undone_at: datetime | None


class ImportItemOut(OutModel):
    id: uuid.UUID
    extracted_name: str | None
    extracted_amount: Decimal | None
    extracted_currency: str | None
    extracted_interval: str | None
    extracted_date: date | None
    confidence: Decimal | None
    field_confidence: dict[str, float] | None
    detection_method: str
    occurrences_count: int
    duplicate_of_id: uuid.UUID | None
    status: str
    subscription_id: uuid.UUID | None


class ImportItemEdit(InModel):
    """Corrections the user makes on the review screen. Only sent fields are applied."""
    extracted_name: str | None = Field(default=None, min_length=1, max_length=150)
    extracted_amount: Money | None = None
    extracted_currency: CurrencyCode | None = None
    extracted_interval: ImportInterval | None = None
    extracted_date: date | None = None


class ImportDecision(InModel):
    item_id: uuid.UUID
    action: Literal["confirm", "reject"]
    edits: ImportItemEdit | None = None

    @model_validator(mode="after")
    def no_edits_on_reject(self):
        if self.action == "reject" and self.edits:
            raise ValueError("edits are only allowed when confirming")
        return self


class ImportConfirmIn(InModel):
    decisions: list[ImportDecision] = Field(min_length=1, max_length=200)

    @field_validator("decisions")
    @classmethod
    def unique_items(cls, v: list[ImportDecision]) -> list[ImportDecision]:
        ids = [d.item_id for d in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Each item can appear only once")
        return v


class ImportConfirmOut(OutModel):
    created_subscription_ids: list[uuid.UUID]
    rejected_count: int
    skipped_count: int


# What we EXPECT the AI model to return. Always validate model output with this
# before writing import_items: never trust raw model JSON.
class ExtractedSubscription(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=150)
    amount: Annotated[Decimal, Field(ge=0, le=Decimal("9999999999"))] | None = None
    currency: CurrencyCode | None = None
    interval: ImportInterval | None = None
    charge_date: date | None = None  # not named 'date': would shadow the type
    confidence: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("0")
    field_confidence: dict[str, float] = Field(default_factory=dict)


class AIExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[ExtractedSubscription] = Field(default_factory=list, max_length=100)


# ==========================================================================
# GROUP D: ANALYTICS, AI ANALYST, BUDGETS, SAVINGS
# ==========================================================================
class CurrencyTotalOut(OutModel):
    currency: str
    monthly: Decimal
    yearly: Decimal


class CategoryTotalOut(OutModel):
    category_id: uuid.UUID | None
    category_name: str
    currency: str
    monthly: Decimal


class UpcomingRenewalOut(OutModel):
    subscription_id: uuid.UUID
    name: str
    amount: Decimal
    currency: str
    renewal_date: date
    days_until: int


class OverviewOut(OutModel):
    active_count: int
    totals_by_currency: list[CurrencyTotalOut]  # never summed across currencies
    by_category: list[CategoryTotalOut]
    upcoming_renewals: list[UpcomingRenewalOut]


class ForecastPointOut(OutModel):
    month: str  # "2026-12"
    currency: str
    amount: Decimal


class ForecastOut(OutModel):
    months: int
    points: list[ForecastPointOut]


class PriceChangeOut(OutModel):
    subscription_id: uuid.UUID
    name: str
    currency: str
    old_amount: Decimal
    new_amount: Decimal
    change_amount: Decimal
    change_percent: Decimal
    effective_date: date
    yearly_impact: Decimal


class InsightOut(OutModel):
    id: uuid.UUID
    subscription_id: uuid.UUID | None
    insight_type: str
    severity: str
    title: str
    description: str
    potential_yearly_saving: Decimal | None
    currency: str | None
    supporting_data: dict[str, Any] | None
    generated_at: datetime
    dismissed: bool


class AskIn(InModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: uuid.UUID | None = None


class AIMessageOut(OutModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[dict[str, Any]] | None
    created_at: datetime


class ProposedActionOut(OutModel):
    id: uuid.UUID
    subscription_id: uuid.UUID | None
    action_type: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    resolved_at: datetime | None


class AskOut(OutModel):
    conversation_id: uuid.UUID
    message: AIMessageOut
    proposed_actions: list[ProposedActionOut] = []


class ConversationOut(OutModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[AIMessageOut]


class ActionDecisionIn(InModel):
    decision: Literal["approve", "reject"]


# Internal: validates an action the AI proposes BEFORE it is stored. Allow-lists
# what the AI may even suggest changing, so a prompt injection can't propose
# changing amounts, currencies or ownership.
AI_EDITABLE_FIELDS = {"next_renewal_date", "category_id", "notes"}


class ProposedActionCreate(BaseModel):
    action_type: Literal["pause_status", "cancel_status", "update_field", "set_reminder"]
    subscription_id: uuid.UUID
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_payload(self):
        p = self.payload
        if self.action_type in ("pause_status", "cancel_status"):
            if p:
                raise ValueError("status actions take no payload")
        elif self.action_type == "update_field":
            if set(p.keys()) - AI_EDITABLE_FIELDS or not p:
                raise ValueError(f"update_field may only change: {sorted(AI_EDITABLE_FIELDS)}")
        elif self.action_type == "set_reminder":
            days = p.get("days_before")
            if set(p.keys()) != {"days_before"} or not isinstance(days, int) or not 0 <= days <= 90:
                raise ValueError("set_reminder needs days_before between 0 and 90")
        return self


class ReportOut(OutModel):
    id: uuid.UUID
    report_type: Literal["monthly", "wrapped"]
    period_start: date
    period_end: date
    summary: str | None
    content: dict[str, Any] | None
    generated_at: datetime


class HealthScoreOut(OutModel):
    score: int = Field(ge=0, le=100)
    factors: dict[str, Any] | None
    calculated_at: datetime


class BudgetCreate(InModel):
    category_id: uuid.UUID | None = None  # null = overall budget
    currency: CurrencyCode
    monthly_limit: PositiveMoney
    warn_at_percent: int = Field(default=80, ge=1, le=100)


class BudgetUpdate(InModel):
    monthly_limit: PositiveMoney | None = None
    warn_at_percent: int | None = Field(default=None, ge=1, le=100)


class BudgetOut(OutModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    currency: str
    monthly_limit: Decimal
    warn_at_percent: int


class BudgetStatusOut(OutModel):
    budget: BudgetOut
    spent: Decimal
    percent_used: Decimal
    state: Literal["ok", "warning", "exceeded"]


class SavingsCreate(InModel):
    subscription_id: uuid.UUID | None = None
    subscription_name: str = Field(min_length=1, max_length=150)
    yearly_saving: PositiveMoney
    currency: CurrencyCode
    reason: Literal["cancelled", "downgraded", "negotiated"]
    occurred_on: date


class SavingsOut(OutModel):
    id: uuid.UUID
    subscription_name: str
    yearly_saving: Decimal
    currency: str
    reason: str
    occurred_on: date


# ==========================================================================
# GROUP E: NOTIFICATIONS
# ==========================================================================
class NotificationOut(OutModel):
    id: uuid.UUID
    subscription_id: uuid.UUID | None
    notification_type: str
    channel: str
    title: str
    message: str
    scheduled_for: datetime
    sent_at: datetime | None
    read_at: datetime | None


class NotificationPreferenceUpdate(InModel):
    renewal_days_before: list[Annotated[int, Field(ge=0, le=90)]] | None = Field(
        default=None, min_length=1, max_length=5
    )
    in_app_enabled: bool | None = None
    email_enabled: bool | None = None
    trial_alerts_enabled: bool | None = None
    price_alerts_enabled: bool | None = None
    weekly_digest_enabled: bool | None = None
    weekly_digest_day: int | None = Field(default=None, ge=0, le=6)

    @field_validator("renewal_days_before")
    @classmethod
    def clean_days(cls, v: list[int] | None) -> list[int] | None:
        return sorted(set(v)) if v else v


class NotificationPreferenceOut(OutModel):
    renewal_days_before: list[int]
    in_app_enabled: bool
    email_enabled: bool
    trial_alerts_enabled: bool
    price_alerts_enabled: bool
    weekly_digest_enabled: bool
    weekly_digest_day: int


# ==========================================================================
# GROUP F: PLANS & PAYPAL
# The webhook endpoint takes NO schema: read the raw request body and verify the
# PayPal signature on those exact bytes before parsing JSON.
# ==========================================================================
class PlanOut(OutModel):
    code: str
    name: str
    price: Decimal
    currency: str
    duration_days: int | None
    limits: dict[str, Any]
    is_active: bool


class CreateOrderIn(InModel):
    plan_code: Literal["plus"]  # the client names the plan; the SERVER decides the price
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


class CreateOrderOut(OutModel):
    paypal_order_id: str
    status: str
    approval_url: str | None = None


class CaptureOrderIn(InModel):
    paypal_order_id: str = Field(min_length=1, max_length=100)


class OrderOut(OutModel):
    id: uuid.UUID
    paypal_order_id: str
    amount: Decimal
    currency: str
    status: str
    failure_reason: str | None
    captured_at: datetime | None
    refunded_at: datetime | None
    created_at: datetime


class EntitlementOut(OutModel):
    plan: PlanOut
    status: str
    activated_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None