"""Import pipeline: upload -> extract -> review -> confirm (or undo).

Safety rule: nothing extracted from a file ever becomes a subscription on its own.
Extraction only writes ImportItem rows with status 'pending'. Subscriptions are created
in confirm_import(), and only for items the user explicitly confirmed."""
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CsvColumnMapping, ImportItem, ImportJob, Plan, Subscription, User
from app.schemas import (
    CsvColumnMappingCreate, ImportConfirmIn, ImportConfirmOut, ImportItemEdit, SubscriptionCreate,
)
from app.services import ai_client, storage, subscription_service
from app.services.ai_client import AIError
from app.services.audit import log_event, to_jsonable
from app.services.csv_parser import CsvError, parse_csv
from app.services.dates import next_renewal_from
from app.services.file_validation import FileRejected, validate_upload
from app.services.pattern_detector import detect_recurring
from app.services.redaction import redact_pii

logger = logging.getLogger(__name__)
MONEY = Decimal("0.01")
MAX_MONEY = Decimal("9999999999.99")


@dataclass
class Draft:
    """One suggested subscription, before the user has reviewed it."""
    name: str
    amount: Decimal | None
    currency: str | None
    interval: str | None
    last_date: date | None
    confidence: Decimal
    field_confidence: dict
    method: str
    occurrences: int = 1


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(value) -> Decimal | None:
    if value is None:
        return None
    quantised = Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)
    return quantised if 0 <= quantised <= MAX_MONEY else None


def _display_name(filename: str) -> str:
    base = re.split(r"[\\/]", filename or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return (base or "upload")[:255]


def _check_import_quota(db: Session, user: User, plan: Plan) -> None:
    limit = (plan.limits or {}).get("imports_per_month")
    if limit is None:
        return
    month_start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(
        select(func.count()).select_from(ImportJob).where(
            ImportJob.user_id == user.id, ImportJob.created_at >= month_start,
            ImportJob.status != "failed",  # a failed import doesn't use up your quota
        )
    )
    if used >= limit:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Your {plan.name} plan allows {limit} imports per month. Upgrade for more.",
        )


# --------------------------------------------------------------------------
# Column mappings
# --------------------------------------------------------------------------
def list_mappings(db: Session, user: User) -> list[CsvColumnMapping]:
    return list(db.scalars(
        select(CsvColumnMapping).where(CsvColumnMapping.user_id == user.id).order_by(CsvColumnMapping.name)
    ))


def create_mapping(db: Session, user: User, data: CsvColumnMappingCreate) -> CsvColumnMapping:
    taken = db.scalar(select(CsvColumnMapping.id).where(
        CsvColumnMapping.user_id == user.id, func.lower(CsvColumnMapping.name) == data.name.lower()))
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a mapping with that name")
    mapping = CsvColumnMapping(user_id=user.id, name=data.name, mapping=data.mapping)
    db.add(mapping)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a mapping with that name")
    db.refresh(mapping)
    return mapping


