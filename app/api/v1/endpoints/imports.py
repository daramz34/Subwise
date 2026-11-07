import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, UserPlan
from app.core.limiter import RateLimiter
from app.schemas import (
    CsvColumnMappingCreate, CsvColumnMappingOut, EmailPasteIn, ImportConfirmIn, ImportConfirmOut,
    ImportItemOut, ImportJobOut,
)
from app.services import import_service

router = APIRouter(prefix="/imports", tags=["imports"])
import_limit = Depends(RateLimiter(times=10, seconds=60, scope="import"))


@router.post("", response_model=ImportJobOut, status_code=status.HTTP_201_CREATED, dependencies=[import_limit])
def upload_import(
    user: CurrentUser, plan: UserPlan, db: DbSession,
    file: Annotated[UploadFile, File()],
    mapping_id: Annotated[uuid.UUID | None, Form()] = None,
):
    """Upload a CSV statement, a PDF or a PNG/JPG receipt. The response is the import job:
    check its `status` ('review' means items are waiting for you, 'failed' explains why)."""
    content = file.file.read(settings.MAX_UPLOAD_BYTES + 1)  # never read more than the limit
    return import_service.create_import_from_file(db, user, plan, file.filename or "", content, mapping_id)


@router.post("/email", response_model=ImportJobOut, status_code=status.HTTP_201_CREATED, dependencies=[import_limit])
def import_from_email(body: EmailPasteIn, user: CurrentUser, plan: UserPlan, db: DbSession):
    return import_service.create_import_from_email(db, user, plan, body.text)


@router.get("", response_model=list[ImportJobOut])
def import_history(user: CurrentUser, db: DbSession):
    return import_service.list_jobs(db, user)


# Declared BEFORE /{import_id}, otherwise "mappings" would be read as an id
@router.get("/mappings", response_model=list[CsvColumnMappingOut])
def list_mappings(user: CurrentUser, db: DbSession):
    return import_service.list_mappings(db, user)


@router.post("/mappings", response_model=CsvColumnMappingOut, status_code=status.HTTP_201_CREATED)
def create_mapping(body: CsvColumnMappingCreate, user: CurrentUser, db: DbSession):
    return import_service.create_mapping(db, user, body)


@router.get("/{import_id}", response_model=ImportJobOut)
def get_import(import_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return import_service.get_job(db, user, import_id)


@router.get("/{import_id}/items", response_model=list[ImportItemOut])
def get_import_items(import_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return import_service.list_items(db, user, import_id)


@router.post("/{import_id}/confirm", response_model=ImportConfirmOut)
def confirm_import(import_id: uuid.UUID, body: ImportConfirmIn, user: CurrentUser, plan: UserPlan, db: DbSession):
    return import_service.confirm_import(db, user, plan, import_id, body)


@router.post("/{import_id}/undo", response_model=ImportJobOut)
def undo_import(import_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return import_service.undo_import(db, user, import_id)