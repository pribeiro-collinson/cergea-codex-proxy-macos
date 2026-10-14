# v5.1.5

- Fixed the history-budget injection to type-check against the upstream `Message` discriminated union under `noUncheckedIndexedAccess`.
- Guarded indexed message/content/tool-call reads and explicitly reconstructed tool/assistant variants to preserve required fields.
- Added a TypeScript regression test using the upstream message/type shapes; runs when `tsc` is available, in addition to the mandatory live upstream typecheck performed by the installer.
- Existing installations are upgraded through the same idempotent history-budget patcher; no manual patching is required.
