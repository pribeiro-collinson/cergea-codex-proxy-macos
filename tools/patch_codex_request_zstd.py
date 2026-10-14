#!/usr/bin/env python3
"""Teach the local Codex Responses proxy to decode zstd-compressed requests.

Recent Codex Desktop builds may send POST /v1/responses with
Content-Encoding: zstd. The upstream proxy's request.text() path attempts to
JSON.parse compressed bytes and returns "Request body is not valid JSON".
This patch decompresses only explicitly zstd-encoded requests before parsing.
"""
from __future__ import annotations
import pathlib
import sys

MARKER = "// CERGEA CODEX ZSTD REQUEST COMPATIBILITY"
OLD = '''async function readJson(request: Request): Promise<unknown> {
  const text = await request.text();
  if (!text.trim()) return {};
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error("Request body is not valid JSON");
  }
}
'''
NEW = '''async function readJson(request: Request): Promise<unknown> {
  const contentEncoding = request.headers.get("content-encoding")?.trim().toLowerCase();
  let text: string;

  // CERGEA CODEX ZSTD REQUEST COMPATIBILITY
  // Codex Desktop can send the Responses request as zstd-compressed bytes.
  // Request.text() does not decode Content-Encoding, so JSON.parse would fail.
  if (contentEncoding === "zstd") {
    const compressed = new Uint8Array(await request.arrayBuffer());
    try {
      const decompressed = Bun.zstdDecompressSync(compressed);
      text = new TextDecoder("utf-8", { fatal: true }).decode(decompressed);
    } catch {
      throw new Error("Could not decompress zstd-encoded request body");
    }
  } else {
    text = await request.text();
  }

  if (!text.trim()) return {};
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error("Request body is not valid JSON");
  }
}
'''

def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {pathlib.Path(sys.argv[0]).name} PATH_TO/server.ts", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    if not path.is_file():
        print(f"ERROR: proxy server source not found: {path}", file=sys.stderr)
        return 2
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print(f"Already patched: {path}")
        return 0
    if source.count(OLD) != 1:
        print(
            f"ERROR: expected exactly one readJson() anchor in {path}; found {source.count(OLD)}. "
            "No changes were written.",
            file=sys.stderr,
        )
        return 1
    path.write_text(source.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"Patched zstd request decompression: {path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
