# v5.1.7

- Fixed request-size diagnostics installation when the upstream server's API-key check does not match the former two-line literal anchor.
- Scope request-size logging specifically to the main `POST /v1/responses` handler; the separate `/v1/responses/compact` handler has its own `routeModel` call and must not be mistaken for the target.
- Treat an existing request-size logging call as installed even if an earlier release uses a different output-cap argument, preventing duplicate calls on upgrades.
- Added regression coverage for the upstream compact route, changed conditional layout, partial installs, and repeated installation.
