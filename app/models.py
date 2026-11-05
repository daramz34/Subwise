import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CHAR, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base
from decimal import Decimal
 

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=new_id)


def fk(target: str, ondelete: str = "CASCADE", nullable: bool = False, index: bool = False):
    return Column(
        UUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=index,
    )


def created():
    return Column(DateTime(timezone=True), nullable=False, default=utcnow)


def updated():
    return Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("failed_login_count >= 0", name="ck_users_failed_login_count"),
    )

    id = pk()
    full_name = Column(String(100), nullable=False)  # NOT unique: two people can share a name
    email = Column(String(255), unique=True, nullable=False, index=True)  # store lowercased
    password_hash = Column(String(255), nullable=False)
    default_currency = Column(CHAR(3), nullable=False, default="USD")
    timezone = Column(String(60), nullable=False, default="UTC")
    is_demo = Column(Boolean, nullable=False, default=False)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)  # NULL = not verified
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = created()
    updated_at = updated()

    # cascade + passive_deletes: the ORM won't try to NULL the children's user_id;
    # the database's ON DELETE CASCADE does the work.
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, unique=True)  # hash only, never the raw token
    user_agent = Column(String(255), nullable=True)  # some clients send none
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)  # set on logout
    created_at = created()

    user = relationship("User", back_populates="refresh_tokens")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, unique=True)  # hash only
    expires_at = Column(DateTime(timezone=True), nullable=False)  # keep short, e.g. 30 min
    used_at = Column(DateTime(timezone=True), nullable=True)  # set once consumed
    created_at = created()

    user = relationship("User", back_populates="password_reset_tokens")





class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_category_user_name"),
        # Postgres treats NULLs as distinct, so enforce uniqueness of system defaults separately
        Index(
            "uq_category_system_name", "name", unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )
 
    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=True, index=True)
    name = Column(String(60), nullable=False)
    color = Column(String(7), nullable=True)  # hex, e.g. #1F77B4
    icon = Column(String(40), nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = created()



class Merchant(Base):
    __tablename__ = "merchants"
 
    id = pk()
    name = Column(String(150), nullable=False)
    normalized_name = Column(String(150), nullable=False, unique=True, index=True)  # lowercase key
    default_category_id = fk("categories.id", ondelete="SET NULL", nullable=True)
    overlap_group = Column(String(60), nullable=True, index=True)  # music_streaming, cloud_storage...
    website_url = Column(Text, nullable=True)
    cancel_url = Column(Text, nullable=True)
    cancel_instructions = Column(Text, nullable=True)
    created_at = created()
 
    default_category = relationship("Category")



class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("status IN ('active','paused','cancelled','trial')", name="ck_sub_status"),
        CheckConstraint("billing_interval IN ('day','week','month','year')", name="ck_sub_interval"),
        CheckConstraint("source IN ('manual','import','email_paste')", name="ck_sub_source"),
        CheckConstraint("interval_count >= 1", name="ck_sub_interval_count"),
        CheckConstraint("amount >= 0", name="ck_sub_amount"),
        CheckConstraint("my_share_percent > 0 AND my_share_percent <= 100", name="ck_sub_share"),
        Index("ix_sub_user_status", "user_id", "status"),
        Index("ix_sub_user_renewal", "user_id", "next_renewal_date"),
    )
 
    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False, index=True)
    merchant_id = fk("merchants.id", ondelete="SET NULL", nullable=True)
    category_id = fk("categories.id", ondelete="SET NULL", nullable=True)
 
    name = Column(String(150), nullable=False)
    merchant = Column(String(150), nullable=True)  # merchant name as typed or imported
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    billing_interval = Column(String(20), nullable=False, default="month")
    interval_count = Column(Integer, nullable=False, default=1)
 
    start_date = Column(Date, nullable=True)
    next_renewal_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="active")
 
    trial_end_date = Column(Date, nullable=True)
    trial_converts_amount = Column(Numeric(12, 2), nullable=True)
    commitment_end_date = Column(Date, nullable=True)
 
    is_shared = Column(Boolean, nullable=False, default=False)
    my_share_percent = Column(Numeric(5, 2), nullable=False, default=Decimal("100.00"))
 
    cancelled_on = Column(Date, nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)  # soft delete
    last_confirmed_active_at = Column(DateTime(timezone=True), nullable=True)  # zombie detector
 
    cancel_url = Column(Text, nullable=True)  # overrides merchant.cancel_url
    source = Column(String(20), nullable=False, default="manual")
    website_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = created()
    updated_at = updated()
 
    # named merchant_info because "merchant" is already the plain-text column above
    merchant_info = relationship("Merchant")
    category = relationship("Category")
    tags = relationship("Tag", secondary="subscription_tags", back_populates="subscriptions")
    price_history = relationship(
        "PriceHistory", back_populates="subscription",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="PriceHistory.effective_date",
    )
    payments = relationship(
        "PaymentRecord", back_populates="subscription",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="PaymentRecord.payment_date",
    )
 


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tag_user_name"),)
 
    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False, index=True)
    name = Column(String(40), nullable=False)
    created_at = created()
 
    subscriptions = relationship("Subscription", secondary="subscription_tags", back_populates="tags")



