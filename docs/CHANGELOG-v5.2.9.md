# v5.2.9 — Mistral tool-call compatibility

- Fixes the Bedrock `UnsupportedParamsError` for Mistral Mixtral 8x7B requests that include `tools` and `tool_choice`. AWS does not list client-side tool calling as supported for this model, so the proxy routes tool-bearing Mistral requests to configured tool-capable GLM-5 instead of dropping tools or failing. Codex generally attaches tool definitions even to ordinary prompts, so Mistral selection will usually route to GLM-5 during Codex sessions.
- Keeps image routing separate and higher priority: a latest user turn containing an image from GLM or Mistral routes to Claude Haiku 5.5. Text-only follow-ups return to the originally selected model even when Codex retains an earlier image in submitted history.
- Adds typed `supportsToolCalling` and provider-level `toolFallbackModel` settings, plus regression tests for tool-routing and image-routing precedence.
- Upgrade is non-resetting; no session/project deletion is performed.

- Fixes sticky vision routing: image detection now examines the latest user turn, not any prior turn in the submitted conversation history.
