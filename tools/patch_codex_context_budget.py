#!/usr/bin/env python3
"""Add model-aware output caps and privacy-safe request-size diagnostics.

This patcher also repairs the earlier distribution's bad patch, which referenced
`provider` from inside toChatBody() where that variable is not in scope.
"""
from __future__ import annotations
import pathlib
import re
import sys

ROOT = pathlib.Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else pathlib.Path.home() / ".local/share/cergea-codex-proxy"


def read(path: pathlib.Path) -> str:
    if not path.is_file():
        raise SystemExit(f"ERROR: expected proxy source file was not found: {path}")
    return path.read_text(encoding="utf-8")


def write_if_changed(path: pathlib.Path, original: str, updated: str) -> None:
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        print(f"Patched: {path}")
    else:
        print(f"Already patched: {path}")


def ensure_field(path: pathlib.Path, marker: str, old_anchor: str, replacement: str, label: str) -> None:
    text = read(path)
    if marker in text:
        return
    count = text.count(old_anchor)
    if count != 1:
        raise SystemExit(f"ERROR: cannot safely patch {path}: expected one anchor for {label}, found {count}; no change made")
    write_if_changed(path, text, text.replace(old_anchor, replacement, 1))


def ensure_adapter(path: pathlib.Path) -> None:
    original = read(path)
    text = original

    old_sig = 'export function toChatBody(parsed: ParsedRequest, model: string): Record<string, unknown> {'
    new_sig = 'export function toChatBody(parsed: ParsedRequest, model: string, maxOutputTokens?: number): Record<string, unknown> {'
    if old_sig in text:
        if text.count(old_sig) != 1:
            raise SystemExit(f"ERROR: expected one toChatBody signature in {path}; no change made")
        text = text.replace(old_sig, new_sig, 1)
    elif new_sig not in text:
        raise SystemExit(f"ERROR: unrecognized toChatBody signature in {path}; no change made")

    # Repair the broken output-cap patch from the preceding bundle. The first
    # install inserted `provider.model...` into toChatBody(), where provider is
    # undefined. Read the model's cap as an explicit helper argument instead.
    text = text.replace(
        'const outputCap = provider.model.maxOutputTokens ?? 16384;',
        'const outputCap = maxOutputTokens ?? 16384;',
    )

    marker = '// CERGEA OUTPUT CAP'
    if marker not in text:
        old_line = '  if (parsed.maxTokens !== undefined) body.max_tokens = parsed.maxTokens;'
        cap_block = '''  // CERGEA OUTPUT CAP: never trust an upstream default that can exhaust context.
  const outputCap = maxOutputTokens ?? 16384;
  const requestedOutput = parsed.maxTokens;
  body.max_tokens = typeof requestedOutput === "number" && requestedOutput > 0
    ? Math.min(requestedOutput, outputCap)
    : outputCap;'''
        count = text.count(old_line)
        if count != 1:
            raise SystemExit(f"ERROR: expected one max_tokens anchor in {path}, found {count}; no change made")
        text = text.replace(old_line, cap_block, 1)
    else:
        # Marker exists from an older install. Ensure its code references the
        # helper parameter (migration) and fail closed if the shape is unknown.
        if 'const outputCap = maxOutputTokens ?? 16384;' not in text:
            raise SystemExit(f"ERROR: output-cap marker exists but implementation is unknown in {path}; no change made")

    old_call = 'JSON.stringify(toChatBody(parsed, provider.model.id))'
    new_call = 'JSON.stringify(toChatBody(parsed, provider.model.id, provider.model.maxOutputTokens))'
    if old_call in text:
        if text.count(old_call) != 1:
            raise SystemExit(f"ERROR: expected one toChatBody call in {path}; no change made")
        text = text.replace(old_call, new_call, 1)
    elif new_call not in text:
        raise SystemExit(f"ERROR: unrecognized toChatBody call in {path}; no change made")

    if 'provider.model.maxOutputTokens' in text and 'const outputCap = provider.model.maxOutputTokens' in text:
        raise SystemExit(f"ERROR: stale out-of-scope provider reference remains in {path}")
    write_if_changed(path, original, text)


