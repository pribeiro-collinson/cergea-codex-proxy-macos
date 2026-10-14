# v5 changelog

- Added a clean bootstrap installer for new and existing users; it backs up conflicting bundle files, copies only the package's known directories, and leaves unrelated `config.toml` settings intact.
- Pinned the upstream proxy base to the tested `dac2f3e` revision; installer refuses to modify a non-matching existing checkout instead of silently applying patches to moving upstream code.
- Added synthetic regression tests for patch idempotency, fail-closed behavior, prior output-cap migration, catalog schema repair, preservation of proxy/Codex configuration, no credential persistence, and Ponytail CLI invocation/idempotency.
- Added Bun-run synthetic behavior tests for output-token caps and the actual injected history guard, including huge tool output, valid-JSON tool-call placeholders, preservation of user messages, privacy-safe diagnostics, and explicit compaction bypass.
- Fixed the history guard to upgrade previously injected blocks and keep omission text within the aggregate tool-history budget. Also bounds oversized assistant tool-call arguments.
- Added opt-in Ponytail plugin installation and explicit documentation that it reduces unnecessary code generation rather than compressing existing history.
- Removed accidental Python bytecode/cache files from the distribution.

- Added a second synthetic test module that executes the actual injected TypeScript under Bun for long tool-name alias round trips, assistant-prefill handling, zstd JSON decoding, history recency, system/user preservation, and image preservation.
- Expanded clean-install tests for a new user's proxy config, restrictive config file permissions, corrupt JSON fail-closed behavior, and no key persistence.
- Installer now discovers/runs every `tests/test_*.py` module instead of only the initial test file.
- Ponytail helper now gives a clear error if Node.js is missing, since its Codex lifecycle hooks need `node` on PATH.
