#!/usr/bin/env python3
"""Add reasoning, image and tool-call compatibility routing.

Targets the pinned MakFly/codex-proxy revision used by the patch-based Cergea
release. Every source change is prepared and validated before any file is
written. Re-running is safe; an unfamiliar upstream layout fails closed.
"""
from __future__ import annotations
import pathlib
import re
import shutil
import sys

MARKER = "CERGEA MULTIMODAL ROUTING"

ROUTER_HELPER = '// CERGEA MULTIMODAL ROUTING\n// Tool compatibility: Mixtral 8x7B on Bedrock does not support client-side tool calling. Route its\n// tool-bearing requests to a configured tool-capable model; an image in the latest\n// user turn has priority and routes that turn to the configured vision model.\nexport function routeModelForMessages(\n  requested: string,\n  config: ProxyConfig,\n  messages: Message[],\n  tools: Tool[] = [],\n  env: NodeJS.ProcessEnv = process.env,\n): ResolvedProvider {\n  const selected = routeModel(requested, config, env);\n  // Codex resubmits prior turns, including old image attachments, on follow-ups.\n  // Route by the latest user turn only, so a previous image does not pin the\n  // entire conversation to Haiku after the user moves back to text.\n  const latestUserMessage = [...messages].reverse().find((message) => message.role === "user");\n  const latestContent = latestUserMessage?.content;\n  const hasImageInLatestUserTurn = Array.isArray(latestContent)\n    && latestContent.some((part) => part.type === "image");\n\n  if (hasImageInLatestUserTurn) {\n    const supportedModalities = selected.model.inputModalities;\n    const forceFallback = selected.model.routeImagesToFallback === true;\n    const requiresVisionFallback = forceFallback || (supportedModalities !== undefined && !supportedModalities.includes("image"));\n    if (requiresVisionFallback) {\n      const fallback = config.providers[selected.id]?.visionFallbackModel;\n      if (!fallback) {\n        throw new Error(\n          `Model \'${selected.slug}\' requires an image fallback for image-bearing conversation history, but provider \'${selected.id}\' has no visionFallbackModel configured`,\n        );\n      }\n      const fallbackSlug = fallback.includes("/") ? fallback : `${selected.id}/${fallback}`;\n      const visionProvider = routeModel(fallbackSlug, config, env);\n      if (!visionProvider.model.inputModalities?.includes("image")) {\n        throw new Error(\n          `Configured vision fallback \'${visionProvider.slug}\' does not advertise image input`,\n        );\n      }\n      console.info(\n        `[cergea-proxy multimodal] Routed ${selected.slug} to ${visionProvider.slug} because the latest user turn contains an image`,\n      );\n      return visionProvider;\n    }\n  }\n\n  if (tools.length > 0 && selected.model.supportsToolCalling === false) {\n    const fallback = config.providers[selected.id]?.toolFallbackModel;\n    if (!fallback) {\n      throw new Error(\n        `Model \'${selected.slug}\' does not support tool calling and provider \'${selected.id}\' has no toolFallbackModel configured`,\n      );\n    }\n    const fallbackSlug = fallback.includes("/") ? fallback : `${selected.id}/${fallback}`;\n    const toolProvider = routeModel(fallbackSlug, config, env);\n    if (toolProvider.model.supportsToolCalling === false) {\n      throw new Error(`Configured tool fallback \'${toolProvider.slug}\' also disables tool calling`);\n    }\n    console.info(\n      `[cergea-proxy tool-compat] Routed ${selected.slug} to ${toolProvider.slug} because the selected model does not support tool calling`,\n    );\n    return toolProvider;\n  }\n\n  return selected;\n}'

