"""SIS 3 demo app: tiny order API that publishes an OrderCreated domain event to SNS.

GET  /health          -> 200 ok (ALB health check)
GET  /                -> which task answered (shows load balancing)
POST /orders          -> publish OrderCreated with a new eventId
POST /orders?id=X     -> publish with a fixed eventId X (to demo deduplication)
"""
import datetime
import json
import os
import socket
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import boto3

TOPIC_ARN = os.environ["TOPIC_ARN"]
APP_ENV = os.environ.get("APP_ENV", "dev")
sns = boto3.client("sns", region_name=os.environ.get("AWS_REGION", "us-east-1"))
HOST = socket.gethostname()


def log(**kw):
    print(json.dumps(kw), flush=True)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, "ok", "text/plain")
        if path == "/":
            return self._send(200, {"service": "sis3-orders", "env": APP_ENV, "task": HOST})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/orders":
            return self._send(404, {"error": "not found"})
        qs = parse_qs(url.query)
        event_id = qs.get("id", [str(uuid.uuid4())])[0]
        event = {
            "eventId": event_id,
            "type": "OrderCreated",
            "orderId": event_id,
            "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "producer": HOST,
        }
        resp = sns.publish(TopicArn=TOPIC_ARN, Message=json.dumps(event))
        log(action="published", eventId=event_id, snsMessageId=resp["MessageId"])
        return self._send(202, {"accepted": True, "eventId": event_id})

    def log_message(self, fmt, *args):  # access log as JSON, skip health-check noise
        if "/health" not in self.path:
            log(access=fmt % args)


if __name__ == "__main__":
    log(action="start", env=APP_ENV, task=HOST)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
