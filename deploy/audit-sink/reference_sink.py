#!/usr/bin/env python3
"""Reference append-only audit sink (v10 follow-up).

The NanoClaw audit checkpoint forwarder (mps_server/services/audit.py) POSTs each
signed checkpoint head to an external append-only sink with:
  - bearer auth (Authorization: Bearer <token>) and/or mTLS,
  - an Idempotency-Key header derived from the audit entry hash,
  - text/plain body: "ts\\tentry_id\\tentry_hash[\\tsignature]".

This is a MINIMAL, dependency-free reference the production sink must behave like.
It is NOT the production sink — it documents and lets you contract-test the exact
behaviour the forwarder relies on:

  1. Authentication: reject requests without the expected bearer token (401).
  2. Idempotency: a repeated Idempotency-Key stores exactly one record (200).
  3. Immutability/append-only: a key may not be overwritten with a different body
     (409); existing records are never mutated or deleted.
  4. Durability: records are appended to a file that is only ever appended to.

Run:  AUDIT_SINK_TOKEN=secret AUDIT_SINK_FILE=/tmp/sink.log \\
      python3 reference_sink.py 127.0.0.1 8088
(Default host 127.0.0.1, port 8088.)

The production deployment must additionally provide: TLS, WORM/immutable storage
(e.g. object-lock S3 / append-only log service), retention policy, access control
and monitoring. Those are operational and out of this reference's scope.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_LOCK = threading.Lock()
_SEEN = {}  # idempotency-key -> body bytes (in-memory dedup mirror of the file)


def _token() -> str:
    return os.getenv("AUDIT_SINK_TOKEN", "").strip()


def _sink_file() -> str:
    return os.getenv("AUDIT_SINK_FILE", "/tmp/audit_sink.log")


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, msg=""):
        body = json.dumps({"status": code, "message": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # (1) authentication
        expected = _token()
        if expected:
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {expected}":
                return self._reply(401, "missing or invalid bearer token")

        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        key = self.headers.get("Idempotency-Key", "")
        if not key:
            return self._reply(400, "Idempotency-Key header required")

        with _LOCK:
            if key in _SEEN:
                # (2) idempotency / (3) immutability
                if _SEEN[key] == body:
                    return self._reply(200, "duplicate ignored (idempotent)")
                return self._reply(409, "key already stored with different body "
                                        "(append-only sink is immutable)")
            # (4) durable append-only write
            _SEEN[key] = body
            with open(_sink_file(), "ab") as fh:
                fh.write(key.encode() + b"\t" + body + b"\n")
        return self._reply(200, "stored")

    def log_message(self, *args):
        pass  # quiet


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8088
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"reference audit sink on http://{host}:{port} "
          f"(token={'set' if _token() else 'NONE'}, file={_sink_file()})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
