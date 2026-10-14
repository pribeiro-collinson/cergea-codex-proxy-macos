# v5.2.7 — accept GLM image paste and route vision requests to Haiku

- Advertise image input capability for GLM-5 so ChatGPT/Codex allows pasted images to reach the proxy.
- Add explicit per-model `routeImagesToFallback` metadata; GLM image-bearing current turns are routed to Claude Haiku 5.5 even though the client catalog advertises image support.
- Change the provider vision fallback from Claude Sonnet 5.5 to Claude Haiku 5.5.
- Preserve direct image handling when Haiku or Sonnet is selected explicitly, and return text-only follow-up turns to the originally selected model.
- Add regression coverage for advertised GLM modalities, forced fallback routing, direct Haiku selection, and Mistral fallback routing.
