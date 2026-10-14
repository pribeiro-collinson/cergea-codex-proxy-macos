# Cergea Codex Proxy — Quick Start (macOS)

Why this package: Codex uses the Responses API, while the Cergea LiteLLM route used by these models exposes Chat Completions through Bedrock. The local proxy translates between them and applies compatibility guards for tool calls, request compression, model-catalog fields, context growth, and TLS trust.

## First-time setup

1. Install **Git**, **Python 3.10+**, **Bun 1.3+**, and ChatGPT/Codex Desktop. Make sure you can reach GitHub and the npm registry.
2. Download and extract this ZIP to a folder in Downloads (do not extract it over `~/.codex`).
3. Quit ChatGPT/Codex Desktop completely.
4. Run the installer by its full path, from any working directory. For example:

   ```bash
   ~/Downloads/cergea-codex-proxy-macos-v5.2.14/install.sh
   ```

   It installs the pinned proxy, runs Python regression tests plus Bun type checks/tests, and creates a minimal Codex config if none exists. Ponytail is optional; the default is **No**.
5. Start the proxy:

   ```bash
   ~/.codex/bin/start-cergea-codex
   ```

   Enter your Cergea LiteLLM API key when prompted. Keep this terminal open.
6. Reopen ChatGPT and select `cergea/zai-glm-5` or `cergea/mistral-mixtral-8x7b-instruct`. The reasoning selector should offer low/medium/high for GLM-5. Both models accept pasted images in the client. Image-bearing latest user turns route to Claude Haiku 5.5; on text-only follow-ups, images retained from earlier turns are stripped before forwarding to the selected text model. Bedrock Mixtral 8x7B does not support client-side tool calling, so Mistral-selected requests with tools are automatically routed to GLM-5; image-bearing history takes priority and routes to Haiku. Run the smoke tests in `docs/SMOKE-TESTS.md` in a fresh conversation before using it for real work.

## If your company intercepts TLS

Ask IT for the approved root CA in PEM format, then run the installer with `CERGEA_EXTRA_CA_CERT=/absolute/path/to/company-root.pem`. Certificate verification remains enabled; do not set `NODE_TLS_REJECT_UNAUTHORIZED=0`.

## Stop

Press Ctrl+C in the proxy terminal or run `~/.codex/bin/stop-cergea-codex`.
