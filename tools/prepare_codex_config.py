#!/usr/bin/env python3
"""Configure Codex to use the local proxy and retain an old provider ID for thread resume."""
from __future__ import annotations
import datetime
import pathlib
import re
import shutil
import sys

PROVIDER_BLOCK = '''[model_providers.cergea-litellm]
name = "Cergea LiteLLM (legacy thread compatibility via local proxy)"
base_url = "http://127.0.0.1:18789/v1"
wire_api = "responses"
'''

def main() -> int:
    path = pathlib.Path(sys.argv[1]).expanduser()
    config_existed = path.exists()
    if config_existed:
        original = path.read_text(encoding="utf-8")
    else:
        # Brand-new Codex installs may not have created config.toml yet. Create
        # only the settings this integration needs; the proxy CLI adds its model
        # and generated-catalog pointers when it starts. No API key is persisted.
        original = ""
    lines = original.splitlines(keepends=True)
    result: list[str] = []
    in_legacy_provider = False
    changed = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            # Remove the old provider table and any nested subtables; replace with
            # a compatibility alias pointing at the local Responses proxy.
            in_legacy_provider = stripped.startswith("[model_providers.cergea-litellm")
            if in_legacy_provider:
                changed = True
                continue
            result.append(line)
            continue
        if in_legacy_provider:
            changed = True
            continue
        # Remove only the obsolete global default-provider selection. Keep catalog
        # pointer for the proxy's generated catalog and preserve other settings.
        if re.match(r'^\s*model_provider\s*=\s*["\']cergea-litellm["\']\s*(?:#.*)?$', line):
            changed = True
            continue
        if re.match(r'^\s*model_catalog_json\s*=.*(?:model-catalogs/cergea\.json|model-catalogs\\cergea\.json).*(?:#.*)?$', line):
            changed = True
            continue
        result.append(line)

    existing_body = "".join(result).rstrip()
    if existing_body:
        updated = existing_body + "\n\n" + PROVIDER_BLOCK
    else:
        # Keep the same stable layout on first install and every subsequent run.
        updated = "model_auto_compact_token_limit = 120000 # Cergea proxy: compact before tool/history payloads grow too large\n\n" + PROVIDER_BLOCK

    # Compact early for the Cergea proxy. Its advertised Claude context window is
    # 1M tokens, but large plugin schemas, image history, or tool outputs can make
    # a single upstream request unexpectedly huge. Preserve stricter user limits;
    # lower any larger/absent limit to 120K.
    root_lines = updated.splitlines(keepends=True)
    first_table = next((i for i, item in enumerate(root_lines) if item.lstrip().startswith("[")), len(root_lines))
    root = root_lines[:first_table]
    rest = root_lines[first_table:]
    compact_re = re.compile(r"^\s*model_auto_compact_token_limit\s*=\s*(\d+)\s*(?:#.*)?$")
    compact_index = next((i for i, item in enumerate(root) if compact_re.match(item.rstrip("\r\n"))), None)
    if compact_index is None:
        root.append("model_auto_compact_token_limit = 120000 # Cergea proxy: compact before tool/history payloads grow too large\n")
    else:
        match = compact_re.match(root[compact_index].rstrip("\r\n"))
        assert match is not None
        if int(match.group(1)) > 120000:
            root[compact_index] = "model_auto_compact_token_limit = 120000 # Cergea proxy: compact before tool/history payloads grow too large\n"
    updated = "".join(root + rest)

    # Keep the reasoning selector visible by default without overriding a user's
    # explicit reasoning effort. The model catalog supplies the allowed levels.
    root_lines = updated.splitlines(keepends=True)
    first_table = next((i for i, item in enumerate(root_lines) if item.lstrip().startswith("[")), len(root_lines))
    root = root_lines[:first_table]
    rest = root_lines[first_table:]
    effort_re = re.compile(r"^\s*model_reasoning_effort\s*=\s*['\"](?:none|minimal|low|medium|high|xhigh|max)['\"]\s*(?:#.*)?$")
    if not any(effort_re.match(item.rstrip("\r\n")) for item in root):
        root.append('model_reasoning_effort = "high" # Cergea proxy default; adjust in Codex settings\n')
    root_text = "".join(root).rstrip("\r\n")
    rest_text = "".join(rest).lstrip("\r\n")
    updated = root_text + ("\n\n" + rest_text if rest_text else "\n")

    if updated == original:
        print("Codex config already points at the local proxy and retains the legacy provider alias.")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    if config_existed:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(path.name + f".pre-cergea-proxy-{stamp}.bak")
        shutil.copy2(path, backup)
        print(f"Backed up previous config to: {backup}")
    path.write_text(updated, encoding="utf-8")
    print(f"Created minimal Codex config: {path}" if not config_existed else f"Updated Codex config: {path}")
    print("Configured legacy provider ID cergea-litellm to resolve through the local proxy.")
    print("Set model_auto_compact_token_limit to at most 120000 to limit accumulated context.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
