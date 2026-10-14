# Initial repository release — v5.2.14

This repository history is intentionally being restarted from the tested v5.2.14 distribution. Earlier development commits are not part of the new Git history; older versioned changelog files are retained only as historical documentation and do not override the behavior documented in the root README and current troubleshooting guide.

## Baseline behavior

- Codex Responses API to Cergea LiteLLM Chat Completions proxy, with guarded upstream compatibility patches.
- GLM-5 and Mistral image requests route to Claude Haiku 5.5 when the latest user turn contains an image.
- On text-only follow-ups, image parts carried forward from older turns are stripped before forwarding to text-only models.
- Mistral requests with tool definitions route to GLM-5; current-turn image routing takes precedence.
- Context/history budgets, output caps, request-size diagnostics, TLS verification, catalog repair, and optional Ponytail integration are retained.

## Release integrity

The ZIP distribution is the baseline source of truth for this reset. Before publishing, run `python3 tools/update_distribution_manifest.py --check`, the bundled Python regression tests, and the installer's upstream Bun typecheck/test gates. Then perform the live smoke tests in `docs/SMOKE-TESTS.md`. Synthetic tests alone do not prove live Cergea/Bedrock compatibility.