class SubscriptionTag(Base):
    __tablename__ = "subscription_tags"
 
    subscription_id = Column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id = Column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )
 

class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_ph_amount"),
        CheckConstraint("source IN ('manual','import','integration')", name="ck_ph_source"),
        Index("ix_ph_sub_effective", "subscription_id", "effective_date"),
    )
 
    id = pk()
    subscription_id = fk("subscriptions.id", ondelete="CASCADE", nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    previous_amount = Column(Numeric(12, 2), nullable=True)  # NULL for the first record
    currency = Column(CHAR(3), nullable=False)
    effective_date = Column(Date, nullable=False)
    recorded_at = created()
    source = Column(String(20), nullable=False, default="manual")
 
    subscription = relationship("Subscription", back_populates="price_history")
 

class PaymentRecord(Base):
    __tablename__ = "payment_records"
    __table_args__ = (
        CheckConstraint("status IN ('recorded','paid','failed','refunded')", name="ck_pay_status"),
        CheckConstraint("source IN ('manual','import','integration')", name="ck_pay_source"),
        CheckConstraint("amount >= 0", name="ck_pay_amount"),
        Index("ix_pay_sub_date", "subscription_id", "payment_date"),
    )
 
    id = pk()
    subscription_id = fk("subscriptions.id", ondelete="CASCADE", nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    payment_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="recorded")
    source = Column(String(20), nullable=False, default="manual")
    verified = Column(Boolean, nullable=False, default=False)  # imported rows stay False
    external_reference = Column(String(255), nullable=True)
    created_at = created()
 
    subscription = relationship("Subscription", back_populates="payments")




class CsvColumnMapping(Base):
    __tablename__ = "csv_column_mappings"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_csvmap_user_name"),)

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False, index=True)
    name = Column(String(100), nullable=False)  # e.g. "GTBank statement"
    mapping = Column(JSONB, nullable=False)  # {"date": "Txn Date", "description": "Narration", ...}
    created_at = created()


class ImportJob(Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        CheckConstraint("file_type IN ('csv','pdf','image','email_text')", name="ck_job_file_type"),
        CheckConstraint(
            "status IN ('uploaded','processing','review','completed','failed')", name="ck_job_status"
        ),
        Index("ix_job_user_created", "user_id", "created_at"),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False)
    file_name = Column(String(255), nullable=True)  # NULL for pasted text
    file_type = Column(String(30), nullable=False)
    storage_path = Column(String(500), nullable=True)
    column_mapping_id = fk("csv_column_mappings.id", ondelete="SET NULL", nullable=True)
    redaction_applied = Column(Boolean, nullable=False, default=False)
    status = Column(String(30), nullable=False, default="uploaded")
    items_detected = Column(Integer, nullable=False, default=0)
    items_confirmed = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = created()
    completed_at = Column(DateTime(timezone=True), nullable=True)
    undone_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship(
        "ImportItem", back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )
    column_mapping = relationship("CsvColumnMapping")


