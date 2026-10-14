# Token/context optimization

## What diagnostics showed

In one video-analysis task, the user prompt was short, but the proxy logged `messageTextChars` growing from about 71K to 453K and then about 1M after tool activity. The same requests logged no inline images and a nearly constant tool-schema size. This points primarily to carried-forward tool/assistant content, not the legacy `cergea.json` prose.

## What this package does

- Caps model output tokens: 16,384 for Claude/GLM-5 and 4,096 for Mistral by default; smaller client requests stay smaller.
- Requests Codex context compaction at a maximum threshold of 120,000 tokens unless an existing stricter limit is configured.
- Bounds historical tool output to 48,000 characters total and 12,000 per result.
- Bounds historical assistant text to 24,000 characters total and 8,000 per message.
- Bounds historical assistant tool-call arguments to 12,000 characters total and 4,000 per call. When arguments are omitted, the proxy substitutes a small valid JSON object to preserve parseable history.
- Preserves message order and tool-result slots. Newer tool outputs are favored. Explicit compaction requests bypass lossy history trimming.
- Logs per-message lengths, tool-schema sizes, image counts, and original/bounded context sizes without logging prompt contents.

The guard is intentionally a bounded text-retention policy, not a semantic summarizer. It may omit historical information and use empty results for older tool messages after the aggregate budget is exhausted. If Codex needs omitted details, ask it to rerun a narrow command or inspect a relevant file range. Test real tasks after installation.

## Diagnostic guide

- `messageTextChars` near the million range but much smaller `boundedMessageChars`: carried-forward history/tool results were the major contributor; the guard should reduce what is sent upstream.
- `toolSchemaBytes` dominates: disable plugins/tools not needed for the task and compare. Ponytail will not shrink schemas.
- `images` / `inlineImageUrlChars` dominate: reduce/crop/split media; a prose skill will not solve visual payload size.
- A fresh thread succeeds but an old thread fails: accumulated history is implicated.
- The request-size line alone records pre-guard size. Check the following `context-shape` line for the post-guard size and `truncated: true`.
