#!/usr/bin/env python3
"""Check a running local Botanika origin without uploading an image.

Usage: python tools/verify_connectivity.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    paths = ("/api/v1/health/live", "/api/v1/health/ready")
    failed = False
    for path in paths:
        try:
            with urlopen(f"{base_url}{path}", timeout=5) as response:  # noqa: S310 - operator-supplied verification URL
                payload = json.load(response)
                print(f"{response.status} {path}: {json.dumps(payload, sort_keys=True)}")
                if response.status != 200:
                    failed = True
        except (OSError, URLError, ValueError) as exc:
            print(f"FAIL {path}: {exc}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
