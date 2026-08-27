from pydantic import BaseModel


class EmailList(BaseModel):
    emails: list[str]


class EmailResult(BaseModel):
    original_email: str
    email: str
    valid: bool
    reason: str | None = None
