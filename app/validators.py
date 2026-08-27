import os
import re
import secrets
import smtplib
import socket
from collections.abc import Callable
from email.utils import parseaddr

import dns.resolver
from email_validator import EmailNotValidError, validate_email

from .models import EmailResult


EmailOperation = Callable[[EmailResult], EmailResult]


def smtp_settings() -> tuple[str, str, float] | None:
    """Return the explicitly configured SMTP identity and envelope sender.

    SMTP probing is deliberately opt-in: an operator must supply a real,
    forward-confirmed hostname and an address on a domain they control rather
    than this application inventing identities that may be rejected or abused.
    """
    hostname = os.getenv("SMTP_HELO_HOSTNAME", "").strip().rstrip(".")
    mail_from = os.getenv("SMTP_MAIL_FROM", "").strip()
    if not hostname or not mail_from:
        return None
    try:
        timeout = max(1.0, float(os.getenv("SMTP_TIMEOUT", "10")))
    except ValueError:
        timeout = 10.0
    return hostname, mail_from, timeout


# MX hosts are matched on DNS label boundaries so, for example, a domain named
# ``notgoogle.com`` cannot be mistaken for Google. More-specific suffixes should
# precede their parent suffix when providers share a namespace.
MAIL_PROVIDER_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("mail.protection.outlook.com", "Microsoft 365"),
    ("googlemail.com", "Google Workspace"),
    ("google.com", "Google Workspace"),
    ("pphosted.com", "Proofpoint"),
    ("proofpoint.com", "Proofpoint"),
    ("mimecast.com", "Mimecast"),
    ("zoho.com", "Zoho"),
    ("zoho.eu", "Zoho"),
    ("zoho.in", "Zoho"),
    ("amazonses.com", "Amazon SES"),
    ("messagingengine.com", "Fastmail"),
    ("protonmail.ch", "Proton Mail"),
    ("protonmail.net", "Proton Mail"),
    ("icloud.com", "Apple iCloud Mail"),
    ("yahoodns.net", "Yahoo Mail"),
)


def detect_mail_provider(mx_hosts: list[str]) -> str | None:
    """Return the known provider serving one of the supplied MX hostnames."""
    for host in mx_hosts:
        normalized_host = host.rstrip(".").lower()
        for suffix, provider in MAIL_PROVIDER_SUFFIXES:
            if normalized_host == suffix or normalized_host.endswith(f".{suffix}"):
                return provider
    return None


def check_address_fallback(
    result: EmailResult, domain: str, ascii_domain: str
) -> EmailResult:
    """Apply SMTP's implicit-MX rule by looking for an A or AAAA address."""
    temporary_failure = False
    for record_type in ("A", "AAAA"):
        try:
            if list(dns.resolver.resolve(ascii_domain, record_type)):
                return result
        except dns.resolver.NXDOMAIN:
            return result.model_copy(
                update={"valid": False, "reason": f"The domain {domain} does not exist."}
            )
        except dns.resolver.NoAnswer:
            continue
        except (dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout):
            temporary_failure = True

    if temporary_failure:
        return result
    return result.model_copy(
        update={
            "valid": False,
            "reason": f"The domain {domain} has no MX, A, or AAAA records.",
        }
    )


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
    """Find a domain's explicit or implicit mail exchanger.

    Resolver failures are kept inconclusive because they do not establish that
    the domain cannot receive mail. NXDOMAIN, an authoritative empty MX answer,
    and Null MX declarations can be rejected without contacting a mail server.
    Per RFC 5321, a domain without MX records is still usable when its own A or
    AAAA record can act as an implicit, preference-zero MX.
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
        return check_address_fallback(result, domain, ascii_domain)
    except (dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout):
        return result

    mx_records = list(answers)
    if not mx_records:
        return check_address_fallback(result, domain, ascii_domain)

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

    mx_hosts = [record.exchange.to_text() for record in mx_records]
    return result.model_copy(update={"provider": detect_mail_provider(mx_hosts)})


MAILBOX_NOT_FOUND_CODES = {550, 551, 553}
MAILBOX_NOT_FOUND_MARKERS = (
    "5.1.1",
    "5.1.0",
    "user unknown",
    "unknown user",
    "no such user",
    "no such mailbox",
    "mailbox not found",
    "recipient not found",
    "invalid recipient",
)


def mailbox_not_found(code: int, message: bytes | str) -> bool:
    """Recognize permanent, recipient-specific mailbox rejections."""
    text = message.decode("utf-8", "replace") if isinstance(message, bytes) else message
    normalized = text.lower()
    return code in MAILBOX_NOT_FOUND_CODES and any(
        marker in normalized for marker in MAILBOX_NOT_FOUND_MARKERS
    )


def catch_all_probe_address(address: str) -> str:
    """Build an unpredictable mailbox address on the recipient's domain."""
    domain = address.rsplit("@", 1)[1]
    return f"email-verifier-{secrets.token_hex(16)}@{domain}"


def smtp_hosts(address: str) -> list[str]:
    """Resolve explicit MX hosts in preference order, or the implicit MX."""
    domain = address.rsplit("@", 1)[1].encode("idna").decode("ascii")
    try:
        records = list(dns.resolver.resolve(domain, "MX"))
    except dns.resolver.NoAnswer:
        return [domain]
    return [
        record.exchange.to_text().rstrip(".")
        for record in sorted(records, key=lambda record: record.preference)
        if record.exchange.to_text() != "."
    ]


def check_smtp(result: EmailResult) -> EmailResult:
    """Probe the SMTP envelope without sending message data."""
    settings = smtp_settings()
    if settings is None:
        return result.model_copy(update={"smtp_status": "not_configured"})

    hostname, mail_from, timeout = settings
    last_status = "connection_failed"
    try:
        hosts = smtp_hosts(result.email)
    except (dns.resolver.DNSException, UnicodeError):
        return result.model_copy(update={"smtp_status": "dns_inconclusive"})

    for host in hosts:
        try:
            with smtplib.SMTP(
                host=host,
                port=25,
                local_hostname=hostname,
                timeout=timeout,
            ) as smtp:
                code, _ = smtp.ehlo(hostname)
                if not 200 <= code < 300:
                    code, _ = smtp.helo(hostname)
                if not 200 <= code < 300:
                    last_status = "greeting_rejected"
                    continue

                code, _ = smtp.mail(mail_from)
                if not 200 <= code < 300:
                    last_status = "mail_from_rejected"
                    continue

                code, message = smtp.rcpt(result.email)
                if code in {250, 251, 252}:
                    # An accepted RCPT only establishes mailbox-specific evidence
                    # when the server rejects an unpredictable address at the same
                    # domain. If it accepts both, it is behaving as a catch-all.
                    probe_code, _ = smtp.rcpt(catch_all_probe_address(result.email))
                    if probe_code in {250, 251, 252}:
                        return result.model_copy(update={"smtp_status": "catch_all"})
                    return result.model_copy(update={"smtp_status": "recipient_accepted"})
                if mailbox_not_found(code, message):
                    return result.model_copy(
                        update={
                            "valid": False,
                            "smtp_status": "mailbox_not_found",
                            "reason": "The receiving mail server reports that this mailbox does not exist.",
                        }
                    )
                return result.model_copy(update={"smtp_status": "recipient_inconclusive"})
        except (OSError, smtplib.SMTPException, socket.timeout):
            continue
    return result.model_copy(update={"smtp_status": last_status})


# Add future per-address checks to this pipeline.
OPERATIONS: tuple[EmailOperation, ...] = (check_format, check_mx_records, check_smtp)


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
