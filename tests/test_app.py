import dns.resolver
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
    }
    assert all(item["reason"] for item in results[1:])


def test_illegal_characters_are_rejected() -> None:
    response = client.post("/api/verify", json={"emails": ["john name@example.com"]})
    assert response.json()[0]["valid"] is False


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
