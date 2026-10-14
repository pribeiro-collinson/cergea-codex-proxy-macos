# Cergea Codex Proxy for macOS — v5.2.14

A portable installer for Codex Desktop/CLI with Cergea LiteLLM, a local Responses-to-Chat-Completions bridge, Bedrock compatibility handling, oversized-history safeguards, reasoning-effort selection, current-turn image routing to Claude Haiku, historical-image sanitization before returning to text-only models, and an optional Ponytail coding-style plugin.

## Why this package exists

Codex uses the Responses API, while Cergea's LiteLLM gateway routes to models through Amazon Bedrock. We observed that simple text requests worked while agent workflows could fail on assistant-message prefill, tool names over Bedrock's 64-character limit, compressed request bodies, catalog schema mismatches, and oversized carried-forward tool results. The local proxy translates the API and applies guarded compatibility patches. It also bounds historical tool output and assistant text/tool arguments before forwarding them, and reports request sizes without logging prompt contents.

Ponytail is an optional complementary Codex plugin that encourages simpler code and less unnecessary generation. It is **not** a context compressor and doesn't replace the proxy's history guard.

See the standalone colleague handout: [`QUICK-START.md`](QUICK-START.md).

## Install

Requirements: macOS, Git, Python 3.10+, Bun 1.3+ (1.4+ recommended), Codex Desktop/CLI, and a Cergea LiteLLM API key. The first install needs access to GitHub and the npm registry; each start checks Cergea's Chat Completions endpoint.

1. Fully quit ChatGPT/Codex Desktop.
2. Extract this ZIP to a folder such as `~/Downloads/cergea-codex-proxy-macos-v5.2.14/`. Do not extract it over an existing folder unless you intend to update that installation.
3. Run the installer from that folder, or invoke it by its full path from any working directory:

   ```bash
   ~/Downloads/cergea-codex-proxy-macos-v5.2.14/install.sh
   ```

The installer resolves paths relative to itself, so it can be launched from any working directory. Before copying, it refreshes the distribution manifest from the extracted release directory so newly added package files are not silently omitted; it never scans `~/.codex` as a source inventory. It creates a minimal `~/.codex/config.toml` if Codex has not created one yet, and preserves existing unrelated settings otherwise. The history-budget patch is also type-checked against the upstream Message union before distribution when a TypeScript compiler is available, and the actual upstream `bun run typecheck` remains a mandatory install gate. It copies every manifest-listed package file—including its own bootstrap script and manifest—into `~/.codex/`, backs up conflicting package files, runs every bundled Python regression module (including Bun-driven runtime tests), fetches the pinned upstream proxy revision, applies compatibility patches, then runs upstream TypeScript type checks and tests. It preserves unrelated `config.toml` settings and never writes the Cergea API key to disk. At the end, it asks whether to install Ponytail; the default is `n`, so third-party hooks are installed only with explicit consent. Ponytail installation requires Node.js on `PATH`; the installer discovers the Codex CLI from `PATH`, `CODEX_CLI_PATH` in `~/.codex/config.toml`, or the standard ChatGPT Desktop bundle path. The proxy itself does not require Node.js. The generated model catalog advertises low/medium/high reasoning levels for configured reasoning-capable models. GLM-5 and Mistral advertise image input so the desktop accepts pasted images. If the latest user turn contains an image, requests selected as GLM-5 or Mistral route to Claude Haiku 5.5. For text-only follow-ups, the proxy strips image parts retained from earlier user turns before forwarding to the selected text model; historical images therefore do not pin routing to Haiku or cause text-only providers to reject the request. Explicitly selected Haiku or Sonnet handle their own image requests. Because Bedrock Mixtral 8x7B does not support client-side tool calling, Mistral-selected requests that contain tool definitions route to GLM-5; image-bearing history takes priority and routes to Haiku.

For a copy-only staging run, use `./install.sh --copy-only`. It copies the bundle into `~/.codex/` and backs up conflicting files without downloading or configuring anything.

## Start

Fully quit ChatGPT/Codex Desktop, then run:

