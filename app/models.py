from pydantic import BaseModel, Field


class EmailList(BaseModel):
    emails: list[str] = Field(min_length=1, max_length=100)


class EmailResult(BaseModel):
    original_email: str
    email: str
    valid: bool
    reason: str | None = None
    provider: str | None = None
    smtp_status: str | None = None
