# v5.2.11

- Fixed installation failure when the existing proxy source already uses the tools-aware `routeModelForMessages(parsed.model, config, parsed.messages, parsed.tools)` call. The context-budget patch now recognizes both the original route call and the multimodal/tool-aware route call, while retaining fail-closed matching and avoiding duplicate diagnostics.
- Added a regression test for installing over an already multimodal-patched proxy.
