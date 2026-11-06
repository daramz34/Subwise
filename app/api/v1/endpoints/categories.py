import uuid

from fastapi import APIRouter, status

from app.core.deps import CurrentUser, DbSession
from app.schemas import CategoryCreate, CategoryOut, CategoryUpdate
from app.services import category_service

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(user: CurrentUser, db: DbSession):
    return category_service.list_categories(db, user)


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryCreate, user: CurrentUser, db: DbSession):
    return category_service.create_category(db, user, body)


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(category_id: uuid.UUID, body: CategoryUpdate, user: CurrentUser, db: DbSession):
    return category_service.update_category(db, user, category_id, body)
