from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import EmailList, EmailResult
from .validators import process_email

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Email Format Verifier")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/verify", response_model=list[EmailResult])
def verify_emails(request: EmailList) -> list[EmailResult]:
    return [process_email(address.strip()) for address in request.emails]
