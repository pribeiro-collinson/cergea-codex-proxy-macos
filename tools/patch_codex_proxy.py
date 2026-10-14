#!/usr/bin/env python3
"""Patch MakFly/codex-proxy's OpenAI Chat adapter for Cergea/Bedrock quirks.

The patch is deliberately fail-closed: if upstream code has changed enough that
our exact anchors no longer match, it exits rather than silently changing logic.
"""
from __future__ import annotations
import pathlib
import sys

MARKER = "// CERGEA BEDROCK COMPATIBILITY PATCH"

REPLACEMENTS = [
    (
        'import { id } from "../ids.ts";\n',
        'import { id } from "../ids.ts";\nimport { createHash } from "node:crypto";\n',
        1,
        "crypto import",
    ),
    (
        'function assistantArgs(call: ToolCall): string {\n  return call.kind === "custom" ? JSON.stringify({ input: call.arguments }) : call.arguments;\n}\n',
        '''function assistantArgs(call: ToolCall): string {
  return call.kind === "custom" ? JSON.stringify({ input: call.arguments }) : call.arguments;
}

// CERGEA BEDROCK COMPATIBILITY PATCH
// Bedrock toolUse.name is limited to 64 characters. Keep a reversible, stable
// alias for long Codex tool names in both tool definitions and conversation history.
const cergeaOriginalNameByAlias = new Map<string, string>();
function upstreamToolName(name: string): string {
  if (name.length <= 64) return name;
  const alias = `cpx_${createHash("sha256").update(name).digest("hex").slice(0, 40)}`;
  cergeaOriginalNameByAlias.set(alias, name);
  return alias;
}
function codexToolName(name: string): string {
  return cergeaOriginalNameByAlias.get(name) ?? name;
}
''',
        1,
        "tool-name alias helpers",
    ),
    (
        'function: { name: call.name, arguments: assistantArgs(call) },',
        'function: { name: upstreamToolName(call.name), arguments: assistantArgs(call) },',
        1,
        "historical assistant tool-call names",
    ),
    (
        '...(message.name ? { name: message.name } : {}),',
        '...(message.name ? { name: upstreamToolName(message.name) } : {}),',
        1,
        "tool-message names",
    ),
    (
        'name: tool.name,',
        'name: upstreamToolName(tool.name),',
        2,
        "tool-definition names (function and custom tools)",
    ),
    (
        'function: { name: parsed.toolChoice.name }',
        'function: { name: upstreamToolName(parsed.toolChoice.name) }',
        1,
        "forced tool choice name",
    ),
    (
        'state = { id: call.id || id("call"), name: call.function?.name ?? "", arguments: "", started: false };',
        'state = { id: call.id || id("call"), name: codexToolName(call.function?.name ?? ""), arguments: "", started: false };',
        1,
        "tool-name restoration on streamed response start",
    ),
    (
        'if (call.function?.name) state.name = call.function.name;',
        'if (call.function?.name) state.name = codexToolName(call.function.name);',
        1,
        "tool-name restoration on streamed name updates",
    ),
    (
        '  const body: Record<string, unknown> = {\n    model,',
        '''  // Newer Bedrock-backed Claude models reject an assistant prefill as the
  // final message. Only add a continuation user turn for a trailing plain
  // assistant message; do not fabricate results for pending tool calls.
  const lastMessage = messages[messages.length - 1];
  if (
    lastMessage?.role === "assistant" &&
    (!Array.isArray(lastMessage.tool_calls) || lastMessage.tool_calls.length === 0)
  ) {
    messages.push({ role: "user", content: "Continue from the last assistant message." });
  }

  const body: Record<string, unknown> = {
    model,''',
        1,
        "trailing assistant-prefill normalization",
    ),
]


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {pathlib.Path(sys.argv[0]).name} PATH_TO/openai-chat.ts", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    if not path.is_file():
        print(f"ERROR: adapter source not found: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"Already patched: {path}")
        return 0
    for old, new, expected_count, label in REPLACEMENTS:
        actual = text.count(old)
        if actual != expected_count:
            print(
                f"ERROR: expected {expected_count} match(es) for {label}, found {actual}. "
                "The upstream source may have changed; no patch was written.",
                file=sys.stderr,
            )
            return 1
    patched = text
    for old, new, _, _ in REPLACEMENTS:
        patched = patched.replace(old, new)
    path.write_text(patched, encoding="utf-8")
    print(f"Patched Bedrock compatibility handling in {path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
