from fastapi import APIRouter

from app.api.v1.endpoints import auth

api_router = APIRouter()
api_router.include_router(auth.router)
# Add each new endpoint module here as you build it:
# api_router.include_router(subscriptions.router)