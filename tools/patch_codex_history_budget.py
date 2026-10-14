#!/usr/bin/env python3
"""Bound excessive historic tool/assistant text before forwarding to Cergea.

Keeps recent tool outputs first, preserves the head and tail of oversized
outputs, leaves user/system content and actual current Codex state untouched,
and logs per-message/tool-schema lengths only (never content or credentials).
"""
from __future__ import annotations
import pathlib
import sys

ROOT = pathlib.Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else pathlib.Path.home() / ".local/share/cergea-codex-proxy"
MARKER = "// CERGEA HISTORY BUDGET"

INJECT = r'''// CERGEA HISTORY BUDGET
// Oversized historical tool output is the observed cause of context blow-ups.
// Preserve message order/tool-call IDs, but bound text carried into each upstream request.
const CERGEA_TOOL_MESSAGE_MAX_CHARS = 12_000;
const CERGEA_TOOL_TEXT_BUDGET_CHARS = 48_000;
const CERGEA_ASSISTANT_MESSAGE_MAX_CHARS = 8_000;
const CERGEA_ASSISTANT_TEXT_BUDGET_CHARS = 24_000;
const CERGEA_TOOL_ARGUMENT_MAX_CHARS = 4_000;
const CERGEA_TOOL_ARGUMENT_BUDGET_CHARS = 12_000;

type CergeaMessage = ParsedRequest["messages"][number];
type CergeaToolMessage = Extract<CergeaMessage, { role: "tool" }>;
type CergeaAssistantMessage = Extract<CergeaMessage, { role: "assistant" }>;
type CergeaContentPart = CergeaAssistantMessage["content"][number];
type CergeaToolCall = NonNullable<CergeaAssistantMessage["toolCalls"]>[number];
function cergeaTextChars(message: CergeaMessage): number {
  if (message.role === "tool") return message.content.length;
  let chars = message.content.reduce((sum, part) => sum + (part.type === "text" ? part.text.length : part.url.length), 0);
  if (message.role === "assistant") {
    chars += (message.toolCalls ?? []).reduce((sum, call) => sum + call.name.length + call.arguments.length, 0);
  }
  return chars;
}
function cergeaTruncateText(text: string, maxChars: number, kind: string): string {
  if (text.length <= maxChars) return text;
  const omitted = text.length - maxChars;
  const marker = `\n\n[local Cergea proxy omitted ${omitted} characters of ${kind}; rerun a narrower command or read the relevant file range if more detail is needed]\n\n`;
  const room = Math.max(0, maxChars - marker.length);
  const head = Math.floor(room * 0.68);
  const tail = room - head;
  if (room <= 0) return marker.slice(0, maxChars);
  return text.slice(0, head) + marker + (tail > 0 ? text.slice(-tail) : "");
}
function cergeaMessagePreview(message: CergeaMessage, index: number): Record<string, unknown> {
  return {
    index,
    role: message.role,
    chars: cergeaTextChars(message),
    ...(message.role === "tool" ? { toolName: message.name ?? null } : {}),
    ...(message.role === "assistant" && message.toolCalls?.length ? {
      toolCalls: message.toolCalls.map((call) => ({ name: call.name, argumentChars: call.arguments.length })),
    } : {}),
  };
}
function boundCergeaHistory(parsed: ParsedRequest, modelSlug: string): ParsedRequest {
  // Never rewrite explicit context-compaction requests; they need the original context to summarize.
  if (parsed.compactionV2) return parsed;
  const originalMessages = parsed.messages;
  // A prior turn's image remains in Codex's serialized conversation even after
  // routing correctly returns to a text model. GLM/Mixtral on this gateway may
  // reject that historical image, so remove image parts from old user turns when
  // the latest user turn is text-only. Never strip an image from the active turn.
  const latestUserMessage = [...originalMessages].reverse().find((message) => message.role === "user");
  const latestUserHasImage = latestUserMessage !== undefined
    && Array.isArray(latestUserMessage.content)
    && latestUserMessage.content.some((part) => part.type === "image");
  const isTextOnlyFallbackModel = modelSlug.includes("zai-glm-5")
    || modelSlug.includes("mistral-mixtral-8x7b-instruct");
  const requestMessages: CergeaMessage[] = isTextOnlyFallbackModel && !latestUserHasImage
    ? originalMessages.map((message) => {
        if (message.role !== "user" || !Array.isArray(message.content)) return message;
        const content = message.content.filter((part) => part.type !== "image");
        return { ...message, content };
      })
    : originalMessages;
  const toolSizes = parsed.tools.map((tool) => ({
    name: tool.name,
    bytes: new TextEncoder().encode(JSON.stringify(tool)).length,
  })).sort((a, b) => b.bytes - a.bytes);
  const largestMessages = requestMessages.map((message, index) => cergeaMessagePreview(message, index))
    .sort((a, b) => Number(b.chars) - Number(a.chars)).slice(0, 8);

  // Allocate budgets newest-first so the most recent tool results survive intact when small.
  // Guard indexed reads explicitly: noUncheckedIndexedAccess is enabled by the upstream project.
  const messages: CergeaMessage[] = [...requestMessages];
  let toolRemaining = CERGEA_TOOL_TEXT_BUDGET_CHARS;
  let assistantRemaining = CERGEA_ASSISTANT_TEXT_BUDGET_CHARS;
  let toolArgumentRemaining = CERGEA_TOOL_ARGUMENT_BUDGET_CHARS;
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message === undefined) continue;
    if (message.role === "tool") {
      const toolMessage = message as CergeaToolMessage;
      const allowed = Math.min(CERGEA_TOOL_MESSAGE_MAX_CHARS, toolRemaining);
      // Keep even the omission marker inside the per-message and aggregate budgets.
      // Once the budget is exhausted, keep the tool-result slot but make its content empty.
      const content = allowed <= 0
        ? ""
        : cergeaTruncateText(toolMessage.content, allowed, "tool output");
      toolRemaining = Math.max(0, toolRemaining - content.length);
      const boundedTool: CergeaToolMessage = {
        role: "tool",
        toolCallId: toolMessage.toolCallId,
        ...(toolMessage.name !== undefined ? { name: toolMessage.name } : {}),
        content,
      };
      messages[i] = boundedTool;
      continue;
    }
    if (message.role === "assistant") {
      const assistantMessage = message as CergeaAssistantMessage;
      let remainingInMessage = Math.min(CERGEA_ASSISTANT_MESSAGE_MAX_CHARS, assistantRemaining);
      const content: CergeaContentPart[] = [...assistantMessage.content];
      for (let j = content.length - 1; j >= 0; j--) {
        const part = content[j];
        if (part === undefined || part.type !== "text") continue;
        const allowed = Math.max(0, remainingInMessage);
        if (allowed <= 0) {
          content[j] = { ...part, text: "" };
          continue;
        }
        const boundedText = cergeaTruncateText(part.text, allowed, "assistant history");
        content[j] = { ...part, text: boundedText };
        remainingInMessage = Math.max(0, remainingInMessage - boundedText.length);
        assistantRemaining = Math.max(0, assistantRemaining - boundedText.length);
      }
      // Tool-call arguments are also serialized into later requests. Bound them newest-first
      // and replace omitted content with valid JSON so tool-call history remains parseable.
      const calls: CergeaToolCall[] = [...(assistantMessage.toolCalls ?? [])];
      for (let k = calls.length - 1; k >= 0; k--) {
        const call = calls[k];
        if (call === undefined) continue;
        const allowedArgs = Math.min(CERGEA_TOOL_ARGUMENT_MAX_CHARS, toolArgumentRemaining);
        if (call.arguments.length > allowedArgs) {
          const placeholder = JSON.stringify({ _local_proxy_omitted: true, original_chars: call.arguments.length });
          const replacement = allowedArgs >= placeholder.length ? placeholder : "{}";
          calls[k] = { ...call, arguments: replacement };
          toolArgumentRemaining = Math.max(0, toolArgumentRemaining - replacement.length);
        } else {
          toolArgumentRemaining = Math.max(0, toolArgumentRemaining - call.arguments.length);
        }
      }
      const boundedAssistant: CergeaAssistantMessage = {
        role: "assistant",
        content,
        ...(assistantMessage.toolCalls !== undefined ? { toolCalls: calls } : {}),
      };
      messages[i] = boundedAssistant;
    }
  }
  const bounded: ParsedRequest = { ...parsed, messages };
  const originalChars = originalMessages.reduce((sum, message) => sum + cergeaTextChars(message), 0);
  const boundedChars = messages.reduce((sum, message) => sum + cergeaTextChars(message), 0);
  console.info("[cergea-proxy context-shape] " + JSON.stringify({
    model: modelSlug,
    originalMessageChars: originalChars,
    boundedMessageChars: boundedChars,
    truncated: originalChars > boundedChars,
    strippedHistoricalImages: originalMessages.reduce((sum, message, index) => {
      const sanitized = requestMessages[index];
      if (message.role !== "user" || sanitized?.role !== "user") return sum;
      const before = Array.isArray(message.content) ? message.content.filter((part) => part.type === "image").length : 0;
      const after = Array.isArray(sanitized.content) ? sanitized.content.filter((part) => part.type === "image").length : 0;
      return sum + Math.max(0, before - after);
    }, 0),
    largestMessages,
    toolSchemas: toolSizes,
    toolOutputBudgetChars: CERGEA_TOOL_TEXT_BUDGET_CHARS,
    assistantHistoryBudgetChars: CERGEA_ASSISTANT_TEXT_BUDGET_CHARS,
    toolArgumentBudgetChars: CERGEA_TOOL_ARGUMENT_BUDGET_CHARS,
  }));
  return bounded;
}
'''


