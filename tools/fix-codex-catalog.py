#!/usr/bin/env python3
"""Keep codex-proxy's catalog compatible with the bundled Codex schema.

Codex 0.162.x requires several ModelInfo keys without serde defaults. Repair
both the proxy's catalog generator and an already-generated catalog so startup
does not fail on the next missing field. A backup is kept before JSON changes.
"""
from __future__ import annotations
import json
import os
import pathlib
import shutil

home = pathlib.Path.home()
proxy_dir = pathlib.Path(os.environ.get("CERGEA_CODEX_PROXY_DIR", home / ".local/share/cergea-codex-proxy")).expanduser()
proxy_home = pathlib.Path(os.environ.get("CODEX_PROXY_HOME", home / ".codex-cergea-proxy")).expanduser()
source = proxy_dir / "src/catalog.ts"
catalog = proxy_home / "catalog.json"

if not source.is_file():
    raise SystemExit(f"Proxy source not found: {source}\nRun the installer first.")
text = source.read_text(encoding="utf-8")
original_text = text

# Apply each field independently, making the tool safe to rerun after an
# earlier partial repair. Keep the exact existing upstream source anchors.
generator_fields = [
    (
        "    truncation_policy:",
        '    max_context_window: model.contextWindow ?? 128000,\n',
        '    truncation_policy: { mode: "tokens", limit: 10000 },\n',
        "truncation_policy",
    ),
    (
        "    default_verbosity:",
        '    default_reasoning_summary: "none",\n',
        '    default_verbosity: null,\n',
        "default_verbosity",
    ),
    (
        "    experimental_supported_tools:",
        '    default_verbosity: null,\n',
        '    experimental_supported_tools: [],\n',
        "experimental_supported_tools",
    ),
]
for marker, anchor, addition, field in generator_fields:
    if marker in text:
        continue
    if text.count(anchor) != 1:
        raise SystemExit(
            f"Could not safely add {field} to catalog generator: expected one anchor, "
            f"found {text.count(anchor)}. Source was left unchanged."
        )
    text = text.replace(anchor, anchor + addition, 1)

if text != original_text:
    source.write_text(text, encoding="utf-8")
    print(f"Updated Codex catalog generator: {source}")
else:
    print(f"Codex catalog generator already has compatibility fields: {source}")

# Required ModelInfo fields in the current Codex desktop/CLI schema. Values
# already supplied by the proxy are preserved; these defaults only fill gaps.
defaults_for_index = lambda index: {
    "description": "",
    "default_reasoning_level": "none",
    "supported_reasoning_levels": [],
    "shell_type": "shell_command",
    "visibility": "list",
    "supported_in_api": True,
    "priority": index + 1,
    "availability_nux": None,
    "upgrade": None,
    "support_verbosity": False,
    "default_verbosity": None,
    "apply_patch_tool_type": "freeform",
    "truncation_policy": {"mode": "tokens", "limit": 10000},
    "experimental_supported_tools": [],
}

if catalog.is_file():
    raw = catalog.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise SystemExit(f"Unexpected catalog structure in {catalog}; left it unchanged.")
    changed = 0
    for index, model in enumerate(data["models"]):
        if not isinstance(model, dict):
            raise SystemExit(f"Unexpected model entry at models[{index}] in {catalog}; left it unchanged.")
        if not model.get("slug") or not model.get("display_name"):
            raise SystemExit(f"Model entry at models[{index}] lacks slug/display_name; left catalog unchanged.")
        for key, value in defaults_for_index(index).items():
            if key not in model:
                model[key] = value
                changed += 1
    if changed:
        backup = catalog.with_suffix(".json.before-schema-repair.bak")
        if not backup.exists():
            shutil.copy2(catalog, backup)
        catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Repaired {changed} missing Codex schema field(s) in catalog: {catalog}")
        print(f"Original catalog backup: {backup}")
    else:
        print(f"Catalog schema fields are present: {catalog}")
else:
    print(f"No generated catalog yet; generator is fixed for the next start: {catalog}")
