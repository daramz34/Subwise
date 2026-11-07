from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.deps import CurrentUser, DbSession, UserPlan
from app.core.limiter import RateLimiter
from app.services import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=500)


@router.post("/ask", dependencies=[Depends(RateLimiter(times=10, seconds=60, scope="ai"))])
def ask(data: AskIn, user: CurrentUser, db: DbSession, plan: UserPlan):
    return ai_service.ask(db, user, plan, data.question)