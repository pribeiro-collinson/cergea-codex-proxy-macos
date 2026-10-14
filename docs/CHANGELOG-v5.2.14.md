# v5.2.14

- Fixes text-only follow-ups after image turns: before forwarding to GLM-5 or Mixtral, the proxy removes image parts retained from older user turns when the latest user turn contains no image.
- Preserves images in the active user turn so image-bearing requests continue to route to Haiku.
- Adds a diagnostic count for historical images stripped from text-model requests.
- No API keys or prompt contents are logged.
