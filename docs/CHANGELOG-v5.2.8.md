# v5.2.8 — route retained image history to Haiku for GLM and Mistral

- Route to Claude Haiku 5.5 whenever the submitted conversation history contains an image and the selected model is configured for image fallback. This keeps text-only follow-up turns from sending retained image parts back to GLM or Mistral.
- Advertise image input for Mistral in the generated catalog so the desktop client accepts image paste, then route image-bearing history to Haiku.
- Add regression tests for GLM and Mistral image turns, follow-ups that retain the earlier image, and selected-model routing when no image remains in submitted history.
- Upgrade patcher replaces older marked routing helpers in place; no Codex reset or session deletion is required.

See also [v5.2.9](CHANGELOG-v5.2.9.md) for Mistral tool-calling compatibility.
