# Email Format Verifier

A small FastAPI application that checks the syntax of a list of email addresses
and confirms that each address's domain exists in DNS. It does not send messages.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. API documentation is available at `/docs`.

## API

Send `GET /health` to check whether the service is running. A healthy service
responds with:

```json
{"status": "ok"}
```

Send `POST /api/verify` with:

```json
{"emails": ["jane@company.com", "john@@company.com"]}
```

Before validation, the service removes common copy/paste formatting, trims
whitespace, and normalizes domains (including internationalized domain names).
It then looks up the domain in DNS and immediately rejects an address when the
resolver confirms that its domain does not exist. Missing MX records alone do
not make an existing domain invalid, and temporary DNS failures are treated as
inconclusive rather than invalid.
The response includes both `original_email`, exactly as submitted, and `email`,
the cleaned and normalized value. Future checks can be appended to `OPERATIONS`
in `app/validators.py`.

## Nginx

Run the app as a service on `127.0.0.1:8000`, copy `nginx/emailverifier.conf` into Nginx's configuration, replace `example.com`, and reload Nginx.
