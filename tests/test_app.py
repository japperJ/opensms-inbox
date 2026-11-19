import hashlib
import hmac
import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.main import create_app

SECRET = "test-secret"


def signed(body: bytes, secret: str = SECRET) -> dict:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-OpenSMS-Signature": f"sha256={digest}"}


def payload(delivery_id="d-1", sender="+14155552671", text="hello"):
    return {
        "event": "sms.received",
        "delivery_id": delivery_id,
        "received_at": "2026-11-19T21:34:29+01:00",
        "sent_at": "2026-11-19T20:34:28+00:00",
        "from": sender,
        "text": text,
        "parts": 1,
        "sim": {"subscription_id": 1},
    }


class AppTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {
            "OPENMS_INBOX_DB": os.path.join(self.tmp.name, "inbox.db"),
            "OPENMS_INBOX_SECRET": SECRET,
            "OPENMS_INBOX_USER": "",
            "OPENMS_INBOX_PASSWORD": "",
        }
        os.environ.update(self.env)
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        for key in self.env:
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def post(self, data, headers=None):
        body = json.dumps(data).encode()
        return self.client.post(
            "/hook", content=body, headers=headers or signed(body)
        )

    ## Webhook

    def test_accepts_signed_webhook(self):
        response = self.post(payload())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["duplicate"])

    def test_rejects_bad_signature(self):
        body = json.dumps(payload()).encode()
        response = self.client.post(
            "/hook", content=body,
            headers={"X-OpenSMS-Signature": "sha256=deadbeef"},
        )
        self.assertEqual(response.status_code, 401)

    def test_rejects_missing_signature(self):
        body = json.dumps(payload()).encode()
        response = self.client.post("/hook", content=body)
        self.assertEqual(response.status_code, 401)

    def test_rejects_invalid_json(self):
        body = b"not json"
        response = self.client.post("/hook", content=body, headers=signed(body))
        self.assertEqual(response.status_code, 400)

    def test_rejects_missing_event(self):
        body = json.dumps({"from": "x"}).encode()
        response = self.client.post("/hook", content=body, headers=signed(body))
        self.assertEqual(response.status_code, 400)

    def test_duplicate_delivery_is_idempotent(self):
        self.assertEqual(self.post(payload()).status_code, 200)
        second = self.post(payload())
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["duplicate"])
        page = self.client.get("/")
        self.assertIn("1 message", page.text)

    def test_unsigned_is_accepted_when_no_secret(self):
        os.environ["OPENMS_INBOX_SECRET"] = ""
        app = create_app()
        client = TestClient(app)
        body = json.dumps(payload()).encode()
        response = client.post("/hook", content=body)
        self.assertEqual(response.status_code, 200)
        client.close()

    ## Inbox UI

    def test_list_shows_message(self):
        self.post(payload(text="Your OTP is 123456"))
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("+14155552671", page.text)
        self.assertIn("Your OTP is 123456", page.text)

    def test_search_filters(self):
        self.post(payload(delivery_id="a", sender="BANK", text="code 1"))
        self.post(payload(delivery_id="b", sender="ALICE", text="dinner"))
        page = self.client.get("/?q=dinner")
        self.assertIn("ALICE", page.text)
        self.assertNotIn("BANK", page.text)

    def test_detail_and_raw_payload(self):
        self.post(payload())
        page = self.client.get("/messages/1")
        self.assertEqual(page.status_code, 200)
        self.assertIn("hello", page.text)
        self.assertIn("sms.received", page.text)

    def test_detail_missing(self):
        self.assertEqual(self.client.get("/messages/999").status_code, 404)

    def test_delete_message(self):
        self.post(payload())
        response = self.client.post(
            "/messages/1/delete", follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get("/messages/1").status_code, 404)

    def test_test_event_is_marked(self):
        data = {
            "event": "webhook.test",
            "delivery_id": "t-1",
            "sent_at": "2026-11-19T21:00:00+00:00",
        }
        self.post(data)
        page = self.client.get("/")
        self.assertIn("test", page.text)

    def test_partial_endpoint(self):
        self.post(payload())
        response = self.client.get("/partials/messages")
        self.assertEqual(response.status_code, 200)
        self.assertIn("+14155552671", response.text)

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"ok": True})

    ## Optional auth

    def test_basic_auth_protects_ui(self):
        os.environ["OPENMS_INBOX_USER"] = "admin"
        os.environ["OPENMS_INBOX_PASSWORD"] = "secret"
        app = create_app()
        client = TestClient(app)
        self.assertEqual(client.get("/").status_code, 401)
        allowed = client.get("/", auth=("admin", "secret"))
        self.assertEqual(allowed.status_code, 200)
        body = json.dumps(payload(delivery_id="auth-1")).encode()
        self.assertEqual(
            client.post("/hook", content=body, headers=signed(body)).status_code,
            200,
        )
        client.close()


if __name__ == "__main__":
    unittest.main()
