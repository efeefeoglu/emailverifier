# Email Verifier

A small FastAPI application that checks the syntax of a list of email addresses
and confirms that each address's domain publishes mail exchange (MX) records. It
does not send messages.

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
It then looks up the domain in DNS and rejects an address when the resolver
confirms that its domain does not exist or has neither an MX record nor the
A/AAAA address required for SMTP's implicit-MX fallback. Domains that use a Null
MX record to explicitly declare that they do not accept email are also rejected
without attempting an SMTP connection. Temporary DNS failures are treated as
inconclusive rather than invalid. When an explicit MX belongs to a recognized
mail service, the response's `provider` field identifies providers including
Google Workspace, Microsoft 365, Zoho, Mimecast, Proofpoint, and other common
services.

## SMTP mailbox verification

SMTP probing is opt-in because the verifier must use identities that you really
control. Set both variables before starting the application:

```bash
export SMTP_HELO_HOSTNAME=verifier.example.com
export SMTP_MAIL_FROM=probe@example.com
export SMTP_TIMEOUT=10
```

`SMTP_HELO_HOSTNAME` should be a legitimate, forward-confirmed hostname for this
server, and `SMTP_MAIL_FROM` must be an address under a domain you control. The
application connects to the recipient domain's MX servers on port 25 in priority
order, tries EHLO (falling back to HELO), issues `MAIL FROM` and `RCPT TO`, and
then closes the session without sending `DATA` or an email. A recipient-specific
permanent response such as `550 5.1.1` marks the address invalid. After the
server accepts the requested recipient, the application also tries a randomly
generated, highly improbable mailbox at the same domain. If both recipients are
accepted, `smtp_status` is `catch_all` rather than claiming that the individual
mailbox was confirmed. Anti-enumeration policies can still prevent a definitive
mailbox result.

The `smtp_status` response field reports `recipient_accepted`, `catch_all`,
`mailbox_not_found`, an inconclusive/rejected stage, or `not_configured`. Ensure
your host permits outbound TCP port 25 before enabling this check.
The response includes both `original_email`, exactly as submitted, and `email`,
the cleaned and normalized value. Future checks can be appended to `OPERATIONS`
in `app/validators.py`.

## Nginx

Run the app as a service on `127.0.0.1:8000`, copy `nginx/emailverifier.conf` into Nginx's configuration, replace `example.com`, and reload Nginx.