TEST_SOURCE = 'import { describe, expect, test } from "bun:test";\nimport { parseConfig } from "../src/config.ts";\nimport { routeModelForMessages } from "../src/router.ts";\nimport type { Message, Tool } from "../src/types.ts";\n\nfunction config() {\n  return parseConfig({\n    listen: "127.0.0.1:18789",\n    defaultProvider: "cergea",\n    defaultModel: "cergea/zai-glm-5",\n    providers: {\n      cergea: {\n        adapter: "openai-chat",\n        baseUrl: "https://example.invalid/v1",\n        apiKeyEnv: "CERGEA_LITELLM_API_KEY",\n        visionFallbackModel: "claude-haiku-5-5",\n        toolFallbackModel: "zai-glm-5",\n        models: [\n          {\n            id: "zai-glm-5",\n            contextWindow: 200000,\n            maxOutputTokens: 16384,\n            reasoning: true,\n            reasoningLevels: ["low", "medium", "high"],\n            defaultReasoningLevel: "high",\n            inputModalities: ["text", "image"],\n            routeImagesToFallback: true,\n          },\n          {\n            id: "claude-haiku-5-5",\n            contextWindow: 1000000,\n            maxOutputTokens: 16384,\n            reasoning: true,\n            reasoningLevels: ["low", "medium", "high"],\n            defaultReasoningLevel: "high",\n            inputModalities: ["text", "image"],\n          },\n          {\n            id: "claude-sonnet-5-5",\n            contextWindow: 1000000,\n            maxOutputTokens: 16384,\n            reasoning: true,\n            reasoningLevels: ["low", "medium", "high"],\n            defaultReasoningLevel: "high",\n            inputModalities: ["text", "image"],\n          },\n          {\n            id: "mistral-mixtral-8x7b-instruct",\n            contextWindow: 32000,\n            maxOutputTokens: 4096,\n            reasoning: false,\n            reasoningLevels: [],\n            defaultReasoningLevel: "none",\n            inputModalities: ["text", "image"],\n            routeImagesToFallback: true,\n            supportsToolCalling: false,\n          },\n        ],\n      },\n    },\n  });\n}\n\nconst imageMessage: Message = {\n  role: "user",\n  content: [\n    { type: "text", text: "Analyze this image" },\n    { type: "image", url: "data:image/png;base64,synthetic-test" },\n  ],\n};\nconst textMessage: Message = { role: "user", content: [{ type: "text", text: "Follow up in text" }] };\n\ndescribe("Cergea multimodal routing", () => {\n  test("advertises GLM image input but routes image turns to Haiku", () => {\n    const cfg = config();\n    const glm = cfg.providers.cergea?.models.find((model) => model.id === "zai-glm-5");\n    expect(glm?.inputModalities).toEqual(["text", "image"]);\n    expect(glm?.routeImagesToFallback).toBe(true);\n    const result = routeModelForMessages("cergea/zai-glm-5", cfg, [imageMessage]);\n    expect(result.slug).toBe("cergea/claude-haiku-5-5");\n  });\n\n  test("does not reroute when Haiku is selected directly", () => {\n    const result = routeModelForMessages("cergea/claude-haiku-5-5", config(), [imageMessage]);\n    expect(result.slug).toBe("cergea/claude-haiku-5-5");\n  });\n\n  test("returns text-only follow-ups to GLM even when an earlier image remains in history", () => {\n    const result = routeModelForMessages("cergea/zai-glm-5", config(), [\n      imageMessage,\n      { role: "assistant", content: [{ type: "text", text: "Image analyzed" }] },\n      textMessage,\n    ]);\n    expect(result.slug).toBe("cergea/zai-glm-5");\n  });\n\n  test("does not reroute a vision-capable model", () => {\n    const result = routeModelForMessages("cergea/claude-sonnet-5-5", config(), [imageMessage]);\n    expect(result.slug).toBe("cergea/claude-sonnet-5-5");\n  });\n\n  test("advertises Mistral image paste and routes image turns to Haiku", () => {\n    const cfg = config();\n    const mistral = cfg.providers.cergea?.models.find((model) => model.id === "mistral-mixtral-8x7b-instruct");\n    expect(mistral?.inputModalities).toEqual(["text", "image"]);\n    expect(mistral?.routeImagesToFallback).toBe(true);\n    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", cfg, [imageMessage]);\n    expect(result.slug).toBe("cergea/claude-haiku-5-5");\n  });\n\n  test("returns text-only Mistral follow-ups to Mistral when an earlier image remains in history", () => {\n    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", config(), [\n      imageMessage,\n      { role: "assistant", content: [{ type: "text", text: "Image analyzed" }] },\n      textMessage,\n    ]);\n    expect(result.slug).toBe("cergea/mistral-mixtral-8x7b-instruct");\n  });\n\n  test("returns to the selected text model when submitted history contains no image", () => {\n    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", config(), [textMessage]);\n    expect(result.slug).toBe("cergea/mistral-mixtral-8x7b-instruct");\n  });\n\n  test("routes tool-bearing Mistral requests to GLM instead of sending unsupported Bedrock parameters", () => {\n    const tool: Tool = { type: "function", name: "exec", description: "Run a command", parameters: {} };\n    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", config(), [textMessage], [tool]);\n    expect(result.slug).toBe("cergea/zai-glm-5");\n  });\n\n  test("image routing takes precedence over tool fallback for Mistral", () => {\n    const tool: Tool = { type: "function", name: "exec", description: "Run a command", parameters: {} };\n    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", config(), [imageMessage], [tool]);\n    expect(result.slug).toBe("cergea/claude-haiku-5-5");\n  });\n\n  test("does not reroute tool-capable GLM requests", () => {\n    const tool: Tool = { type: "function", name: "exec", description: "Run a command", parameters: {} };\n    const result = routeModelForMessages("cergea/zai-glm-5", config(), [textMessage], [tool]);\n    expect(result.slug).toBe("cergea/zai-glm-5");\n  });\n\n  test("fails clearly if forced image routing has no configured fallback", () => {\n    const value = config();\n    const provider = value.providers.cergea;\n    if (!provider) throw new Error("test fixture provider missing");\n    delete provider.visionFallbackModel;\n    expect(() => routeModelForMessages("cergea/zai-glm-5", value, [imageMessage])).toThrow(\n      "has no visionFallbackModel configured",\n    );\n  });\n});\n'
def require_anchor(text: str, anchor: str, label: str) -> None:
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")


