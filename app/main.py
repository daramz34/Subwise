
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(title=settings.APP_NAME, version=settings.VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

FRONTEND_DIST = (
    Path(__file__).resolve().parent.parent
    / "frontend"
    / "dist"
)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    index_file = FRONTEND_DIST / "index.html"

    if not index_file.exists():
        raise HTTPException(
            status_code=503,
            detail="Frontend has not been built"
        )

    requested_file = (FRONTEND_DIST / full_path).resolve()

    if (
        requested_file.is_relative_to(FRONTEND_DIST.resolve())
        and requested_file.is_file()
    ):
        return FileResponse(requested_file)

    return FileResponse(index_file)
