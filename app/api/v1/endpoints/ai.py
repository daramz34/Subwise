from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, DbSession, UserPlan
from app.core.limiter import RateLimiter
from app.schemas import AskIn, AskOut
from app.services import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/ask", response_model=AskOut,
             dependencies=[Depends(RateLimiter(times=10, seconds=60, scope="ai"))])
def ask(data: AskIn, user: CurrentUser, db: DbSession, plan: UserPlan):
    return ai_service.ask(db, user, plan, data.question)