def ensure_request_size_diagnostics(path: pathlib.Path) -> None:
    original = read(path)
    text = original
    marker = '// CERGEA REQUEST SIZE DIAGNOSTICS'
    if marker not in text:
        diagnostics = '''// CERGEA REQUEST SIZE DIAGNOSTICS
// Counts and lengths only. Never log prompt content, image URLs, schemas, or credentials.
function logRequestSize(parsed: ParsedRequest, modelSlug: string, outputCap: number): void {
  let messageTextChars = 0;
  let toolMessageCount = 0;
  let imageCount = 0;
  let inlineImageUrlChars = 0;
  const roles = { system: 0, user: 0, assistant: 0, tool: 0 };
  for (const message of parsed.messages) {
    roles[message.role] += 1;
    if (message.role === "tool") {
      toolMessageCount += 1;
      messageTextChars += message.content.length;
      continue;
    }
    for (const part of message.content) {
      if (part.type === "text") messageTextChars += part.text.length;
      else if (part.type === "image") {
        imageCount += 1;
        if (part.url.startsWith("data:")) inlineImageUrlChars += part.url.length;
      }
    }
  }
  const toolSchemaBytes = new TextEncoder().encode(JSON.stringify(parsed.tools)).length;
  console.info("[cergea-proxy request-size] " + JSON.stringify({
    model: modelSlug,
    instructionsChars: parsed.instructions?.length ?? 0,
    messages: roles,
    totalMessages: parsed.messages.length,
    messageTextChars,
    toolMessages: toolMessageCount,
    images: imageCount,
    inlineImageUrlChars,
    toolDefinitions: parsed.tools.length,
    toolSchemaBytes,
    requestedOutputTokens: parsed.maxTokens ?? null,
    appliedOutputTokenCap: outputCap,
  }));
}

'''
        anchor = 'function prepareParsed(parsed: ParsedRequest): ParsedRequest {\n'
        if text.count(anchor) != 1:
            raise SystemExit(f"ERROR: expected one prepareParsed anchor in {path}; no change made")
        text = text.replace(anchor, diagnostics + anchor, 1)

    # Scope diagnostics to the main /v1/responses route. The upstream server
    # also has /v1/responses/compact, which contains another routeModel call.
    # Do not couple this insertion to the following API-key conditional: the
    # pinned upstream uses a multi-line return-json guard, and prior versions
    # may already have inserted a log call with a different output-cap expression.
    responses_route = re.compile(
        r'''(?m)^(?P<indent>[ \t]*)if\s*\(\s*path\s*===\s*["']/v1/responses["']\s*&&\s*request\.method\s*===\s*["']POST["']\s*\)\s*\{[ \t]*$'''
    )
    route_matches = list(responses_route.finditer(text))
    if not route_matches:
        raise SystemExit(
            f"ERROR: cannot safely locate the main /v1/responses handler in {path}; no change made"
        )
    provider_anchor = re.compile(
        r"(?m)^(?P<indent>[ \t]*)(?:const|let)\s+provider\s*=\s*(?:"
        r"routeModel\(\s*parsed\.model\s*,\s*config\s*\)|"
        r"routeModelForMessages\(\s*parsed\.model\s*,\s*config\s*,\s*parsed\.messages"
        r"(?:\s*,\s*parsed\.tools)?\s*\)"
        r")\s*;?[ \t]*$"
    )
    logged_route = re.compile(r"\blogRequestSize\s*\(\s*parsed\s*,\s*provider\.slug\b")

    # Some Codex-proxy revisions/tests contain an earlier guard branch for the
    # same route that immediately returns an error. Select the handler segment
    # that actually performs provider routing, not merely the first route text.
    candidates = []
    for index, route_match in enumerate(route_matches):
        segment_end = route_matches[index + 1].start() if index + 1 < len(route_matches) else len(text)
        segment = text[route_match.end():segment_end]
        provider_matches = list(provider_anchor.finditer(segment))
        if len(provider_matches) == 1:
            candidates.append((route_match, segment_end, provider_matches[0]))
    if len(candidates) != 1:
        raise SystemExit(
            f"ERROR: cannot safely identify the provider-routed /v1/responses handler in {path}: "
            f"expected exactly one candidate, found {len(candidates)}; no change made"
        )

    route_match, segment_end, provider_match = candidates[0]
    route_tail = text[route_match.end():segment_end]
    if not logged_route.search(route_tail):
        insert_at = route_match.end() + provider_match.end()
        indent = provider_match.group("indent")
        log_line = "\n" + indent + "logRequestSize(parsed, provider.slug, provider.model.maxOutputTokens ?? 16384);"
        text = text[:insert_at] + log_line + text[insert_at:]

    # Verify this particular handler is instrumented. Existing logs from older
    # releases are accepted, even if their third argument differs; don't append
    # duplicate calls on repeated installs or migration from partial installs.
    route_matches = list(responses_route.finditer(text))
    candidates = []
    for index, route_match in enumerate(route_matches):
        segment_end = route_matches[index + 1].start() if index + 1 < len(route_matches) else len(text)
        segment = text[route_match.end():segment_end]
        provider_matches = list(provider_anchor.finditer(segment))
        if len(provider_matches) == 1:
            candidates.append((route_match, segment_end, segment))
    if len(candidates) != 1:
        raise SystemExit(f"ERROR: /v1/responses handler verification failed in {path}; no change made")
    if marker not in text or not logged_route.search(candidates[0][2]):
        raise SystemExit(f"ERROR: request-size diagnostics verification failed in {path}; no change made")

    write_if_changed(path, original, text)


def main() -> int:
    if len(sys.argv) > 2:
        print("Usage: patch_codex_context_budget.py [PATH_TO/codex-proxy]", file=sys.stderr)
        return 2

    ensure_field(
        ROOT / "src/types.ts",
        "maxOutputTokens?: number; // CERGEA OUTPUT CAP",
        "  contextWindow?: number;\n",
        "  contextWindow?: number;\n  maxOutputTokens?: number; // CERGEA OUTPUT CAP\n",
        "model output cap type",
    )
    ensure_field(
        ROOT / "src/config.ts",
        "maxOutputTokens: optionalNumber(rec.maxOutputTokens",
        '    contextWindow: optionalNumber(rec.contextWindow, `models[${index}].contextWindow`),\n',
        '    contextWindow: optionalNumber(rec.contextWindow, `models[${index}].contextWindow`),\n'
        '    maxOutputTokens: optionalNumber(rec.maxOutputTokens, `models[${index}].maxOutputTokens`),\n',
        "model output cap parsing",
    )
    ensure_adapter(ROOT / "src/adapters/openai-chat.ts")
    ensure_request_size_diagnostics(ROOT / "src/server.ts")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
