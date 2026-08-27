import re
from collections.abc import Callable
from email.utils import parseaddr

from email_validator import EmailNotValidError, validate_email

from .models import EmailResult


EmailOperation = Callable[[EmailResult], EmailResult]


def clean_email(address: str) -> str:
    """Remove common copy/paste artifacts before validating an address."""
    cleaned = address.strip().removeprefix("\ufeff")

    if cleaned.lower().startswith("mailto:"):
        cleaned = cleaned[7:].strip()

    # Accept addresses copied in the conventional ``Name <address>`` form, but
    # only when the parser can account for the complete input.
    display_name, parsed_address = parseaddr(cleaned)
    if display_name and parsed_address and cleaned.endswith(">"):
        cleaned = parsed_address
    elif cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1].strip()

    # Spaces around separators are common spreadsheet and document artifacts.
    cleaned = re.sub(r"\s*@\s*", "@", cleaned)
    if "@" in cleaned:
        local_part, domain = cleaned.rsplit("@", 1)
        domain = re.sub(r"\s*\.\s*", ".", domain)
        cleaned = f"{local_part}@{domain}"

    return cleaned


def check_format(result: EmailResult) -> EmailResult:
    """Validate email syntax only; this operation never makes network requests."""
    try:
        validated = validate_email(result.email, check_deliverability=False)
    except EmailNotValidError as error:
        return result.model_copy(update={"valid": False, "reason": str(error)})
    return result.model_copy(update={"email": validated.normalized})


# Add future per-address checks to this pipeline.
OPERATIONS: tuple[EmailOperation, ...] = (check_format,)


def process_email(address: str) -> EmailResult:
    result = EmailResult(
        original_email=address,
        email=clean_email(address),
        valid=True,
    )
    for operation in OPERATIONS:
        result = operation(result)
        if not result.valid:
            break
    return result
