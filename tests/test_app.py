import dns.resolver
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def existing_dns_domain(monkeypatch) -> None:
    monkeypatch.setattr("app.validators.dns.resolver.resolve", lambda domain, rdtype: ())


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
    }


def test_domain_without_mx_records_still_exists(monkeypatch) -> None:
    def domain_without_mx(domain: str, rdtype: str) -> None:
        raise dns.resolver.NoAnswer

    monkeypatch.setattr("app.validators.dns.resolver.resolve", domain_without_mx)

    response = client.post("/api/verify", json={"emails": ["user@example.org"]})

    assert response.json()[0]["valid"] is True