def insert_after_field(text: str, marker: str, anchor: str, addition: str, label: str) -> str:
    if marker in text:
        return text
    require_anchor(text, anchor, label)
    return text.replace(anchor, anchor + addition, 1)


def prepare_proxy_types(proxy_dir: pathlib.Path, updated: dict[pathlib.Path, str]) -> None:
    types_path = proxy_dir / "src/types.ts"
    text = types_path.read_text(encoding="utf-8")
    if "inputModalities?: Array<\"text\" | \"image\">;" not in text:
        anchor = "  reasoningLevels?: ReasoningEffort[];\n"
        text = insert_after_field(
            text,
            'inputModalities?: Array<"text" | "image">;',
            anchor,
            '  defaultReasoningLevel?: ReasoningEffort;\n  inputModalities?: Array<"text" | "image">;\n',
            "ModelConfig reasoning/modality fields",
        )
    elif "defaultReasoningLevel?: ReasoningEffort;" not in text:
        text = insert_after_field(
            text, "defaultReasoningLevel?: ReasoningEffort;",
            "  reasoningLevels?: ReasoningEffort[];\n",
            "  defaultReasoningLevel?: ReasoningEffort;\n",
            "ModelConfig default reasoning field",
        )
    # defaultModel also exists on ProxyConfig, so a file-wide replacement is
    # ambiguous on the pinned upstream revision. Scope the insertion to the
    # ProviderConfig declaration and validate only that block.
    provider_pattern = re.compile(
        r"(?ms)^export type ProviderConfig = \{(?P<body>.*?)^\};"
    )
    provider_matches = list(provider_pattern.finditer(text))
    if len(provider_matches) != 1:
        raise RuntimeError(
            "ProviderConfig declaration: expected exactly one exported type block, "
            f"found {len(provider_matches)}"
        )
    provider_match = provider_matches[0]
    provider_block = provider_match.group(0)
    if "visionFallbackModel?: string;" not in provider_block:
        provider_anchor = "  defaultModel?: string;\n"
        require_anchor(provider_block, provider_anchor, "ProviderConfig defaultModel field")
        patched_provider = provider_block.replace(
            provider_anchor,
            provider_anchor + "  visionFallbackModel?: string; // image routing fallback model id or slug\n",
            1,
        )
        text = text[:provider_match.start()] + patched_provider + text[provider_match.end():]
    if "routeImagesToFallback?: boolean;" not in text:
        modalities_anchor = '  inputModalities?: Array<"text" | "image">;\n'
        require_anchor(text, modalities_anchor, "ModelConfig inputModalities field")
        text = text.replace(
            modalities_anchor,
            modalities_anchor + "  routeImagesToFallback?: boolean; // route image turns to the configured fallback\n",
            1,
        )
    if "supportsToolCalling?: boolean;" not in text:
        anchor = "  routeImagesToFallback?: boolean; // route image turns to the configured fallback\n"
        require_anchor(text, anchor, "ModelConfig routeImagesToFallback field")
        text = text.replace(anchor, anchor + "  supportsToolCalling?: boolean; // whether the provider model supports tools\n", 1)

    provider_pattern = re.compile(r"(?ms)^export type ProviderConfig = \{(?P<body>.*?)^\};")
    provider_matches = list(provider_pattern.finditer(text))
    if len(provider_matches) != 1:
        raise RuntimeError("ProviderConfig declaration: expected exactly one exported type block")
    provider_match = provider_matches[0]
    provider_block = provider_match.group(0)
    if "toolFallbackModel?: string;" not in provider_block:
        provider_anchor = "  visionFallbackModel?: string; // image routing fallback model id or slug\n"
        require_anchor(provider_block, provider_anchor, "ProviderConfig visionFallbackModel field")
        patched_provider = provider_block.replace(provider_anchor, provider_anchor + "  toolFallbackModel?: string; // model id or slug for requests requiring tool calling\n", 1)
        text = text[:provider_match.start()] + patched_provider + text[provider_match.end():]
    updated[types_path] = text


