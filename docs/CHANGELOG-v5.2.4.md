# v5.2.4 — self-maintaining distribution manifest

- Add an idempotent manifest generator that discovers new package files while excluding user state, secrets, symlinks, caches, compiled bytecode, and archive artifacts.
- Refresh the manifest automatically from the extracted release directory before installing; never scan `~/.codex` when it is the install source.
- Pass the original distribution directory into installer regression tests, so the manifest test does not treat unrelated files in the user's shared Codex home as package contents.
- Preserve the existing non-resetting install behavior, user configuration, sessions, project state, and optional Ponytail integration.