```bash
~/.codex/bin/start-cergea-codex
```

Enter your Cergea key at the prompt and keep that terminal running. Relaunch Codex Desktop and select `cergea/zai-glm-5`. To stop the proxy, press Ctrl+C in its terminal or run `~/.codex/bin/stop-cergea-codex`.

## Verify before work

Run the tests in [`docs/SMOKE-TESTS.md`](docs/SMOKE-TESTS.md) in a disposable folder and a fresh thread. A successful `OK` reply alone does not demonstrate tool calling. The installer runs synthetic tests for patcher idempotence/fail-closed behavior, new-user and existing-user config, catalog schema repair, output caps, context trimming/recency, zstd body parsing, Bedrock tool-name round trips, assistant-prefill normalization, reasoning/model catalog capabilities, current-turn image routing to Haiku, Mistral tool-capability fallback to GLM-5, and Ponytail install commands; it also runs upstream TypeScript checks/tests. The actual Cergea/Bedrock runtime still requires the smoke tests on your machine.

## Token/context reduction

Watch the proxy terminal for `[cergea-proxy request-size]` and `[cergea-proxy context-shape]`. These log counts and lengths only, not the prompt/tool payload itself. Recent diagnostics showed that the message text expanded to nearly one million characters after tool calls, while image count was zero and tool schema size stayed constant. The proxy keeps recent tool results first, bounds historical tool/assistant text and prior tool-call arguments, and marks or empties old content where necessary. This is a defensive loss of old context: if a detail is omitted, ask Codex to rerun a narrower command/read a specific range.

See [`docs/TOKEN-OPTIMIZATION.md`](docs/TOKEN-OPTIMIZATION.md), [`docs/PONYTAIL.md`](docs/PONYTAIL.md), [`docs/SMOKE-TESTS.md`](docs/SMOKE-TESTS.md), and [`docs/CHANGELOG-v5.2.14.md`](docs/CHANGELOG-v5.2.14.md). The v5.2.14 changelog is the baseline release note for this repository reset; older versioned changelogs are retained as historical records and may describe behavior superseded by this baseline.

## Security and limitations

- The proxy listens only on `127.0.0.1:18789`.
- TLS verification remains enabled; the installer builds a CA bundle from macOS trust sources and the launcher passes it to Bun via `NODE_EXTRA_CA_CERTS` and `SSL_CERT_FILE`, invoking Bun with its documented `--use-system-ca` flag. It checks the endpoint with Bun itself before starting. On a managed network whose root is not in the system keychain, ask IT for an approved PEM CA and run the installer as `CERGEA_EXTRA_CA_CERT=/absolute/path/to/company-root.pem ./install.sh`. No insecure-certificate bypasses are used.
- The key is entered at runtime and passed to the proxy via its process environment, not saved in TOML/JSON. The preflight avoids putting the bearer token in curl command-line arguments; its mode-600 temporary config is deleted after the check.
- Logs report counts/lengths, not message content, inline image URLs, tool schema JSON, or credentials.
- Ponytail is third-party code from `DietrichGebert/ponytail`. The installer prompts before installing it and defaults to no. Review and trust its lifecycle hooks from Codex's `/hooks` screen before starting a new thread.
- The current proxy compatibility patches target upstream commit `dac2f3e` and stop if expected code anchors change. Do not manually reset or pull the patched checkout to a new revision; use a separate path to test another upstream version.
- A passing synthetic test suite is not the same as verified live provider compatibility. Run the tool-calling smoke tests after installation/model changes.

## Recovery

The installer backs up changed files/configs with timestamped `.bak` suffixes. Ctrl+C or `~/.codex/bin/stop-cergea-codex` restores the proxy's managed Codex wiring. To remove Ponytail, use `codex plugin remove ponytail` and review the plugin's documented uninstall steps. See [`docs/README.md`](docs/README.md) for troubleshooting.

## Third-party software

The installer fetches `MakFly/codex-proxy` at the pinned revision and optionally installs Ponytail from its official marketplace. See [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) for notices and license text.