def prepare_config_parser(proxy_dir: pathlib.Path, updated: dict[pathlib.Path, str]) -> None:
    path = proxy_dir / "src/config.ts"
    text = path.read_text(encoding="utf-8")
    marker = "// CERGEA MULTIMODAL ROUTING CAPABILITIES"
    return_marker = "    defaultReasoningLevel,\n    inputModalities,\n"
    if marker not in text:
        # Anchor to parseModel's reasoningLevels declaration and its following
        # returned model object, rather than depending on one exact line layout.
        reasoning_pos = text.find("const reasoningLevels =")
        if reasoning_pos < 0 or text.find("const reasoningLevels =", reasoning_pos + 1) >= 0:
            raise RuntimeError("parseModel reasoningLevels declaration: expected exactly one anchor")
        tail = text[reasoning_pos:]
        return_match = re.search(r"\breturn\s*\{\s*\n[ \t]*id(?:\s*,|\s*:)", tail)
        if not return_match:
            raise RuntimeError("parseModel return object after reasoningLevels: expected one anchor")
        declaration_prefix = tail[:return_match.start()]
        if not re.search(r":\s*undefined;\s*$", declaration_prefix, re.S):
            raise RuntimeError("parseModel reasoningLevels declaration does not end in ': undefined;'")
        return_abs = reasoning_pos + return_match.start()
        line_start = text.rfind("\n", 0, return_abs) + 1
        indent = text[line_start:return_abs]
        if indent.strip():
            raise RuntimeError("parseModel return anchor is not on its own line")
        new = '''  // CERGEA MULTIMODAL ROUTING CAPABILITIES
  const defaultReasoningLevelRaw = optionalString(
    rec.defaultReasoningLevel,
    `models[${index}].defaultReasoningLevel`,
  );
  if (defaultReasoningLevelRaw && !EFFORTS.has(defaultReasoningLevelRaw as ReasoningEffort)) {
    throw new Error(`models[${index}].defaultReasoningLevel is not a valid effort`);
  }
  const defaultReasoningLevel = defaultReasoningLevelRaw as ReasoningEffort | undefined;
  const inputModalities: Array<"text" | "image"> | undefined = Array.isArray(rec.inputModalities)
    ? rec.inputModalities.map((modality, i) => {
        if (modality !== "text" && modality !== "image") {
          throw new Error(`models[${index}].inputModalities[${i}] must be text or image`);
        }
        return modality;
      })
    : undefined;
  if (rec.routeImagesToFallback !== undefined && typeof rec.routeImagesToFallback !== "boolean") {
    throw new Error(`models[${index}].routeImagesToFallback must be a boolean`);
  }
  const routeImagesToFallback = rec.routeImagesToFallback === true;
'''
        text = text[:line_start] + new + text[line_start:]
    elif return_marker not in text:
        raise RuntimeError("partial multimodal config.ts patch detected; inspect src/config.ts manually")

    if return_marker not in text:
        anchor = "    reasoningLevels,\n  };\n"
        require_anchor(text, anchor, "parseModel returned capabilities")
        text = text.replace(anchor, "    reasoningLevels,\n    defaultReasoningLevel,\n    inputModalities,\n    routeImagesToFallback,\n  };\n", 1)

    if "const routeImagesToFallback = rec.routeImagesToFallback === true;" not in text:
        modality_pattern = re.compile(r"(  const inputModalities: Array<\"text\" \| \"image\"> \| undefined = Array\.isArray\(rec\.inputModalities\).*?^    : undefined;\n)", re.S | re.M)
        matches = list(modality_pattern.finditer(text))
        if len(matches) != 1:
            raise RuntimeError(f"parseModel inputModalities block for routeImagesToFallback: expected one match, found {len(matches)}")
        insert = "  if (rec.routeImagesToFallback !== undefined && typeof rec.routeImagesToFallback !== \"boolean\") {\n    throw new Error(`models[${index}].routeImagesToFallback must be a boolean`);\n  }\n  const routeImagesToFallback = rec.routeImagesToFallback === true;\n"
        match = matches[0]
        text = text[:match.end()] + insert + text[match.end():]
    if "    routeImagesToFallback,\n" not in text:
        return_anchor = "    inputModalities,\n  };\n"
        require_anchor(text, return_anchor, "parseModel returned inputModalities")
        text = text.replace(return_anchor, "    inputModalities,\n    routeImagesToFallback,\n  };\n", 1)

    if "const supportsToolCalling = rec.supportsToolCalling === undefined ? undefined : rec.supportsToolCalling as boolean;" not in text:
        anchor = "  const routeImagesToFallback = rec.routeImagesToFallback === true;\n"
        require_anchor(text, anchor, "parseModel routeImagesToFallback declaration")
        addition = "  if (rec.supportsToolCalling !== undefined && typeof rec.supportsToolCalling !== \"boolean\") {\n    throw new Error(`models[${index}].supportsToolCalling must be a boolean`);\n  }\n  const supportsToolCalling = rec.supportsToolCalling === undefined ? undefined : rec.supportsToolCalling as boolean;\n"
        text = text.replace(anchor, anchor + addition, 1)
    if "    supportsToolCalling,\n  };\n" not in text:
        anchor = "    routeImagesToFallback,\n  };\n"
        require_anchor(text, anchor, "parseModel returned routeImagesToFallback")
        text = text.replace(anchor, "    routeImagesToFallback,\n    supportsToolCalling,\n  };\n", 1)

    provider_marker = "visionFallbackModel: optionalString(rec.visionFallbackModel"
    provider_anchor = '    defaultModel: optionalString(rec.defaultModel, `providers.${id}.defaultModel`),\n'
    if provider_marker not in text:
        require_anchor(text, provider_anchor, "parseProvider vision fallback field")
        text = text.replace(
            provider_anchor,
            provider_anchor + '    visionFallbackModel: optionalString(rec.visionFallbackModel, `providers.${id}.visionFallbackModel`),\n',
            1,
        )
    if "toolFallbackModel: optionalString(rec.toolFallbackModel" not in text:
        vision_line = '    visionFallbackModel: optionalString(rec.visionFallbackModel, `providers.${id}.visionFallbackModel`),\n'
        require_anchor(text, vision_line, "parseProvider tool fallback field")
        text = text.replace(vision_line, vision_line + '    toolFallbackModel: optionalString(rec.toolFallbackModel, `providers.${id}.toolFallbackModel`),\n', 1)
    updated[path] = text


