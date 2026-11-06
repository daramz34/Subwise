from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Category, User
from app.schemas import CategoryCreate, CategoryUpdate


def _visible(user: User):
    """System defaults (user_id NULL) plus this user's own categories."""
    return or_(Category.user_id.is_(None), Category.user_id == user.id)


def _name_taken(db: Session, user: User, name: str, exclude_id=None) -> bool:
    stmt = select(Category.id).where(func.lower(Category.name) == name.lower(), _visible(user))
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    return db.scalar(stmt) is not None


def list_categories(db: Session, user: User) -> list[Category]:
    return list(db.scalars(
        select(Category).where(_visible(user)).order_by(Category.is_default.desc(), func.lower(Category.name))
    ))


def get_usable_category(db: Session, user: User, category_id) -> Category:
    """A category the user may attach to a subscription: a default or one they own.
    Someone else's category gives the same 404 as one that doesn't exist."""
    category = db.scalar(select(Category).where(Category.id == category_id, _visible(user)))
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return category


def create_category(db: Session, user: User, data: CategoryCreate) -> Category:
    if _name_taken(db, user, data.name):
        raise HTTPException(status.HTTP_409_CONFLICT, "A category with that name already exists")
    category = Category(user_id=user.id, name=data.name, color=data.color, icon=data.icon, is_default=False)
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A category with that name already exists")
    db.refresh(category)
    return category


def update_category(db: Session, user: User, category_id, data: CategoryUpdate) -> Category:
    category = get_usable_category(db, user, category_id)
    if category.user_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Default categories can't be edited")

    changes = data.model_dump(exclude_unset=True)
    if "name" in changes:
        if changes["name"] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name cannot be null")
        if _name_taken(db, user, changes["name"], exclude_id=category.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "A category with that name already exists")
    for field, value in changes.items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category