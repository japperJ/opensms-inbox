# OpenSMS Inbox

A tiny self-hosted web inbox for [OpenSMS](https://github.com/daslearning-org/OpenSMS) webhooks. It receives the `sms.received` webhooks and keeps them in SQLite, with a searchable web UI.

- Verifies the `X-OpenSMS-Signature` HMAC when a secret is configured.
- Idempotent: OpenSMS retries are deduplicated by `delivery_id`.
- Newest-first inbox with search, detail view, raw payload and delete.
- Optional HTTP Basic auth for the UI; `/hook` always uses the HMAC secret.
- Auto-refreshes the list every 5 seconds (no JS build step).

## Quickstart

```bash
git clone https://github.com/japperJ/opensms-inbox.git
cd opensms-inbox
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export OPENMS_INBOX_SECRET="the-same-secret-as-in-opensms"
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8099
```

Open `http://<host>:8099`. The webhook endpoint is `POST /hook`.

Then on the phone: OpenSMS → Settings → Webhook URL = `http://<host>:8099/hook`, Signing Secret = the same value, enable, Save. Use **Send Test Webhook** to check it, then send an SMS to the phone.

With a LAN target, keep the phone and this server on the same network and make sure the port is allowed through the host firewall.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENMS_INBOX_DB` | `data/inbox.db` | SQLite file (created automatically) |
| `OPENMS_INBOX_SECRET` | empty | HMAC secret; leave empty to accept unsigned webhooks |
| `OPENMS_INBOX_USER` | empty | Basic auth user for the UI |
| `OPENMS_INBOX_PASSWORD` | empty | Basic auth password for the UI |
| `OPENMS_INBOX_TITLE` | `OpenSMS Inbox` | Page title |

`/hook` is never behind Basic auth: OpenSMS authenticates with the signature. If `OPENMS_INBOX_SECRET` is empty, anyone who can reach the port can inject messages, so set it.

## Docker

```bash
docker compose up -d --build
```

`docker-compose.yml` mounts `./data` for SQLite and exposes port 8099. Edit the environment block to set the secret and credentials.

## Endpoints

- `POST /hook` — accepts an OpenSMS webhook, returns `{"ok": true, "duplicate": false}`.
- `GET /` — inbox, `?q=` search, `?page=`.
- `GET /partials/messages` — HTML fragment used by the auto-refresh.
- `GET /messages/{id}` — detail and raw payload.
- `POST /messages/{id}/delete` — delete and redirect.
- `GET /health` — readiness probe.

## Tests

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

## Notes

- This is a LAN-oriented tool. Terminate TLS in a reverse proxy (Caddy, nginx) if it is reachable from the internet.
- One process per SQLite file. For multiple workers, use Postgres or a single worker.
- `webhook.test` events from the "Send Test" button are stored and shown with a `test` badge.
- MMS is not supported by OpenSMS, so only SMS payloads are expected.

## License

Apache-2.0, same as OpenSMS.