def _owned_mapping(db: Session, user: User, mapping_id) -> CsvColumnMapping:
    row = db.scalar(select(CsvColumnMapping).where(
        CsvColumnMapping.id == mapping_id, CsvColumnMapping.user_id == user.id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Column mapping not found")
    return row


# --------------------------------------------------------------------------
# Extraction (writes pending items only)
# --------------------------------------------------------------------------
def _drafts_from_csv(content: bytes, mapping: dict | None, user: User) -> list[Draft]:
    parsed = parse_csv(content, mapping, settings.MAX_CSV_ROWS)
    drafts = []
    for c in detect_recurring(parsed.transactions):
        field_confidence = dict(c.field_confidence)
        field_confidence["currency"] = 0.95 if c.currency else 0.4  # guessed from the user's default
        drafts.append(Draft(
            name=c.name, amount=c.amount, currency=c.currency or user.default_currency,
            interval=c.interval, last_date=c.last_date, confidence=c.confidence,
            field_confidence=field_confidence, method="pattern", occurrences=c.occurrences,
        ))
    return drafts


def _drafts_from_ai(*, text: str | None = None, file_bytes: bytes | None = None,
                    media_type: str | None = None) -> list[Draft]:
    raw = ai_client.call_ai_extraction(text=text, file_bytes=file_bytes, media_type=media_type)
    drafts = []
    for item in ai_client.parse_ai_output(raw):
        drafts.append(Draft(
            name=item.name, amount=_money(item.amount), currency=item.currency, interval=item.interval,
            last_date=item.charge_date,
            confidence=Decimal(str(round(float(item.confidence), 3))),
            field_confidence={k: max(0.0, min(1.0, float(v))) for k, v in item.field_confidence.items()
                              if isinstance(v, (int, float))},
            method="ai",
        ))
    return drafts


def _store_items(db: Session, user: User, job: ImportJob, drafts: list[Draft]) -> None:
    for draft in drafts:
        duplicates = subscription_service.find_similar_ids(db, user, draft.name)
        db.add(ImportItem(
            import_job_id=job.id,
            extracted_name=draft.name,
            extracted_amount=draft.amount,
            extracted_currency=draft.currency,
            extracted_interval=draft.interval,
            extracted_date=draft.last_date,
            confidence=draft.confidence,
            field_confidence=draft.field_confidence,
            detection_method=draft.method,
            occurrences_count=draft.occurrences,
            duplicate_of_id=duplicates[0] if duplicates else None,
            status="pending",
        ))


def _fail_job(db: Session, job_id, message: str) -> None:
    db.rollback()
    job = db.get(ImportJob, job_id)
    job.status = "failed"
    job.error_message = message
    job.completed_at = _now()
    db.commit()


def _process_job(db: Session, user: User, job: ImportJob, *, content: bytes | None = None,
                 media_type: str | None = None, mapping: dict | None = None,
                 text: str | None = None) -> ImportJob:
    job_id = job.id
    try:
        if job.file_type == "csv":
            drafts = _drafts_from_csv(content, mapping, user)
        elif job.file_type == "email_text":
            drafts = _drafts_from_ai(text=text)
        else:
            drafts = _drafts_from_ai(file_bytes=content, media_type=media_type)

        _store_items(db, user, job, drafts)
        job.items_detected = len(drafts)
        if drafts:
            job.status = "review"
        else:
            job.status = "completed"       # nothing found: there is nothing to review
            job.completed_at = _now()
        db.commit()
    except (CsvError, AIError) as exc:
        _fail_job(db, job_id, str(exc))
    except Exception:
        logger.exception("Import job %s crashed", job_id)
        _fail_job(db, job_id, "Something went wrong while processing this file. Please try again.")
    db.refresh(job)
    return job


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------
def create_import_from_file(db: Session, user: User, plan: Plan, filename: str, content: bytes,
                            mapping_id=None) -> ImportJob:
    try:
        validated = validate_upload(filename, content, settings.MAX_UPLOAD_BYTES)
    except FileRejected as exc:
        raise HTTPException(exc.status_code, exc.message)
    _check_import_quota(db, user, plan)

    mapping_row = _owned_mapping(db, user, mapping_id) if mapping_id else None
    job = ImportJob(
        user_id=user.id, file_name=_display_name(filename), file_type=validated.file_type,
        status="processing", column_mapping_id=mapping_row.id if mapping_row else None,
        redaction_applied=False,  # files go to the AI as uploaded; only pasted text is redacted
    )
    db.add(job)
    db.flush()
    try:
        job.storage_path = storage.save_upload(user.id, job.id, validated.extension, content)
    except (OSError, ValueError):
        db.rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Couldn't store the upload. Please try again.")
    db.commit()

    return _process_job(db, user, job, content=content, media_type=validated.media_type,
                        mapping=mapping_row.mapping if mapping_row else None)


def create_import_from_email(db: Session, user: User, plan: Plan, text: str) -> ImportJob:
    _check_import_quota(db, user, plan)
    job = ImportJob(user_id=user.id, file_name=None, file_type="email_text", status="processing",
                    redaction_applied=True)
    db.add(job)
    db.commit()
    # The raw text is never stored; only the redacted version is sent to the AI
    return _process_job(db, user, job, text=redact_pii(text))


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------
def get_job(db: Session, user: User, job_id) -> ImportJob:
    job = db.scalar(select(ImportJob).where(ImportJob.id == job_id, ImportJob.user_id == user.id))
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return job


def list_jobs(db: Session, user: User) -> list[ImportJob]:
    return list(db.scalars(
        select(ImportJob).where(ImportJob.user_id == user.id).order_by(ImportJob.created_at.desc()).limit(50)
    ))


def list_items(db: Session, user: User, job_id) -> list[ImportItem]:
    job = get_job(db, user, job_id)
    return list(db.scalars(
        select(ImportItem).where(ImportItem.import_job_id == job.id)
        .order_by(ImportItem.confidence.desc().nulls_last(), ImportItem.extracted_name)
    ))


# --------------------------------------------------------------------------
# Confirm
# --------------------------------------------------------------------------
_EDIT_TO_CONFIDENCE_KEY = {
    "extracted_name": "name", "extracted_amount": "amount", "extracted_currency": "currency",
    "extracted_interval": "interval", "extracted_date": "date",
}


def _apply_edits(item: ImportItem, edits: ImportItemEdit) -> None:
    changes = edits.model_dump(exclude_unset=True, exclude_none=True)
    record = dict(item.user_edits or {})
    confidence = dict(item.field_confidence or {})
    for field_name, value in changes.items():
        old = getattr(item, field_name)
        if old != value:
            record[field_name] = {"from": old, "to": value}
        setattr(item, field_name, value)
        confidence[_EDIT_TO_CONFIDENCE_KEY[field_name]] = 1.0  # the user checked it themselves
    if record:
        item.user_edits = to_jsonable(record)
        item.field_confidence = confidence


def _require_complete(item: ImportItem) -> None:
    missing = [label for label, value in (("a name", item.extracted_name), ("an amount", item.extracted_amount),
                                          ("a currency", item.extracted_currency)) if not value]
    if missing:
        raise HTTPException(
            422, f"'{item.extracted_name or 'An item'}' is missing {', '.join(missing)}. Edit it before confirming.")


def _check_capacity(db: Session, user: User, plan: Plan, to_add: int) -> None:
    limit = (plan.limits or {}).get("max_subscriptions")
    if limit is None or to_add == 0:
        return
    count = db.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.user_id == user.id, Subscription.archived_at.is_(None)))
    if count + to_add > limit:
        room = max(limit - count, 0)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Your {plan.name} plan allows up to {limit} subscriptions, so you can add {room} more. "
            "Deselect some items or upgrade.")


