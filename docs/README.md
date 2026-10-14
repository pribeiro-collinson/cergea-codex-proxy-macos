# Troubleshooting

## Install fails on a fresh machine

Requirements are macOS, Git, Python 3.10+, Bun 1.3+ (1.4+ recommended), ChatGPT/Codex Desktop, and a Cergea LiteLLM API key. The installer fetches a pinned proxy revision and installs its locked dependencies, so GitHub and the npm registry must be reachable. Do not continue if TypeScript checks or Bun tests fail.

## `unable to get local issuer certificate`

The launcher tests TLS using both `curl` and Bun. If the Bun test fails, the proxy will not start. On a company network with TLS inspection, ask IT for the approved CA certificate in PEM format and run:

```bash
CERGEA_EXTRA_CA_CERT=/absolute/path/to/company-root.pem \
  ~/Downloads/cergea-codex-proxy-macos-v5.2.14/install.sh
```

TLS verification is never disabled. Do not use `NODE_TLS_REJECT_UNAUTHORIZED=0`.

## Codex cannot load `config.toml` or model catalog

Check the exact missing field in the error. Re-run the installer for the bundled catalog repair. Keep `~/.codex/config.toml` as TOML and `~/.codex-cergea-proxy/catalog.json` as the proxy-generated catalog; the old `~/.codex/model-catalogs/cergea.json` is not the active catalog for this setup.

## `Request body is not valid JSON`

Ensure Codex is wired to the local proxy by starting with `~/.codex/bin/start-cergea-codex`, not by using the old direct Cergea provider. The proxy has a zstd request-body decoder; if it fails its guarded patch, do not manually edit `server.ts`—run the installer and share the exact anchor error.

## Context-window errors

Use a fresh thread for a test. Watch `[cergea-proxy request-size]` and `[cergea-proxy context-shape]` in the proxy terminal. The proxy trims carried-forward historical tool results/assistant text while preserving recent outputs; truncated old results may need to be re-read with a narrower command.

## Ponytail

Ponytail is optional. The default installer answer is no. If installed, it requires Node.js for hooks; open `/hooks`, review and trust the hooks explicitly, and start a new thread. It is a coding-style aid, not a context compressor.

## Restore or stop

Use Ctrl+C in the proxy terminal or `~/.codex/bin/stop-cergea-codex` to restore the proxy-managed Codex settings. The installer makes timestamped backups of package-owned files and the settings it changes.


## Reasoning, image and tool routing (baseline v5.2.14)

The generated model catalog advertises low/medium/high reasoning levels for configured reasoning-capable models. The selected effort is forwarded through the OpenAI-compatible Chat Completions adapter.

For GLM-5 and Mistral, an image in the **latest user turn** routes the request to Claude Haiku 5.5. On a text-only follow-up, the proxy removes image parts retained from earlier user turns before forwarding the request to the selected text model. This separates model selection from stale multimodal payloads: old images neither keep routing stuck on Haiku nor reach text-only providers. Explicitly selected Haiku or Sonnet handle their own image requests.

Bedrock Mixtral 8x7B does not support client-side tool calling, so Mistral-selected requests containing tool definitions route to GLM-5. An image in the latest user turn takes priority and routes to Haiku. Run the current smoke tests in `SMOKE-TESTS.md`; older versioned changelogs are historical and may describe behavior superseded by the v5.2.14 baseline.

The output caps, early compaction threshold, bounded history/tool-result guards, Zstandard request handling, TLS verification, and optional Ponytail integration remain enabled. Ponytail is a companion coding-style plugin, not the mechanism that trims proxy history.
