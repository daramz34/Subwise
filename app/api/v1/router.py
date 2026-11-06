from fastapi import APIRouter

from app.api.v1.endpoints import auth, categories, subscriptions, tags

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(categories.router)
api_router.include_router(tags.router)
api_router.include_router(subscriptions.router)
# Add each new endpoint module here as you build it.