"""Shared helpers for the posting scripts."""
import os
import sys
import time
import json


def env(name, required=True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        print(f"ERROR: missing required environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return val


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def describe_error(e):
    """Format an exception for logging, including the response body when
    it's a requests HTTPError -- that body is where Meta/TikTok actually put
    the useful error (e.g. Graph API's {"error": {"message": ..., "code": ...}}).
    Plain str(e) on an HTTPError is just "400 Client Error: Bad Request for
    url: ..." with no indication of *why*, which makes failures like an
    expired access token indistinguishable from a malformed request in the
    logs. Falls back to str(e) for anything without a response body."""
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            body = resp.text
        except Exception:
            body = "<unreadable response body>"
        return f"{e} | response body: {body}"
    return str(e)


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
