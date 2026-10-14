# v5.2.10 — Return to selected model after image turns

- Fixes sticky vision routing: image detection examines only the latest user turn, not any prior turn in the submitted conversation history.
- Prompts whose latest user turn contains an image are still routed from GLM-5 or Mistral to Claude Haiku 5.5.
- Text-only follow-ups return to the originally selected model, even when Codex resubmits the earlier image in conversation history.
- Preserves Mistral tool-call compatibility routing and gives current-turn image routing priority when the latest user turn contains an image.
