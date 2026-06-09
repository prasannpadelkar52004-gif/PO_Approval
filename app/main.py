"""
PO Approval System — FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.po import router as po_router
from app.api.v1.endpoints.html_routes import router as html_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs on startup — seeds first superuser if not exists."""
    await _seed_superuser()
    yield


async def _seed_superuser():
    from sqlalchemy import select
    from app.models.models import User, UserRole
    from app.api.v1.deps import hash_password

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)
        )
        if not result.scalar_one_or_none():
            admin = User(
                email=settings.FIRST_SUPERUSER_EMAIL,
                full_name="System Admin",
                hashed_password=hash_password(settings.FIRST_SUPERUSER_PASSWORD),
                role=UserRole.ADMIN,
                is_superuser=True,
            )
            session.add(admin)
            await session.commit()


app = FastAPI(
    title=settings.APP_NAME,
    description="Digital PO Approval System for Construction & Real Estate",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Static files ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")
from fastapi.staticfiles import StaticFiles
import os
os.makedirs("app/static/uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="app/static/uploads"), name="uploads")

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(html_router)              # HTML pages (browser UI)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(po_router,   prefix="/api/v1")

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "app": settings.APP_NAME}