class ImportItem(Base):
    __tablename__ = "import_items"
    __table_args__ = (
        CheckConstraint("detection_method IN ('ai','pattern','both')", name="ck_item_method"),
        CheckConstraint("status IN ('pending','confirmed','rejected')", name="ck_item_status"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_item_conf"),
        Index("ix_item_job_status", "import_job_id", "status"),
    )

    id = pk()
    import_job_id = fk("import_jobs.id", ondelete="CASCADE", nullable=False)
    extracted_name = Column(String(150), nullable=True)
    extracted_amount = Column(Numeric(12, 2), nullable=True)
    extracted_currency = Column(CHAR(3), nullable=True)
    extracted_interval = Column(String(20), nullable=True)
    extracted_date = Column(Date, nullable=True)
    confidence = Column(Numeric(4, 3), nullable=True)
    field_confidence = Column(JSONB, nullable=True)  # {"amount": 0.98, "interval": 0.55}
    detection_method = Column(String(20), nullable=False, default="ai")
    occurrences_count = Column(Integer, nullable=False, default=1)
    duplicate_of_id = fk("subscriptions.id", ondelete="SET NULL", nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # AI output is never trusted until confirmed
    user_edits = Column(JSONB, nullable=True)
    subscription_id = fk("subscriptions.id", ondelete="SET NULL", nullable=True)

    job = relationship("ImportJob", back_populates="items")

class AIInsight(Base):
    __tablename__ = "ai_insights"
    __table_args__ = (
        CheckConstraint(
            "insight_type IN ('price_increase','forecast','spending','zombie','overlap',"
            "'trial_ending','savings_opportunity')",
            name="ck_insight_type",
        ),
        CheckConstraint("severity IN ('info','warning','critical')", name="ck_insight_severity"),
        Index("ix_insight_user_active", "user_id", "dismissed", "generated_at"),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False)
    subscription_id = fk("subscriptions.id", ondelete="CASCADE", nullable=True)
    insight_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="info")
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    potential_yearly_saving = Column(Numeric(12, 2), nullable=True)
    currency = Column(CHAR(3), nullable=True)
    supporting_data = Column(JSONB, nullable=True)  # the figures behind the insight
    generated_at = created()
    dismissed = Column(Boolean, nullable=False, default=False)


# Table 15
class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False, index=True)
    title = Column(String(200), nullable=True)
    created_at = created()
    updated_at = updated()

    messages = relationship(
        "AIMessage", back_populates="conversation", cascade="all, delete-orphan",
        passive_deletes=True, order_by="AIMessage.created_at",
    )


# Table 16
class AIMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_msg_role"),
        Index("ix_msg_conv_created", "conversation_id", "created_at"),
    )

    id = pk()
    conversation_id = fk("ai_conversations.id", ondelete="CASCADE", nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    citations = Column(JSONB, nullable=True)  # subscription ids + figures the answer used
    created_at = created()

    conversation = relationship("AIConversation", back_populates="messages")


# Table 17: AI proposes, user approves. Nothing executes until status = 'approved'.
class AIProposedAction(Base):
    __tablename__ = "ai_proposed_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('pause_status','cancel_status','update_field','set_reminder')",
            name="ck_action_type",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected','expired')", name="ck_action_status"
        ),
        Index("ix_action_user_status", "user_id", "status"),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False)
    message_id = fk("ai_messages.id", ondelete="SET NULL", nullable=True)
    subscription_id = fk("subscriptions.id", ondelete="CASCADE", nullable=True)
    action_type = Column(String(40), nullable=False)
    payload = Column(JSONB, nullable=False)  # the exact change to apply
    status = Column(String(20), nullable=False, default="pending")
    created_at = created()
    resolved_at = Column(DateTime(timezone=True), nullable=True)


# Table 18
class AIReport(Base):
    __tablename__ = "ai_reports"
    __table_args__ = (
        CheckConstraint("report_type IN ('monthly','wrapped')", name="ck_report_type"),
        # one report per user, type and period: regenerating can't create duplicates
        UniqueConstraint("user_id", "report_type", "period_start", name="uq_report_period"),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False, index=True)
    report_type = Column(String(30), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    summary = Column(Text, nullable=True)
    content = Column(JSONB, nullable=True)
    generated_at = created()


# Table 19
class HealthScoreSnapshot(Base):
    __tablename__ = "health_score_snapshots"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_health_score"),
        Index("ix_health_user_time", "user_id", "calculated_at"),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False)
    score = Column(Integer, nullable=False)
    factors = Column(JSONB, nullable=True)  # {"overlaps": -10, "zombies": -5, ...}
    calculated_at = created()
class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("monthly_limit > 0", name="ck_budget_limit"),
        CheckConstraint("warn_at_percent >= 1 AND warn_at_percent <= 100", name="ck_budget_warn"),
        UniqueConstraint("user_id", "category_id", "currency", name="uq_budget_scope"),
        # NULL category = overall budget; NULLs are distinct in Postgres so enforce separately
        Index(
            "uq_budget_overall", "user_id", "currency", unique=True,
            postgresql_where=text("category_id IS NULL"),
        ),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False, index=True)
    category_id = fk("categories.id", ondelete="CASCADE", nullable=True)
    currency = Column(CHAR(3), nullable=False)
    monthly_limit = Column(Numeric(12, 2), nullable=False)
    warn_at_percent = Column(Integer, nullable=False, default=80)
    created_at = created()
    updated_at = updated()