def main() -> int:
    if len(sys.argv) > 2:
        print(f"Usage: {pathlib.Path(sys.argv[0]).name} [PATH_TO/codex-proxy]", file=sys.stderr)
        return 2
    path = ROOT / "src/server.ts"
    if not path.is_file():
        print(f"ERROR: proxy source file was not found: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    anchor = "async function runAdapter(\n"
    if text.count(anchor) != 1:
        print(f"ERROR: cannot safely patch {path}: expected one runAdapter anchor; no changes made", file=sys.stderr)
        return 1
    if MARKER in text:
        # Replace our whole previous injected block, upgrading existing installs
        # instead of leaving older budget logic in place forever.
        if text.count(MARKER) != 1:
            print(f"ERROR: found multiple history-budget markers in {path}; no changes made", file=sys.stderr)
            return 1
        start = text.index(MARKER)
        end = text.index(anchor, start)
        updated_block = INJECT + "\n"
        text = text[:start] + updated_block + text[end:]
    else:
        text = text.replace(anchor, INJECT + "\n" + anchor, 1)
    # Wire the bounded copy at the unique adapter invocation instead of slicing a
    # route by a "Not found" return. The upstream server has several nested/early
    # response branches, so route slicing can stop before the real request path.
    # The call itself proves `parsed` and `provider` are in scope.
    old_call = "runAdapter(parsed, provider, fetchFn, abort)"
    new_call = "runAdapter(upstreamParsed, provider, fetchFn, abort)"
    marker_line = "const upstreamParsed = boundCergeaHistory(parsed, provider.slug);"

    if text.count(new_call) > 1 or text.count(old_call) > 1:
        print(f"ERROR: expected at most one main adapter invocation in {path}; no changes made", file=sys.stderr)
        return 1

    if old_call in text:
        if marker_line not in text:
            call_pos = text.index(old_call)
            line_start = text.rfind("\n", 0, call_pos) + 1
            line_end = text.find("\n", call_pos)
            if line_end < 0:
                line_end = len(text)
            line = text[line_start:line_end]
            indent = line[: len(line) - len(line.lstrip())]
            if not line.strip() or old_call not in line:
                print(f"ERROR: cannot safely determine adapter-call line in {path}; no changes made", file=sys.stderr)
                return 1
            # Insert at the same indentation as the adapter invocation, even if
            # it appears after `const result = await` on that line.
            text = text[:line_start] + indent + marker_line + "\n" + text[line_start:]
        text = text.replace(old_call, new_call, 1)
    elif new_call not in text:
        print(f"ERROR: could not find the expected main adapter invocation in {path}; no changes made", file=sys.stderr)
        return 1

    if text.count(marker_line) != 1 or text.count(new_call) != 1:
        print(f"ERROR: history budget patch verification failed for {path}; no changes made", file=sys.stderr)
        return 1
    if text.index(marker_line) > text.index(new_call):
        print(f"ERROR: bounded request is declared after adapter invocation in {path}; no changes made", file=sys.stderr)
        return 1
    path.write_text(text, encoding="utf-8")
    print(f"Applied tool/assistant history budget and context diagnostics: {path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