def prepare_catalog(proxy_dir: pathlib.Path, updated: dict[pathlib.Path, str]) -> None:
    path = proxy_dir / "src/catalog.ts"
    text = path.read_text(encoding="utf-8")
    level_default = '    default_reasoning_level: reasoning[0]?.effort ?? "none",\n'
    level_new = '    default_reasoning_level: model.defaultReasoningLevel ?? reasoning[0]?.effort ?? "none",\n'
    if level_new not in text:
        require_anchor(text, level_default, "catalog default reasoning level")
        text = text.replace(level_default, level_new, 1)
    modalities_default = '    input_modalities: ["text", "image"],\n'
    modalities_new = '    input_modalities: model.inputModalities ?? ["text", "image"],\n'
    if modalities_new not in text:
        require_anchor(text, modalities_default, "catalog input modalities")
        text = text.replace(modalities_default, modalities_new, 1)
    updated[path] = text


def prepare_router(proxy_dir: pathlib.Path, updated: dict[pathlib.Path, str]) -> None:
    path = proxy_dir / "src/router.ts"
    text = path.read_text(encoding="utf-8")
    import_old = 'import type { ModelConfig, ProxyConfig, ResolvedProvider } from "./types.ts";'
    import_new = 'import type { Message, ModelConfig, ProxyConfig, ResolvedProvider, Tool } from "./types.ts";'
    import_current = 'import type { Message, ModelConfig, ProxyConfig, ResolvedProvider } from "./types.ts";'

    if "routeModelForMessages" not in text:
        if import_new not in text:
            require_anchor(text, import_old, "router type import")
            text = text.replace(import_old, import_new, 1)
        matches = list(re.finditer(r"(?m)^[ \t]*function matchSlug\s*\(", text))
        if len(matches) != 1:
            raise RuntimeError(
                f"router multimodal helper insertion: expected one matchSlug function, found {len(matches)}"
            )
        line_start = text.rfind("\n", 0, matches[0].start()) + 1
        text = text[:line_start] + ROUTER_HELPER + "\n" + text[line_start:]
    else:
        # Upgrade older releases in place. Replace the whole marked helper rather
        # than patching individual expressions: prior versions inspected the full
        # history, pinning text-only follow-ups to the vision fallback.
        if import_new not in text:
            if import_current in text:
                text = text.replace(import_current, import_new, 1)
            elif import_old in text:
                text = text.replace(import_old, import_new, 1)
            else:
                raise RuntimeError("router Message/Tool type import: expected known type import")
        helper_pattern = re.compile(
            r"(?ms)^// CERGEA MULTIMODAL ROUTING\n.*?(?=^[ \t]*function matchSlug\s*\()"
        )
        matches = list(helper_pattern.finditer(text))
        if len(matches) != 1:
            raise RuntimeError(
                f"router multimodal helper migration: expected one marked helper before matchSlug, found {len(matches)}"
            )
        current = matches[0]
        replacement = ROUTER_HELPER.strip("\n") + "\n\n"
        text = text[:current.start()] + replacement + text[current.end():]

    if "const hasImageInLatestUserTurn" not in text:
        raise RuntimeError("router latest-turn image detection: expected a latest user-turn image check")
    if '[cergea-proxy multimodal]' not in text:
        raise RuntimeError("partial router multimodal patch detected; inspect src/router.ts manually")
    updated[path] = text

