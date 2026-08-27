import re
from collections.abc import Callable
from email.utils import parseaddr

import dns.resolver
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


def check_mx_records(result: EmailResult) -> EmailResult:
    """Reject domains that do not publish a usable MX record.

    Resolver failures are kept inconclusive because they do not establish that
    the domain cannot receive mail. NXDOMAIN, an authoritative empty MX answer,
    and Null MX declarations can be rejected without contacting a mail server.
    """
    domain = result.email.rsplit("@", 1)[1]
    ascii_domain = domain.encode("idna").decode("ascii")

    try:
        answers = dns.resolver.resolve(ascii_domain, "MX")
    except dns.resolver.NXDOMAIN:
        return result.model_copy(
            update={"valid": False, "reason": f"The domain {domain} does not exist."}
        )
    except dns.resolver.NoAnswer:
        return result.model_copy(
            update={"valid": False, "reason": f"The domain {domain} has no MX records."}
        )
    except (dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout):
        return result

    mx_records = list(answers)
    if not mx_records:
        return result.model_copy(
            update={"valid": False, "reason": f"The domain {domain} has no MX records."}
        )

    # RFC 7505 represents Null MX as a priority-zero record whose exchange is
    # the DNS root (serialized by dnspython as a single dot).
    if any(
        record.preference == 0 and record.exchange.to_text() == "."
        for record in mx_records
    ):
        return result.model_copy(
            update={
                "valid": False,
                "reason": f"The domain {domain} declares that it does not accept email.",
            }
        )

    return result


# Add future per-address checks to this pipeline.
OPERATIONS: tuple[EmailOperation, ...] = (check_format, check_mx_records)


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