class SavingsRecord(Base):
    __tablename__ = "savings_records"
    __table_args__ = (
        CheckConstraint("reason IN ('cancelled','downgraded','negotiated')", name="ck_savings_reason"),
        CheckConstraint("yearly_saving >= 0", name="ck_savings_amount"),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False, index=True)
    subscription_id = fk("subscriptions.id", ondelete="SET NULL", nullable=True)
    subscription_name = Column(String(150), nullable=False)  # snapshot, survives deletion
    yearly_saving = Column(Numeric(12, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    reason = Column(String(30), nullable=False)
    occurred_on = Column(Date, nullable=False)
    created_at = created()

class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "notification_type IN ('renewal','trial_ending','price_increase','budget_warning','weekly_digest')",
            name="ck_notif_type",
        ),
        CheckConstraint("channel IN ('in_app','email')", name="ck_notif_channel"),
        UniqueConstraint("user_id", "dedupe_key", name="uq_notif_dedupe"),
        Index("ix_notif_user_sched", "user_id", "scheduled_for"),
        Index("ix_notif_due", "scheduled_for", postgresql_where=text("sent_at IS NULL")),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False)
    subscription_id = fk("subscriptions.id", ondelete="CASCADE", nullable=True)
    notification_type = Column(String(40), nullable=False)
    channel = Column(String(20), nullable=False, default="in_app")
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    dedupe_key = Column(String(150), nullable=False)  # e.g. renewal:<sub_id>:2026-11-05
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = created()


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint("weekly_digest_day >= 0 AND weekly_digest_day <= 6", name="ck_pref_digest_day"),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False)
    renewal_days_before = Column(JSONB, nullable=False, default=lambda: [1, 3, 7])
    in_app_enabled = Column(Boolean, nullable=False, default=True)
    email_enabled = Column(Boolean, nullable=False, default=True)
    trial_alerts_enabled = Column(Boolean, nullable=False, default=True)
    price_alerts_enabled = Column(Boolean, nullable=False, default=True)
    weekly_digest_enabled = Column(Boolean, nullable=False, default=False)
    weekly_digest_day = Column(Integer, nullable=False, default=0)
    updated_at = updated()

    __table_args__ = __table_args__ + (UniqueConstraint("user_id", name="uq_pref_user"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_user_time", "user_id", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=True)  # no FK: entity may be deleted
    action = Column(String(30), nullable=False)  # create, update, delete, ai_action_approved
    old_values = Column(JSONB, nullable=True)
    new_values = Column(JSONB, nullable=True)
    created_at = created()


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (CheckConstraint("price >= 0", name="ck_plan_price"),)

    id = pk()
    code = Column(String(30), nullable=False, unique=True)  # free, plus
    name = Column(String(60), nullable=False)
    price = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(CHAR(3), nullable=False, default="USD")
    duration_days = Column(Integer, nullable=True)  # NULL = no expiry
    limits = Column(JSONB, nullable=False, default=dict)  # max_subscriptions, ai_chat, imports_per_month
    is_active = Column(Boolean, nullable=False, default=True)


class PayPalOrder(Base):
    __tablename__ = "paypal_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created','approved','completed','failed','refunded')", name="ck_order_status"
        ),
        CheckConstraint("amount >= 0", name="ck_order_amount"),
        Index("ix_order_user_created", "user_id", "created_at"),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False)
    plan_id = fk("plans.id", ondelete="RESTRICT", nullable=False)
    paypal_order_id = Column(String(100), nullable=False, unique=True)
    idempotency_key = Column(String(100), nullable=False, unique=True)
    capture_id = Column(String(100), nullable=True, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    status = Column(String(30), nullable=False, default="created")
    failure_reason = Column(Text, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = created()
    updated_at = updated()

    plan = relationship("Plan")


class UserEntitlement(Base):
    __tablename__ = "user_entitlements"
    __table_args__ = (
        CheckConstraint("status IN ('active','revoked','expired')", name="ck_ent_status"),
        CheckConstraint(
            "revoke_reason IS NULL OR revoke_reason IN ('refunded','payment_failed','manual')",
            name="ck_ent_revoke_reason",
        ),
    )

    id = pk()
    user_id = fk("users.id", ondelete="CASCADE", nullable=False)
    plan_id = fk("plans.id", ondelete="RESTRICT", nullable=False)
    status = Column(String(20), nullable=False, default="active")
    source_order_id = fk("paypal_orders.id", ondelete="SET NULL", nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoke_reason = Column(String(50), nullable=True)

    plan = relationship("Plan")

    __table_args__ = __table_args__ + (UniqueConstraint("user_id", name="uq_ent_user"),)

class PayPalWebhookEvent(Base):
    __tablename__ = "paypal_webhook_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received','processed','failed','ignored')", name="ck_webhook_status"
        ),
    )

    id = pk()
    event_id = Column(String(100), nullable=False, unique=True)
    event_type = Column(String(80), nullable=False)
    paypal_order_id = Column(String(100), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="received")
    attempts = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=True)
    received_at = created()
    processed_at = Column(DateTime(timezone=True), nullable=True)