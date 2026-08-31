from pathlib import Path

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import EmailList, EmailResult
from .security import require_api_key
from .validators import process_email

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Email Format Verifier")
allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/verify",
    response_model=list[EmailResult],
    dependencies=[Depends(require_api_key)],
)
def verify_emails(request: EmailList) -> list[EmailResult]:
    return [process_email(address) for address in request.emails]
