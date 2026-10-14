# v5.2.3 — restore reasoning selector and tested multimodal routing

- Restore Codex's reasoning-effort selector by advertising low/medium/high levels in the generated catalog for configured reasoning-capable models.
- Preserve each model's maximum output budget and explicit input modalities in the local proxy configuration.
- Route only image-bearing current user turns from a configured text-only model to Claude Sonnet 5.5; text-only follow-ups return to the requested model.
- Add typed metadata parsing and a dedicated Bun test file for multimodal routing; the installer runs the patch before TypeScript checks and tests.
- Preserve v5.2.2's explicit output caps, 120K auto-compaction threshold, bounded historical context guards, Zstandard support, Bedrock tool-name aliases, assistant-prefill workaround, TLS verification, and optional Ponytail integration.
