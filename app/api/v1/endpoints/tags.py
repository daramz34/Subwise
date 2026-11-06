import uuid

from fastapi import APIRouter, status

from app.core.deps import CurrentUser, DbSession
from app.schemas import DetailOut, TagCreate, TagOut
from app.services import tag_service

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
def list_tags(user: CurrentUser, db: DbSession):
    return tag_service.list_tags(db, user)


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(body: TagCreate, user: CurrentUser, db: DbSession):
    return tag_service.create_tag(db, user, body)


@router.delete("/{tag_id}", response_model=DetailOut)
def delete_tag(tag_id: uuid.UUID, user: CurrentUser, db: DbSession):
    tag_service.delete_tag(db, user, tag_id)
    return DetailOut(detail="Tag deleted")