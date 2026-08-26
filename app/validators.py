from collections.abc import Callable

from email_validator import EmailNotValidError, validate_email

from .models import EmailResult


EmailOperation = Callable[[EmailResult], EmailResult]


def check_format(result: EmailResult) -> EmailResult:
    """Validate email syntax only; this operation never makes network requests."""
    try:
        validate_email(result.email, check_deliverability=False)
    except EmailNotValidError as error:
        return result.model_copy(update={"valid": False, "reason": str(error)})
    return result


# Add future per-address checks to this pipeline.
OPERATIONS: tuple[EmailOperation, ...] = (check_format,)


def process_email(address: str) -> EmailResult:
    result = EmailResult(email=address, valid=True)
    for operation in OPERATIONS:
        result = operation(result)
        if not result.valid:
            break
    return result
