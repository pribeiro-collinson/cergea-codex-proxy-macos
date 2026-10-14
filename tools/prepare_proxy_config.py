#!/usr/bin/env python3
"""Create or update the per-user Cergea provider in the local proxy config.

Never writes API-key material. It references CERGEA_LITELLM_API_KEY by name.
Other configured providers and unrelated config keys are preserved.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import shutil
import sys

PROVIDER = {
    "adapter": "openai-chat",
    "baseUrl": "https://litellm.platform.com-eng.cergea.com/v1",
    "apiKeyEnv": "CERGEA_LITELLM_API_KEY",
    "visionFallbackModel": "claude-haiku-5-5",
    "toolFallbackModel": "zai-glm-5",
    "models": [
        {
            "id": "claude-haiku-5-5",
            "displayName": "Cergea · Claude Haiku 5.5",
            "contextWindow": 1_000_000,
            "maxOutputTokens": 16_384,
            "reasoning": True,
            "reasoningLevels": ["low", "medium", "high"],
            "defaultReasoningLevel": "high",
            "inputModalities": ["text", "image"],
        },
        {
            "id": "claude-sonnet-5-5",
            "displayName": "Cergea · Claude Sonnet 5.5",
            "contextWindow": 1_000_000,
            "maxOutputTokens": 16_384,
            "reasoning": True,
            "reasoningLevels": ["low", "medium", "high"],
            "defaultReasoningLevel": "high",
            "inputModalities": ["text", "image"],
        },
        {
            "id": "mistral-mixtral-8x7b-instruct",
            "displayName": "Cergea · Mistral Mixtral 8x7B Instruct",
            "contextWindow": 32_000,
            "maxOutputTokens": 4_096,
            "reasoning": False,
            "reasoningLevels": [],
            "defaultReasoningLevel": "none",
            # Client must allow image paste; proxy redirects image-bearing history to Haiku.
            "inputModalities": ["text", "image"],
            "routeImagesToFallback": True,
            # Bedrock Mixtral 8x7B has no client-side tool-calling capability.
            # Requests with tools are rerouted to GLM-5 rather than stripping tool parameters.
            "supportsToolCalling": False,
        },
        {
            "id": "zai-glm-5",
            "displayName": "Cergea · GLM-5",
            "contextWindow": 200_000,
            "maxOutputTokens": 16_384,
            "reasoning": True,
            "reasoningLevels": ["low", "medium", "high"],
            "defaultReasoningLevel": "high",
            # Codex must allow image paste for this model; proxy redirects image turns to Haiku.
            "inputModalities": ["text", "image"],
            "routeImagesToFallback": True,
        },
    ],
}


def main() -> int:
    home = pathlib.Path(os.environ.get("CODEX_PROXY_HOME", pathlib.Path.home() / ".codex-cergea-proxy")).expanduser()
    path = home / "config.json"
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)

    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"ERROR: existing proxy config is not valid JSON ({path}): {exc}", file=sys.stderr)
            print("No changes were made. Back up and fix that file, then rerun the installer.", file=sys.stderr)
            return 1
        if not isinstance(config, dict):
            print(f"ERROR: expected a JSON object in {path}; no changes were made.", file=sys.stderr)
            return 1
    else:
        config = {}

    original = json.dumps(config, ensure_ascii=False, indent=2) + "\n" if path.exists() else None
    config.setdefault("listen", "127.0.0.1:18789")
    # Keep this service private to the local machine even if an older config used another host.
    config["listen"] = "127.0.0.1:18789"
    providers = config.get("providers")
    if providers is None:
        providers = {}
        config["providers"] = providers
    if not isinstance(providers, dict):
        print(f"ERROR: `providers` must be an object in {path}; no changes were made.", file=sys.stderr)
        return 1

    existing = providers.get("cergea", {})
    if not isinstance(existing, dict):
        print(f"ERROR: `providers.cergea` must be an object in {path}; no changes were made.", file=sys.stderr)
        return 1
    # Preserve provider headers and other advanced settings, but keep the endpoint,
    # API-key environment variable, and currently advertised models in sync.
    merged = {key: value for key, value in existing.items() if key != "apiKey"}
    merged.update(PROVIDER)
    providers["cergea"] = merged
    config["defaultProvider"] = "cergea"
    config["defaultModel"] = "cergea/zai-glm-5"

    rendered = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    if rendered == original:
        print(f"Proxy config already current: {path}")
        return 0
    if path.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"config.json.pre-cergea-distribution-{stamp}.bak")
        shutil.copy2(path, backup)
        print(f"Backed up previous proxy config: {backup}")
    path.write_text(rendered, encoding="utf-8")
    os.chmod(path, 0o600)
    print(f"Configured Cergea through Chat Completions: {path}")
    print("API key is read from CERGEA_LITELLM_API_KEY; no key was written to disk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
