# Email Format Verifier

A small FastAPI application that checks the syntax of a list of email addresses. It does not perform DNS lookups or send messages.

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

The response is an array with a result for each input address. Future checks can be appended to `OPERATIONS` in `app/validators.py`.

## Nginx

Run the app as a service on `127.0.0.1:8000`, copy `nginx/emailverifier.conf` into Nginx's configuration, replace `example.com`, and reload Nginx.
