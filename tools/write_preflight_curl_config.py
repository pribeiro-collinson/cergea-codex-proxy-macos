#!/usr/bin/env python3
"""Write a private temporary curl config without exposing the token in argv."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def quote_curl(value: str) -> str:
    """Quote a curl-config string using curl's backslash escaping rules."""
    if "\n" in value or "\r" in value:
        raise ValueError("newline characters are not permitted in curl config values")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: write_preflight_curl_config.py OUTPUT_PATH", file=sys.stderr)
        return 2
    key = os.environ.get("CERGEA_LITELLM_API_KEY", "")
    if not key or "\n" in key or "\r" in key:
        print("The API key is empty or contains a newline.", file=sys.stderr)
        return 2
    output = Path(sys.argv[1])
    config = [
        'url = ' + quote_curl("https://litellm.platform.com-eng.cergea.com/v1/chat/completions"),
        'request = "POST"',
        'header = ' + quote_curl("Authorization: Bearer " + key),
        'header = "Content-Type: application/json"',
        'data = ' + quote_curl('{"model":"zai-glm-5","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":8,"temperature":0,"stream":false}'),
    ]
    # Create/replace with restrictive permissions even if the caller made the file earlier.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as stream:
            stream.write("\n".join(config) + "\n")
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
