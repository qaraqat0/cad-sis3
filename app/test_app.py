"""Unit tests for the order API. Run: python -m unittest discover -s app -v
SNS is mocked, so the tests need no AWS account and no credentials."""
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:test-orders")
os.environ.setdefault("APP_VERSION", "test-sha")

with mock.patch("boto3.client") as fake_client:
    fake_client.return_value.publish.return_value = {"MessageId": "m-1"}
    import app  # noqa: E402


class OrderApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def call(self, path, method="GET"):
        req = urllib.request.Request(self.base + path, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def setUp(self):
        app.sns.publish.reset_mock()

    def test_health_returns_200(self):
        status, body = self.call("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, "ok")

    def test_root_reports_version(self):
        status, body = self.call("/")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["version"], "test-sha")

    def test_post_order_publishes_event_with_given_id(self):
        status, body = self.call("/orders?id=order-42", method="POST")
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(body)["eventId"], "order-42")
        sent = json.loads(app.sns.publish.call_args.kwargs["Message"])
        self.assertEqual(sent["eventId"], "order-42")
        self.assertEqual(sent["type"], "OrderCreated")

    def test_post_order_generates_id_when_missing(self):
        status, body = self.call("/orders", method="POST")
        self.assertEqual(status, 202)
        self.assertTrue(json.loads(body)["eventId"])

    def test_unknown_path_is_404(self):
        self.assertEqual(self.call("/nope")[0], 404)
        self.assertEqual(self.call("/nope", method="POST")[0], 404)
        app.sns.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