def _create_from_item(db: Session, user: User, plan: Plan, item: ImportItem, source: str) -> Subscription:
    interval = item.extracted_interval or "month"
    today = datetime.now(timezone.utc).date()
    try:
        data = SubscriptionCreate(
            name=item.extracted_name, amount=item.extracted_amount, currency=item.extracted_currency,
            billing_interval=interval, interval_count=1,
            next_renewal_date=next_renewal_from(item.extracted_date, interval, today),
            acknowledge_duplicate=True,  # the review screen already showed the duplicate warning
        )
    except ValidationError as exc:
        raise HTTPException(422, f"'{item.extracted_name}' has invalid values: {exc.errors()[0]['msg']}")
    return subscription_service.create_subscription(
        db, user, plan, data, source=source, commit=False, price_effective_date=item.extracted_date)


def confirm_import(db: Session, user: User, plan: Plan, job_id, data: ImportConfirmIn) -> ImportConfirmOut:
    job = get_job(db, user, job_id)
    if job.status != "review" or job.undone_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This import is no longer open for review.")

    item_ids = [d.item_id for d in data.decisions]
    items = {i.id: i for i in db.scalars(
        select(ImportItem).where(ImportItem.import_job_id == job.id, ImportItem.id.in_(item_ids)))}
    if len(items) != len(item_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import item not found")

    source = "email_paste" if job.file_type == "email_text" else "import"
    rejected = skipped = 0
    created_ids = []
    try:
        to_create = []
        for decision in data.decisions:
            item = items[decision.item_id]
            if item.status != "pending":
                skipped += 1            # already decided: confirming twice can't create twice
            elif decision.action == "reject":
                item.status = "rejected"
                rejected += 1
            else:
                if decision.edits:
                    _apply_edits(item, decision.edits)
                _require_complete(item)
                to_create.append(item)

        _check_capacity(db, user, plan, len(to_create))   # all-or-nothing, never a half import
        for item in to_create:
            sub = _create_from_item(db, user, plan, item, source)
            item.status = "confirmed"
            item.subscription_id = sub.id
            created_ids.append(sub.id)

        job.items_confirmed += len(created_ids)
        db.flush()
        pending = db.scalar(select(func.count()).select_from(ImportItem).where(
            ImportItem.import_job_id == job.id, ImportItem.status == "pending"))
        if pending == 0:
            job.status = "completed"
            job.completed_at = _now()
        log_event(db, user.id, "import", job.id, "confirm",
                  new={"created": len(created_ids), "rejected": rejected, "skipped": skipped})
        db.commit()
    except HTTPException:
        db.rollback()                   # nothing from this request is kept
        raise
    return ImportConfirmOut(created_subscription_ids=created_ids, rejected_count=rejected, skipped_count=skipped)


# --------------------------------------------------------------------------
# Undo
# --------------------------------------------------------------------------
def undo_import(db: Session, user: User, job_id) -> ImportJob:
    job = get_job(db, user, job_id)
    if job.undone_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This import was already undone.")
    confirmed = list(db.scalars(select(ImportItem).where(
        ImportItem.import_job_id == job.id, ImportItem.status == "confirmed",
        ImportItem.subscription_id.is_not(None))))
    if not confirmed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing from this import has been added, so there is nothing to undo.")

    now = _now()
    archived = 0
    for item in confirmed:
        sub = db.scalar(select(Subscription).where(
            Subscription.id == item.subscription_id, Subscription.user_id == user.id,
            Subscription.archived_at.is_(None)))
        if sub is not None:             # skip ones the user already archived themselves
            old = subscription_service.snapshot_subscription(sub)
            sub.archived_at = now
            log_event(db, user.id, "subscription", sub.id, "import_undo",
                      old=old, new=subscription_service.snapshot_subscription(sub))
            archived += 1
    job.undone_at = now
    log_event(db, user.id, "import", job.id, "undo", new={"archived": archived})
    db.commit()
    db.refresh(job)
    return job