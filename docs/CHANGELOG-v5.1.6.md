# v5.1.6

- Fixed the history-budget patcher so it wires the bounded request at the unique `runAdapter(parsed, provider, fetchFn, abort)` call instead of relying on fragile route slicing.
- Handles upstream server layouts with earlier/nested `/v1/responses` branches and `Not found` returns.
- Added a regression test reproducing the route-slicing failure, plus idempotency and adapter-call wiring assertions.
- No proxy behavior, model IDs, output caps, history budgets, or user Codex settings were otherwise changed.
