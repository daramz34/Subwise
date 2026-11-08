from fastapi import APIRouter

from app.api.v1.endpoints import auth, categories, imports, subscriptions, tags, analytics, payments, ai, notifications

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(categories.router)
api_router.include_router(tags.router)
api_router.include_router(subscriptions.router)
api_router.include_router(imports.router)
api_router.include_router(analytics.router)
api_router.include_router(payments.plans_router)
api_router.include_router(payments.router)
api_router.include_router(ai.router)
api_router.include_router(notifications.router)
# Add each new endpoint module here as you build it.