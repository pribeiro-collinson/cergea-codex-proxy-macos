# v5.2.5 — scoped ProviderConfig patch anchor

- Fix the image-routing patcher to add `visionFallbackModel` inside `ProviderConfig` only. The upstream types file also declares `defaultModel` on `ProxyConfig`, so a file-wide anchor incorrectly matched twice and stopped installation.
- Extend the regression fixture to match upstream's duplicate `defaultModel` field shape and assert the vision fallback field is present exactly once, in the correct type.
- Retain the self-updating distribution manifest and the non-resetting installation behavior from v5.2.4.
