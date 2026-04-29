import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from config import settings
from routers.generate import router as generate_router
from services import db_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise SQLite on startup
    await db_service.init_db()
    yield


app = FastAPI(
    title="Event ROI Dashboard API",
    version="2.0.0",
    description="AI-powered post-event ROI report generator",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate_router, prefix="/api/generate", tags=["Generate"])


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    # Prevent path traversal
    safe_name = os.path.basename(filename)
    filepath = os.path.join(settings.temp_dir, safe_name)
    if not os.path.exists(filepath):
        from fastapi import HTTPException
        raise HTTPException(404, "File not found")

    ext = safe_name.rsplit(".", 1)[-1].lower()
    media_types = {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pdf": "application/pdf",
    }
    return FileResponse(
        filepath,
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=safe_name,
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


# Serve built React frontend in production
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")
