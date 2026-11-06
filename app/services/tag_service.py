from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Tag, User
from app.schemas import TagCreate


def list_tags(db: Session, user: User) -> list[Tag]:
    return list(
        db.scalars(
            select(Tag)
            .where(Tag.user_id == user.id)
            .order_by(func.lower(Tag.name))
        )
    )


def get_owned_tags(db: Session, user: User, tag_ids: list[UUID]) -> list[Tag]:
    if not tag_ids:
        return []

    tags = list(
        db.scalars(
            select(Tag)
            .where(Tag.user_id == user.id, Tag.id.in_(set(tag_ids)))
            .order_by(func.lower(Tag.name))
        )
    )
    if len(tags) != len(set(tag_ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    return tags


def create_tag(db: Session, user: User, data: TagCreate) -> Tag:
    existing = db.scalar(
        select(Tag.id).where(
            Tag.user_id == user.id,
            func.lower(Tag.name) == data.name.lower(),
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A tag with that name already exists")

    tag = Tag(user_id=user.id, name=data.name)
    db.add(tag)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A tag with that name already exists")
    db.refresh(tag)
    return tag


def delete_tag(db: Session, user: User, tag_id: UUID) -> None:
    tag = db.scalar(select(Tag).where(Tag.id == tag_id, Tag.user_id == user.id))
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    db.delete(tag)
    db.commit()
