# v5.2.6 — image-content type guard and upgrade migration

- Fix current-turn image routing for upstream `Message.content` values typed as `string | ContentPart[]` by checking that the value is an array before inspecting image parts.
- Migrate the broken routing helper installed by v5.2.5 when upgrading an existing proxy checkout; the patch remains idempotent and validates its expected source anchors.
- Add TypeScript regression coverage for string-or-array message content and a migration test for the previously installed helper.
- Preserve the manifest updater and all existing non-resetting install behavior.
