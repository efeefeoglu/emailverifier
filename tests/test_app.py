import os

import dns.resolver
from fastapi.testclient import TestClient

os.environ["API_KEY"] = "test-key"

from app.main import app  # noqa: E402
from app.security import require_api_key  # noqa: E402

client = TestClient(app, headers={"X-API-Key": "test-key"})


class FakeExchange:
    def __init__(self, value: str) -> None:
        self.value = value

    def to_text(self) -> str:
        return self.value


class FakeMxRecord:
    def __init__(self, preference: int, exchange: str) -> None:
        self.preference = preference
        self.exchange = FakeExchange(exchange)


def existing_dns_domain(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.validators.dns.resolver.resolve",
        lambda domain, rdtype: [FakeMxRecord(10, "mail.example.com.")],
    )


def test_homepage() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Email Format Verifier" in response.text
    assert 'id="result-summary"' in response.text


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_verify_requires_a_valid_api_key() -> None:
    response = TestClient(app).post("/api/verify", json={"emails": ["a@b.com"]})
    assert response.status_code == 401
    response = TestClient(app).post(
        "/api/verify",
        headers={"X-API-Key": "wrong-key"},
        json={"emails": ["a@b.com"]},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "ApiKey"


def test_verify_is_unavailable_when_no_keys_are_configured(monkeypatch) -> None:
    monkeypatch.delenv("API_KEY")
    response = client.post("/api/verify", json={"emails": ["a@b.com"]})
    assert response.status_code == 503


def test_api_key_is_rate_limited(monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT", "1")
    require_api_key.reset()
    first = client.post("/api/verify", json={"emails": ["invalid"]})
    second = client.post("/api/verify", json={"emails": ["invalid"]})
    assert first.status_code == 200
    assert first.headers["x-ratelimit-remaining"] == "0"
    assert second.status_code == 429
    assert "retry-after" in second.headers
    require_api_key.reset()


def test_verify_rejects_oversized_batches() -> None:
    response = client.post("/api/verify", json={"emails": ["invalid"] * 101})
    assert response.status_code == 422


def test_verify_returns_one_result_per_address(monkeypatch) -> None:
    existing_dns_domain(monkeypatch)
    response = client.post(
        "/api/verify",
        json={"emails": ["jane@company.com", "john@@company.com", "john@"]},
    )

    assert response.status_code == 200
    results = response.json()
    assert [item["valid"] for item in results] == [True, False, False]
    assert results[0] == {
        "original_email": "jane@company.com",
        "email": "jane@company.com",
        "valid": True,
        "reason": None,
        "provider": None,
        "smtp_status": "not_configured",
    }
    assert all(item["reason"] for item in results[1:])


def test_illegal_characters_are_rejected() -> None:
    response = client.post("/api/verify", json={"emails": ["john name@example.com"]})
    assert response.json()[0]["valid"] is False


def test_role_accounts_are_rejected_without_dns_lookup(monkeypatch) -> None:
    def unexpected_dns_lookup(domain: str, rdtype: str) -> None:
        raise AssertionError("role account detection should run before DNS")

    monkeypatch.setattr("app.validators.dns.resolver.resolve", unexpected_dns_lookup)

    emails = [
        "info@company.com",
        "Sales@company.com",
        "support@company.com",
        "admin@company.com",
        "office@company.com",
        "billing@company.com",
        "marketing@company.com",
    ]
    results = client.post("/api/verify", json={"emails": emails}).json()

    assert all(result["valid"] is False for result in results)
    assert all("generic role account" in result["reason"] for result in results)


def test_free_email_providers_are_rejected_without_dns_lookup(monkeypatch) -> None:
    def unexpected_dns_lookup(domain: str, rdtype: str) -> None:
        raise AssertionError("free provider detection should run before DNS")

    monkeypatch.setattr("app.validators.dns.resolver.resolve", unexpected_dns_lookup)

    emails = [
        "person@gmail.com",
        "person@outlook.com",
        "person@yahoo.com",
        "person@icloud.com",
        "person@proton.me",
    ]
    results = client.post("/api/verify", json={"emails": emails}).json()

    assert [result["provider"] for result in results] == [
        "Gmail",
        "Outlook",
        "Yahoo Mail",
        "iCloud",
        "Proton Mail",
    ]
    assert all(result["valid"] is False for result in results)
    assert all("free email provider" in result["reason"] for result in results)


def test_provider_domain_must_match_exactly(monkeypatch) -> None:
    existing_dns_domain(monkeypatch)

    result = client.post(
        "/api/verify", json={"emails": ["person@notgmail.com"]}
    ).json()[0]

    assert result["valid"] is True


def test_addresses_are_cleaned_and_original_input_is_preserved(monkeypatch) -> None:
    existing_dns_domain(monkeypatch)
    submitted = "  mailto:Jane.Doe @ EXAMPLE.COM  "
    response = client.post("/api/verify", json={"emails": [submitted]})

    assert response.json()[0] == {
        "original_email": submitted,
        "email": "Jane.Doe@example.com",
        "valid": True,
        "reason": None,
        "provider": None,
        "smtp_status": "not_configured",
    }


def test_display_name_formatting_is_cleaned(monkeypatch) -> None:
    existing_dns_domain(monkeypatch)
    response = client.post(
        "/api/verify", json={"emails": ["Jane Doe <jane@example.com>"]}
    )

    assert response.json()[0]["email"] == "jane@example.com"
    assert response.json()[0]["valid"] is True


def test_internationalized_and_punycode_domains_share_a_normalized_form(
    monkeypatch,
) -> None:
    existing_dns_domain(monkeypatch)
    response = client.post(
        "/api/verify",
        json={"emails": ["user@BÜCHER.DE", "user@xn--bcher-kva.de"]},
    )

    results = response.json()
    assert [item["email"] for item in results] == ["user@bücher.de", "user@bücher.de"]
    assert all(item["valid"] for item in results)


def test_nonexistent_domain_is_rejected(monkeypatch) -> None:
    def nonexistent_domain(domain: str, rdtype: str) -> None:
        raise dns.resolver.NXDOMAIN

    monkeypatch.setattr("app.validators.dns.resolver.resolve", nonexistent_domain)

    response = client.post(
        "/api/verify", json={"emails": ["user@does-not-exist.example.net"]}
    )

    assert response.json()[0] == {
        "original_email": "user@does-not-exist.example.net",
        "email": "user@does-not-exist.example.net",
        "valid": False,
        "reason": "The domain does-not-exist.example.net does not exist.",
        "provider": None,
        "smtp_status": None,
    }


def test_domain_without_mx_or_address_records_is_rejected(monkeypatch) -> None:
    def domain_without_mail_dns(domain: str, rdtype: str) -> None:
        raise dns.resolver.NoAnswer

    monkeypatch.setattr("app.validators.dns.resolver.resolve", domain_without_mail_dns)

    response = client.post("/api/verify", json={"emails": ["user@example.org"]})

    assert response.json()[0] == {
        "original_email": "user@example.org",
        "email": "user@example.org",
        "valid": False,
        "reason": "The domain example.org has no MX, A, or AAAA records.",
        "provider": None,
        "smtp_status": None,
    }


def test_a_record_is_accepted_as_an_implicit_mx(monkeypatch) -> None:
    queried_types = []

    def implicit_mx(domain: str, rdtype: str):
        queried_types.append(rdtype)
        if rdtype == "A":
            return ["192.0.2.10"]
        raise dns.resolver.NoAnswer

    monkeypatch.setattr("app.validators.dns.resolver.resolve", implicit_mx)

    result = client.post("/api/verify", json={"emails": ["user@example.org"]}).json()[0]

    assert result["valid"] is True
    assert result["provider"] is None
    assert queried_types == ["MX", "A"]


def test_aaaa_record_is_accepted_as_an_implicit_mx(monkeypatch) -> None:
    def implicit_mx(domain: str, rdtype: str):
        if rdtype == "AAAA":
            return ["2001:db8::10"]
        raise dns.resolver.NoAnswer

    monkeypatch.setattr("app.validators.dns.resolver.resolve", implicit_mx)

    result = client.post("/api/verify", json={"emails": ["user@example.org"]}).json()[0]

    assert result["valid"] is True


def test_null_mx_domain_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.validators.dns.resolver.resolve",
        lambda domain, rdtype: [FakeMxRecord(0, ".")],
    )

    response = client.post("/api/verify", json={"emails": ["user@example.org"]})

    assert response.json()[0] == {
        "original_email": "user@example.org",
        "email": "user@example.org",
        "valid": False,
        "reason": "The domain example.org declares that it does not accept email.",
        "provider": None,
        "smtp_status": None,
    }


def test_common_mail_provider_is_detected_from_mx_hostname(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.validators.dns.resolver.resolve",
        lambda domain, rdtype: [
            FakeMxRecord(10, "ASPMX.L.GOOGLE.COM."),
            FakeMxRecord(20, "alt1.aspmx.l.google.com."),
        ],
    )

    result = client.post("/api/verify", json={"emails": ["user@example.org"]}).json()[0]

    assert result["valid"] is True
    assert result["provider"] == "Google Workspace"


def test_provider_suffix_must_match_on_dns_label_boundary(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.validators.dns.resolver.resolve",
        lambda domain, rdtype: [FakeMxRecord(10, "mx.notgoogle.com.")],
    )

    result = client.post("/api/verify", json={"emails": ["user@example.org"]}).json()[0]

    assert result["provider"] is None


def test_temporary_dns_failure_is_inconclusive(monkeypatch) -> None:
    def timed_out(domain: str, rdtype: str) -> None:
        raise dns.resolver.LifetimeTimeout

    monkeypatch.setattr("app.validators.dns.resolver.resolve", timed_out)

    response = client.post("/api/verify", json={"emails": ["user@example.org"]})

    assert response.json()[0]["valid"] is True


class FakeSMTP:
    instances = []

    def __init__(self, host, port, local_hostname, timeout) -> None:
        self.host = host
        self.port = port
        self.local_hostname = local_hostname
        self.timeout = timeout
        self.commands = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def ehlo(self, hostname):
        self.commands.append(("ehlo", hostname))
        return 500, b"EHLO unavailable"

    def helo(self, hostname):
        self.commands.append(("helo", hostname))
        return 250, b"hello"

    def mail(self, sender):
        self.commands.append(("mail", sender))
        return 250, b"sender ok"

    def rcpt(self, recipient):
        self.commands.append(("rcpt", recipient))
        return 250, b"recipient ok"


def configure_smtp(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HELO_HOSTNAME", "verifier.example.net")
    monkeypatch.setenv("SMTP_MAIL_FROM", "probe@example.net")
    monkeypatch.setenv("SMTP_TIMEOUT", "3")
    monkeypatch.setattr("app.validators.smtplib.SMTP", FakeSMTP)
    FakeSMTP.instances.clear()


def test_smtp_session_uses_configured_identity_and_envelope_sender(monkeypatch) -> None:
    existing_dns_domain(monkeypatch)
    configure_smtp(monkeypatch)
    monkeypatch.setattr(
        "app.validators.catch_all_probe_address",
        lambda address: "email-verifier-random@company.com",
    )

    result = client.post("/api/verify", json={"emails": ["jane@company.com"]}).json()[0]

    assert result["valid"] is True
    assert result["smtp_status"] == "catch_all"
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.local_hostname, smtp.timeout) == (
        "mail.example.com",
        25,
        "verifier.example.net",
        3.0,
    )
    assert smtp.commands == [
        ("ehlo", "verifier.example.net"),
        ("helo", "verifier.example.net"),
        ("mail", "probe@example.net"),
        ("rcpt", "jane@company.com"),
        ("rcpt", "email-verifier-random@company.com"),
    ]


def test_smtp_acceptance_is_mailbox_specific_when_random_recipient_is_rejected(
    monkeypatch,
) -> None:
    class NonCatchAllSMTP(FakeSMTP):
        def rcpt(self, recipient):
            self.commands.append(("rcpt", recipient))
            if recipient.startswith("email-verifier-"):
                return 550, b"5.1.1 User unknown"
            return 250, b"recipient ok"

    existing_dns_domain(monkeypatch)
    configure_smtp(monkeypatch)
    monkeypatch.setattr("app.validators.smtplib.SMTP", NonCatchAllSMTP)

    result = client.post("/api/verify", json={"emails": ["jane@company.com"]}).json()[0]

    assert result["valid"] is True
    assert result["smtp_status"] == "recipient_accepted"
    probe = NonCatchAllSMTP.instances[0].commands[-1][1]
    assert probe.startswith("email-verifier-")
    assert probe.endswith("@company.com")
    assert probe != "jane@company.com"


def test_smtp_550_511_marks_mailbox_as_not_found(monkeypatch) -> None:
    class RejectingSMTP(FakeSMTP):
        def rcpt(self, recipient):
            self.commands.append(("rcpt", recipient))
            return 550, b"5.1.1 User unknown"

    existing_dns_domain(monkeypatch)
    configure_smtp(monkeypatch)
    monkeypatch.setattr("app.validators.smtplib.SMTP", RejectingSMTP)

    result = client.post("/api/verify", json={"emails": ["missing@company.com"]}).json()[0]

    assert result["valid"] is False
    assert result["smtp_status"] == "mailbox_not_found"
    assert result["reason"] == (
        "The receiving mail server reports that this mailbox does not exist."
    )


def test_generic_recipient_policy_rejection_is_invalid(monkeypatch) -> None:
    class PolicyRejectingSMTP(FakeSMTP):
        def rcpt(self, recipient):
            return 550, b"5.7.1 Relay denied"

    existing_dns_domain(monkeypatch)
    configure_smtp(monkeypatch)
    monkeypatch.setattr("app.validators.smtplib.SMTP", PolicyRejectingSMTP)

    result = client.post("/api/verify", json={"emails": ["jane@company.com"]}).json()[0]

    assert result["valid"] is False
    assert result["smtp_status"] == "recipient_inconclusive"
    assert result["reason"] == (
        "The receiving mail server did not accept the recipient address."
    )