def prepare_server(proxy_dir: pathlib.Path, updated: dict[pathlib.Path, str]) -> None:
    path = proxy_dir / "src/server.ts"
    text = path.read_text(encoding="utf-8")
    old_import = 'import { listSlugs, routeModel } from "./router.ts";'
    new_import = 'import { listSlugs, routeModelForMessages } from "./router.ts";'
    if new_import not in text:
        require_anchor(text, old_import, "server router import")
        text = text.replace(old_import, new_import, 1)

    old_call = "routeModel(parsed.model, config)"
    new_call = "routeModelForMessages(parsed.model, config, parsed.messages, parsed.tools)"
    old_count = text.count(old_call)
    new_count = text.count(new_call)
    legacy_call = "routeModelForMessages(parsed.model, config, parsed.messages)"
    legacy_count = text.count(legacy_call)
    if old_count + new_count + legacy_count != 2:
        raise RuntimeError(
            f"server routing integration: expected two /responses routes in total, found old={old_count}, new={new_count}, legacy={legacy_count}"
        )
    if old_count:
        text = text.replace(old_call, new_call)
    if legacy_count:
        text = text.replace(legacy_call, new_call)
    updated[path] = text


def main() -> int:
    if len(sys.argv) > 2:
        print("Usage: patch_codex_multimodal_routing.py [PATH_TO/codex-proxy]", file=sys.stderr)
        return 2
    home = pathlib.Path.home()
    proxy_dir = pathlib.Path(sys.argv[1]).expanduser() if len(sys.argv) == 2 else home / ".local/share/cergea-codex-proxy"
    if not proxy_dir.is_dir():
        print(f"ERROR: proxy checkout not found: {proxy_dir}", file=sys.stderr)
        return 2

    source_paths = [
        proxy_dir / "src/types.ts", proxy_dir / "src/config.ts", proxy_dir / "src/catalog.ts",
        proxy_dir / "src/router.ts", proxy_dir / "src/server.ts",
    ]
    missing = [str(path) for path in source_paths if not path.is_file()]
    if missing:
        print("ERROR: required proxy sources missing:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 2

    updated: dict[pathlib.Path, str] = {}
    try:
        prepare_proxy_types(proxy_dir, updated)
        prepare_config_parser(proxy_dir, updated)
        prepare_catalog(proxy_dir, updated)
        prepare_router(proxy_dir, updated)
        prepare_server(proxy_dir, updated)
    except RuntimeError as exc:
        print(f"ERROR: {exc}; no source files were changed.", file=sys.stderr)
        return 1

    # Write files only after every expected anchor was successfully validated.
    for path, new_text in updated.items():
        old_text = path.read_text(encoding="utf-8")
        if old_text == new_text:
            continue
        backup = path.with_name(path.name + ".pre-cergea-multimodal.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(new_text, encoding="utf-8")
        print(f"Updated {path}")

    # Keep runtime routing covered by Bun's normal `bun test` invocation.
    fixture = pathlib.Path(__file__).resolve().parents[1] / "tests/fixtures/cergea-multimodal.test.ts"
    if not fixture.is_file():
        print(f"ERROR: routing regression test is missing from the distribution: {fixture}", file=sys.stderr)
        return 1
    test_content = fixture.read_text(encoding="utf-8")
    if test_content != TEST_SOURCE:
        print(f"ERROR: bundled multimodal regression test differs from the tested fixture: {fixture}", file=sys.stderr)
        return 1
    target_test = proxy_dir / "test/cergea-multimodal.test.ts"
    target_test.parent.mkdir(parents=True, exist_ok=True)
    if not target_test.exists() or target_test.read_text(encoding="utf-8") != test_content:
        if target_test.exists() and target_test.read_text(encoding="utf-8") != test_content:
            backup = target_test.with_name(target_test.name + ".pre-cergea-multimodal.bak")
            if not backup.exists():
                shutil.copy2(target_test, backup)
        target_test.write_text(test_content, encoding="utf-8")
        print(f"Installed multimodal routing regression tests: {target_test}")
    else:
        print(f"Multimodal routing regression tests already installed: {target_test}")
    print("Cergea reasoning metadata, image routing, and tool-call compatibility routing are installed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
