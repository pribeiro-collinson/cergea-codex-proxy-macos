#!/usr/bin/env python3
"""Hermetic regression tests for installer/config writers and proxy patchers.

The companion test_runtime_contracts.py executes additional injected TypeScript at runtime.
Both modules are discovered by the macOS installer; Bun is required at installation time.
"""
from __future__ import annotations

import importlib.util
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def distribution_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Return only files shipped by this package, never arbitrary ~/.codex data."""
    manifest = root / "DISTRIBUTION-MANIFEST.txt"
    if not manifest.is_file():
        raise AssertionError(f"Missing distribution manifest: {manifest}")
    result: list[pathlib.Path] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        relative = line.strip()
        if not relative or relative.startswith("#"):
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise AssertionError(f"Manifest path escapes package root: {relative}") from exc
        if candidate.is_file():
            result.append(candidate)
    return result


def load_module(path: pathlib.Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load test module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_python(script: pathlib.Path, *args: str, env: dict[str, str] | None = None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(script), *args],
        text=True,
        capture_output=True,
        env=merged,
        check=False,
    )


class PatchFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cergea-synth-")
        self.tmp = pathlib.Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_tool_name_and_prefill_patch_is_idempotent(self):
        module = load_module(TOOLS / "patch_codex_proxy.py", "patch_codex_proxy_fixture")
        parts: list[str] = []
        for old, _new, expected_count, _label in module.REPLACEMENTS:
            parts.extend([old] * expected_count)
        path = self.tmp / "openai-chat.ts"
        path.write_text("\n".join(parts), encoding="utf-8")

        first = run_python(TOOLS / "patch_codex_proxy.py", str(path))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        patched = path.read_text(encoding="utf-8")
        self.assertIn("CERGEA BEDROCK COMPATIBILITY PATCH", patched)
        self.assertIn("function upstreamToolName(name: string)", patched)
        self.assertIn("function codexToolName(name: string)", patched)
        self.assertIn('"Continue from the last assistant message."', patched)
        self.assertNotIn("function: { name: call.name, arguments", patched)
        self.assertNotIn("name: tool.name,", patched)

        second = run_python(TOOLS / "patch_codex_proxy.py", str(path))
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(path.read_text(encoding="utf-8"), patched)

    def test_tool_name_patch_fails_closed_on_unrecognized_source(self):
        module = load_module(TOOLS / "patch_codex_proxy.py", "patch_codex_proxy_bad_fixture")
        parts: list[str] = []
        for old, _new, expected_count, _label in module.REPLACEMENTS:
            parts.extend([old] * expected_count)
        source = "\n".join(parts).replace('name: tool.name,', 'name: changed_by_upstream,', 1)
        path = self.tmp / "openai-chat.ts"
        path.write_text(source, encoding="utf-8")
        result = run_python(TOOLS / "patch_codex_proxy.py", str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_text(encoding="utf-8"), source, "a failed patch must not partially mutate source")

    def test_zstd_patch_is_idempotent_and_fail_closed(self):
        module = load_module(TOOLS / "patch_codex_request_zstd.py", "zstd_patch_fixture")
        path = self.tmp / "server.ts"
        path.write_text(module.OLD, encoding="utf-8")
        first = run_python(TOOLS / "patch_codex_request_zstd.py", str(path))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        patched = path.read_text(encoding="utf-8")
        self.assertIn("Bun.zstdDecompressSync(compressed)", patched)
        self.assertIn('request.headers.get("content-encoding")', patched)
        second = run_python(TOOLS / "patch_codex_request_zstd.py", str(path))
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(path.read_text(encoding="utf-8"), patched)
        bad = self.tmp / "bad-server.ts"
        bad.write_text("async function readJson(request: Request) { return request.json(); }", encoding="utf-8")
        original = bad.read_text(encoding="utf-8")
        result = run_python(TOOLS / "patch_codex_request_zstd.py", str(bad))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(bad.read_text(encoding="utf-8"), original)

    def make_proxy_fixture(self, root: pathlib.Path):
        (root / "src/adapters").mkdir(parents=True)
        (root / "src").mkdir(exist_ok=True)
        (root / "src/types.ts").write_text("  contextWindow?: number;\n", encoding="utf-8")
        (root / "src/config.ts").write_text(
            '    contextWindow: optionalNumber(rec.contextWindow, `models[${index}].contextWindow`),\n',
            encoding="utf-8",
        )
        adapter = '''export function toChatBody(parsed: ParsedRequest, model: string): Record<string, unknown> {
  const body: Record<string, unknown> = { model };
  if (parsed.maxTokens !== undefined) body.max_tokens = parsed.maxTokens;
  return body;
}
const serialized = JSON.stringify(toChatBody(parsed, provider.model.id));
'''
        (root / "src/adapters/openai-chat.ts").write_text(adapter, encoding="utf-8")
        server = '''function prepareParsed(parsed: ParsedRequest): ParsedRequest {
  return parsed;
}
async function runAdapter(
  parsed: ParsedRequest,
  provider: Provider,
  fetchFn: typeof fetch,
  abort: AbortSignal,
) {
  const serialized = JSON.stringify(toChatBody(parsed, provider.model.id));
  return serialized;
}
if (path === "/v1/responses" && request.method === "POST") {
        const provider = routeModel(parsed.model, config);
        if (!provider.apiKey && provider.adapter !== "openai-chat") {
          throw new Error("missing key");
        }
        const result = await runAdapter(parsed, provider, fetchFn, abort);
      }
    return json(errorPayload(`Not found: ${path}`));
'''
        (root / "src/server.ts").write_text(server, encoding="utf-8")

    def test_output_budget_patch_and_old_bug_migration(self):
        proxy = self.tmp / "proxy"
        self.make_proxy_fixture(proxy)
        result = run_python(TOOLS / "patch_codex_context_budget.py", str(proxy))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        adapter_path = proxy / "src/adapters/openai-chat.ts"
        patched = adapter_path.read_text(encoding="utf-8")
        self.assertIn("maxOutputTokens?: number", patched)
        self.assertIn("const outputCap = maxOutputTokens ?? 16384;", patched)
        self.assertIn("provider.model.maxOutputTokens))", patched)
        self.assertNotIn("const outputCap = provider.model.maxOutputTokens", patched)
        self.assertIn("CERGEA REQUEST SIZE DIAGNOSTICS", (proxy / "src/server.ts").read_text(encoding="utf-8"))

        # Simulate the bad earlier package and ensure rerunning the patcher repairs it.
        patched = patched.replace(
            "const outputCap = maxOutputTokens ?? 16384;",
            "const outputCap = provider.model.maxOutputTokens ?? 16384;",
            1,
        )
        adapter_path.write_text(patched, encoding="utf-8")
        migrate = run_python(TOOLS / "patch_codex_context_budget.py", str(proxy))
        self.assertEqual(migrate.returncode, 0, migrate.stderr + migrate.stdout)
        patched = adapter_path.read_text(encoding="utf-8")
        self.assertIn("const outputCap = maxOutputTokens ?? 16384;", patched)
        self.assertNotIn("const outputCap = provider.model.maxOutputTokens", patched)

    def test_context_budget_patch_accepts_tools_aware_multimodal_router(self):
        # v5.2.9+ installs routeModelForMessages with parsed.tools. The context
        # diagnostics patch must recognize that already-patched server layout.
        proxy = self.tmp / "proxy-tools-aware-router"
        self.make_proxy_fixture(proxy)
        server_path = proxy / "src/server.ts"
        source = server_path.read_text(encoding="utf-8").replace(
            "routeModel(parsed.model, config)",
            "routeModelForMessages(parsed.model, config, parsed.messages, parsed.tools)",
            1,
        )
        server_path.write_text(source, encoding="utf-8")

        result = run_python(TOOLS / "patch_codex_context_budget.py", str(proxy))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        patched = server_path.read_text(encoding="utf-8")
        self.assertIn(
            "routeModelForMessages(parsed.model, config, parsed.messages, parsed.tools);\n"
            "        logRequestSize(parsed, provider.slug, provider.model.maxOutputTokens ?? 16384);",
            patched,
        )

    def test_context_budget_patch_survives_routing_layout_variants_and_is_idempotent(self):
        # Reproduce the installer's failure: the provider-routing statement is
        # present, but the following conditional differs from the patcher's old
        # two-line literal anchor.
        proxy = self.tmp / "proxy-layout-variant"
        self.make_proxy_fixture(proxy)
        server_path = proxy / "src/server.ts"
        source = server_path.read_text(encoding="utf-8")
        source = source.replace(
            "        if (!provider.apiKey && provider.adapter !== \"openai-chat\") {",
            "        // The upstream conditional was refactored; routing itself is unchanged.\n"
            "        if (provider.adapter !== \"openai-chat\" && !provider.apiKey) {",
            1,
        )
        server_path.write_text(source, encoding="utf-8")

        first = run_python(TOOLS / "patch_codex_context_budget.py", str(proxy))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        patched = server_path.read_text(encoding="utf-8")
        self.assertIn("CERGEA REQUEST SIZE DIAGNOSTICS", patched)
        self.assertIn("logRequestSize(parsed, provider.slug, provider.model.maxOutputTokens ?? 16384);", patched)
        self.assertEqual(patched.count("logRequestSize(parsed, provider.slug"), 1)

        second = run_python(TOOLS / "patch_codex_context_budget.py", str(proxy))
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(server_path.read_text(encoding="utf-8"), patched)

        # Existing-but-different output-cap expressions should count as already
        # wired, rather than causing the old exact-anchor error or duplicate logs.
        partial = self.tmp / "proxy-partial"
        self.make_proxy_fixture(partial)
        partial_server = partial / "src/server.ts"
        source = partial_server.read_text(encoding="utf-8")
        source = source.replace(
            "function prepareParsed(parsed: ParsedRequest): ParsedRequest {",
            "// CERGEA REQUEST SIZE DIAGNOSTICS\nfunction logRequestSize(parsed: ParsedRequest, modelSlug: string, outputCap: number): void {}\n"
            "function prepareParsed(parsed: ParsedRequest): ParsedRequest {",
            1,
        )
        source = source.replace(
            "        if (!provider.apiKey && provider.adapter !== \"openai-chat\") {",
            "        logRequestSize(parsed, provider.slug, 4096);\n"
            "        if (provider.adapter !== \"openai-chat\" && !provider.apiKey) {",
            1,
        )
        partial_server.write_text(source, encoding="utf-8")
        result = run_python(TOOLS / "patch_codex_context_budget.py", str(partial))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(partial_server.read_text(encoding="utf-8").count("logRequestSize(parsed, provider.slug"), 1)

    def test_context_budget_patch_targets_main_responses_route_not_compact_route(self):
        proxy = self.tmp / "proxy-with-compact-route"
        self.make_proxy_fixture(proxy)
        server_path = proxy / "src/server.ts"
        source = server_path.read_text(encoding="utf-8")
        compact_route = '''if (path === "/v1/responses/compact" && request.method === "POST") {
          const provider = routeModel(parsed.model, config);
          const { response } = await runAdapter(parsed, provider, fetchFn, abort);
        }
        '''
        source = source.replace(
            'if (path === "/v1/responses" && request.method === "POST") {',
            compact_route + 'if (path === "/v1/responses" && request.method === "POST") {',
            1,
        )
        server_path.write_text(source, encoding="utf-8")

        result = run_python(TOOLS / "patch_codex_context_budget.py", str(proxy))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        patched = server_path.read_text(encoding="utf-8")
        compact_start = patched.index('if (path === "/v1/responses/compact"')
        main_start = patched.index('if (path === "/v1/responses" && request.method === "POST")')
        compact = patched[compact_start:main_start]
        main = patched[main_start:]
        self.assertNotIn("logRequestSize(parsed, provider.slug", compact)
        self.assertEqual(main.count("logRequestSize(parsed, provider.slug"), 1)

    def test_history_budget_patch_typechecks_against_upstream_message_union(self):
        # This catches TypeScript errors that Bun's transpile-only runtime tests do not.
        tsc = shutil.which("tsc")
        if not tsc:
            proxy_root = pathlib.Path(os.environ.get(
                "CERGEA_CODEX_PROXY_DIR", pathlib.Path.home() / ".local/share/cergea-codex-proxy"
            ))
            local_tsc = proxy_root / "node_modules/.bin/tsc"
            if local_tsc.is_file():
                tsc = str(local_tsc)
        if not tsc:
            self.skipTest("TypeScript compiler isn't available before dependency installation")

        module = load_module(TOOLS / "patch_codex_history_budget.py", "history_budget_typescript_contract")
        declarations = """type ContentPart = { type: \"text\"; text: string } | { type: \"image\"; url: string };
type ToolCall = { id: string; name: string; arguments: string; kind: \"function\" | \"custom\" };
type Message =
  | { role: \"system\" | \"user\"; content: ContentPart[] }
  | { role: \"assistant\"; content: ContentPart[]; toolCalls?: ToolCall[] }
  | { role: \"tool\"; toolCallId: string; name?: string; content: string };
type Tool =
  | { type: \"function\"; name: string; description?: string; parameters?: Record<string, unknown> }
  | { type: \"custom\"; name: string; description?: string };
type ParsedRequest = { messages: Message[]; tools: Tool[]; compactionV2: boolean };
"""
        source = declarations + "\n" + module.INJECT + "\nconst sample: ParsedRequest = { messages: [], tools: [], compactionV2: false };\nboundCergeaHistory(sample, \"fixture/model\");\n"
        fixture = self.tmp / "history-budget-types.ts"
        fixture.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [tsc, "--noEmit", "--strict", "--noUncheckedIndexedAccess", "--target", "ES2022", "--lib", "ES2022,DOM", str(fixture)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_history_budget_runtime_behavior_with_tsc_and_node_when_bun_missing(self):
        tsc = shutil.which("tsc")
        node = shutil.which("node")
        if not tsc or not node:
            self.skipTest("Node.js and TypeScript are needed for the portable fallback runtime test")
        module = load_module(TOOLS / "patch_codex_history_budget.py", "history_budget_node_runtime_contract")
        declarations = """type ContentPart = { type: \"text\"; text: string } | { type: \"image\"; url: string };
type ToolCall = { id: string; name: string; arguments: string; kind: \"function\" | \"custom\" };
type Message =
  | { role: \"system\" | \"user\"; content: ContentPart[] }
  | { role: \"assistant\"; content: ContentPart[]; toolCalls?: ToolCall[] }
  | { role: \"tool\"; toolCallId: string; name?: string; content: string };
type Tool =
  | { type: \"function\"; name: string; description?: string; parameters?: Record<string, unknown> }
  | { type: \"custom\"; name: string; description?: string };
type ParsedRequest = { messages: Message[]; tools: Tool[]; compactionV2: boolean };
"""
        checks = r'''
function check(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`ASSERTION FAILED: ${message}`);
}
console.info = () => {};
const originalUser: Message = { role: "user", content: [{ type: "text", text: "preserve this exact user request" }] };
const sourceTools: Message[] = Array.from({ length: 40 }, (_, i) => ({
  role: "tool" as const, toolCallId: `call-${i}`, name: "shell", content: `PRIVATE_MARKER_${i}_` + "x".repeat(25000),
}));
const parsed: ParsedRequest = { messages: [originalUser, ...sourceTools], tools: [{ type: "function", name: "shell", parameters: { type: "object" } }], compactionV2: false };
const bounded = boundCergeaHistory(parsed, "fixture/model");
const boundedTools = bounded.messages.filter((m) => m.role === "tool");
check(boundedTools.length === 40, "preserve tool result message slots");
check(boundedTools.reduce((sum, m) => sum + (m.role === "tool" ? m.content.length : 0), 0) <= 48000, "enforce aggregate tool text budget");
check(Math.max(...boundedTools.map((m) => m.role === "tool" ? m.content.length : 0)) <= 12000, "enforce per-tool result budget");
check(JSON.stringify(bounded.messages[0]) === JSON.stringify(originalUser), "leave user message unchanged");
check((boundedTools[39] as Extract<Message, { role: "tool" }>).content.includes("PRIVATE_MARKER_39_"), "prioritize newest tool results");
check(!JSON.stringify(bounded).includes("PRIVATE_MARKER_0_"), "old tool result marker omitted");
const image: ContentPart = { type: "image", url: "data:image/png;base64,synthetic" };
const imageParsed: ParsedRequest = { messages: [{ role: "user", content: [image] }, { role: "tool", toolCallId: "x", content: "z".repeat(100000) }], tools: [], compactionV2: false };
const imageBounded = boundCergeaHistory(imageParsed, "fixture/model");
check(JSON.stringify(imageBounded.messages[0]) === JSON.stringify(imageParsed.messages[0]), "preserve image parts");
const call: ToolCall = { id: "call-a", name: "exec", kind: "function", arguments: JSON.stringify({ command: "x".repeat(25000) }) };
const assistantParsed: ParsedRequest = { messages: [{ role: "assistant", content: [{ type: "text", text: "a".repeat(20000) }], toolCalls: [call] }], tools: [], compactionV2: false };
const assistantBounded = boundCergeaHistory(assistantParsed, "fixture/model");
const assistant = assistantBounded.messages[0];
check(assistant !== undefined && assistant.role === "assistant", "retain assistant message");
check(assistant.content.reduce((n, p) => n + (p.type === "text" ? p.text.length : 0), 0) <= 8000, "enforce per-assistant text budget");
check(assistant.toolCalls !== undefined && assistant.toolCalls[0] !== undefined, "retain tool-call metadata");
check(assistant.toolCalls[0].arguments.length <= 4000, "enforce tool-argument limit");
JSON.parse(assistant.toolCalls[0].arguments);
const compact: ParsedRequest = { messages: [{ role: "tool", toolCallId: "c", content: "x".repeat(100000) }], tools: [], compactionV2: true };
check(boundCergeaHistory(compact, "fixture/model") === compact, "do not alter explicit compaction requests");
'''
        fixture = self.tmp / "history-budget-runtime.ts"
        fixture.write_text(declarations + "\n" + module.INJECT + "\n" + checks, encoding="utf-8")
        out_dir = self.tmp / "history-budget-js"
        out_dir.mkdir()
        compile_result = subprocess.run(
            [tsc, "--strict", "--noUncheckedIndexedAccess", "--target", "ES2022", "--lib", "ES2022,DOM", "--module", "commonjs", "--outDir", str(out_dir), str(fixture)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
        js_file = out_dir / "history-budget-runtime.js"
        run_result = subprocess.run([node, str(js_file)], text=True, capture_output=True, check=False)
        self.assertEqual(run_result.returncode, 0, run_result.stdout + run_result.stderr)

    def test_history_budget_strips_historical_images_before_text_model_requests(self):
        source = (TOOLS / "patch_codex_history_budget.py").read_text(encoding="utf-8")
        self.assertIn("latestUserHasImage", source)
        self.assertIn('modelSlug.includes("zai-glm-5")', source)
        self.assertIn('modelSlug.includes("mistral-mixtral-8x7b-instruct")', source)
        self.assertIn('message.content.filter((part) => part.type !== "image")', source)
        self.assertIn("strippedHistoricalImages", source)

    def test_history_budget_injection_is_idempotent_and_routes_bounded_copy(self):
        proxy = self.tmp / "proxy"
        self.make_proxy_fixture(proxy)
        first = run_python(TOOLS / "patch_codex_context_budget.py", str(proxy))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        script = TOOLS / "patch_codex_history_budget.py"
        first = run_python(script, str(proxy))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        path = proxy / "src/server.ts"
        source = path.read_text(encoding="utf-8")
        self.assertIn("CERGEA HISTORY BUDGET", source)
        self.assertIn("boundCergeaHistory(parsed, provider.slug)", source)
        self.assertIn("runAdapter(upstreamParsed, provider, fetchFn, abort)", source)
        self.assertIn("CERGEA_TOOL_ARGUMENT_BUDGET_CHARS", source)
        second = run_python(script, str(proxy))
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(path.read_text(encoding="utf-8"), source)
        # Existing installs must be upgraded, not left running stale inline code.
        old_version = source.replace("const CERGEA_TOOL_TEXT_BUDGET_CHARS = 48_000;", "const CERGEA_TOOL_TEXT_BUDGET_CHARS = 900_000;", 1)
        path.write_text(old_version, encoding="utf-8")
        upgrade = run_python(script, str(proxy))
        self.assertEqual(upgrade.returncode, 0, upgrade.stderr + upgrade.stdout)
        self.assertIn("const CERGEA_TOOL_TEXT_BUDGET_CHARS = 48_000;", path.read_text(encoding="utf-8"))

    def test_history_budget_patch_survives_earlier_responses_branch(self):
        # Regression for v5.1.5: route slicing can stop at an early Not found
        # branch before it reaches the actual provider/adapter route.
        proxy = self.tmp / "proxy"
        self.make_proxy_fixture(proxy)
        server_path = proxy / "src/server.ts"
        original = server_path.read_text(encoding="utf-8")
        early_branch = "\n".join([
            'if (path === "/v1/responses" && request.method === "POST") {',
            '  return json(errorPayload(`Not found: early branch`));',
            '}',
            '',
        ])
        server_path.write_text(early_branch + original, encoding="utf-8")

        context = run_python(TOOLS / "patch_codex_context_budget.py", str(proxy))
        self.assertEqual(context.returncode, 0, context.stderr + context.stdout)
        history_script = TOOLS / "patch_codex_history_budget.py"
        first = run_python(history_script, str(proxy))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        patched = server_path.read_text(encoding="utf-8")
        self.assertEqual(patched.count("const upstreamParsed = boundCergeaHistory(parsed, provider.slug);"), 1)
        self.assertEqual(patched.count("runAdapter(upstreamParsed, provider, fetchFn, abort)"), 1)
        self.assertLess(
            patched.index("const upstreamParsed = boundCergeaHistory(parsed, provider.slug);"),
            patched.index("runAdapter(upstreamParsed, provider, fetchFn, abort)"),
        )
        second = run_python(history_script, str(proxy))
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(server_path.read_text(encoding="utf-8"), patched)

    def test_catalog_repair_preserves_existing_values_and_is_idempotent(self):
        proxy = self.tmp / "proxy"
        home = self.tmp / "proxy-home"
        (proxy / "src").mkdir(parents=True)
        (proxy / "src/catalog.ts").write_text(
            'return {\n    default_reasoning_summary: "none",\n    max_context_window: model.contextWindow ?? 128000,\n};\n',
            encoding="utf-8",
        )
        home.mkdir()
        catalog_path = home / "catalog.json"
        catalog_path.write_text(json.dumps({"models": [{"slug": "cergea/zai-glm-5", "display_name": "GLM", "max_context_window": 200000}]}), encoding="utf-8")
        env = {"HOME": str(self.tmp / "user-home"), "CERGEA_CODEX_PROXY_DIR": str(proxy), "CODEX_PROXY_HOME": str(home)}
        (self.tmp / "user-home").mkdir()
        script = TOOLS / "fix-codex-catalog.py"
        first = run_python(script, env=env)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        model = catalog["models"][0]
        self.assertEqual(model["max_context_window"], 200000)
        self.assertIn("truncation_policy", model)
        self.assertIn("experimental_supported_tools", model)
        generator = (proxy / "src/catalog.ts").read_text(encoding="utf-8")
        self.assertIn("experimental_supported_tools", generator)
        repaired = catalog_path.read_text(encoding="utf-8")
        second = run_python(script, env=env)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(catalog_path.read_text(encoding="utf-8"), repaired)

    def test_proxy_config_preserves_other_providers_and_never_persists_secret(self):
        home = self.tmp / "proxy-home"
        home.mkdir()
        config_path = home / "config.json"
        config_path.write_text(json.dumps({
            "listen": "0.0.0.0:1234",
            "customSetting": "preserve-me",
            "providers": {
                "other": {"adapter": "openai-chat", "baseUrl": "https://example.invalid/v1"},
                "cergea": {"apiKey": "DO_NOT_KEEP", "headers": {"x-team": "qa"}},
            },
        }), encoding="utf-8")
        env = {"CODEX_PROXY_HOME": str(home)}
        script = TOOLS / "prepare_proxy_config.py"
        first = run_python(script, env=env)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["listen"], "127.0.0.1:18789")
        self.assertEqual(saved["customSetting"], "preserve-me")
        self.assertIn("other", saved["providers"])
        self.assertEqual(saved["providers"]["cergea"]["headers"], {"x-team": "qa"})
        self.assertNotIn("apiKey", saved["providers"]["cergea"])
        self.assertEqual(saved["providers"]["cergea"]["apiKeyEnv"], "CERGEA_LITELLM_API_KEY")
        caps = {m["id"]: m["maxOutputTokens"] for m in saved["providers"]["cergea"]["models"]}
        self.assertEqual(caps["zai-glm-5"], 16384)
        self.assertEqual(caps["mistral-mixtral-8x7b-instruct"], 4096)
        once = config_path.read_text(encoding="utf-8")
        second = run_python(script, env=env)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(config_path.read_text(encoding="utf-8"), once)

    def test_codex_config_preserves_unrelated_settings_and_legacy_alias(self):
        config_path = self.tmp / "config.toml"
        original = '''model = "gpt-5.6-sol"
model_provider = "cergea-litellm"
model_catalog_json = "/Users/old/.codex/model-catalogs/cergea.json"
model_auto_compact_token_limit = 900000
model_reasoning_effort = "low"

[mcp_servers.docs]
command = "docs-mcp"
args = ["--quiet"]

[model_providers.cergea-litellm]
name = "old provider"
base_url = "https://example.invalid/v1"
wire_api = "responses"
'''
        config_path.write_text(original, encoding="utf-8")
        script = TOOLS / "prepare_codex_config.py"
        first = run_python(script, str(config_path))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        updated = config_path.read_text(encoding="utf-8")
        self.assertIn('[mcp_servers.docs]', updated)
        self.assertIn('command = "docs-mcp"', updated)
        self.assertIn('[model_providers.cergea-litellm]', updated)
        self.assertIn('base_url = "http://127.0.0.1:18789/v1"', updated)
        self.assertIn("model_auto_compact_token_limit = 120000", updated)
        self.assertIn('model_reasoning_effort = "low"', updated, "preserve the user's chosen reasoning effort")
        self.assertNotIn('model_reasoning_effort = "high"', updated)
        self.assertNotIn('/Users/old/.codex/model-catalogs/cergea.json', updated)
        once = updated
        second = run_python(script, str(config_path))
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(config_path.read_text(encoding="utf-8"), once)


    def test_codex_config_created_for_brand_new_install(self):
        config_path = self.tmp / "fresh-home" / ".codex" / "config.toml"
        script = TOOLS / "prepare_codex_config.py"
        first = run_python(script, str(config_path))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertTrue(config_path.is_file(), "fresh install must create config.toml")
        text = config_path.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^model_auto_compact_token_limit = 120000(?:\s|#)")
        self.assertRegex(text, r'(?m)^model_reasoning_effort = "high"')
        self.assertIn("[model_providers.cergea-litellm]", text)
        self.assertIn('base_url = "http://127.0.0.1:18789/v1"', text)
        self.assertIn('wire_api = "responses"', text)
        self.assertNotIn("api_key", text.lower())
        self.assertNotIn("CERGEA_LITELLM_API_KEY=", text)
        first_text = text
        second = run_python(script, str(config_path))
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(config_path.read_text(encoding="utf-8"), first_text, "fresh config creation should be idempotent")

    def test_installer_replaces_symlinks_without_overwriting_their_targets(self):
        target_home = self.tmp / "target-codex-home-symlink"
        external = self.tmp / "user-owned-script.sh"
        external.write_text("#!/bin/sh\necho user-owned\n", encoding="utf-8")
        target_script = target_home / "bin/start-cergea-codex"
        target_script.parent.mkdir(parents=True)
        target_script.symlink_to(external)
        env = {**os.environ, "CODEX_HOME": str(target_home)}
        result = subprocess.run([str(ROOT / "install.sh"), "--copy-only"], cwd=self.tmp,
                                text=True, capture_output=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(target_script.is_symlink(), "package-owned path should be a regular file")
        self.assertIn("exec bun --use-system-ca run", target_script.read_text(encoding="utf-8"))
        self.assertEqual(external.read_text(encoding="utf-8"), "#!/bin/sh\necho user-owned\n", "installer must not write through symlink")
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        backups = list(target_script.parent.glob(f"start-cergea-codex.pre-cergea-v{version}-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].is_symlink(), "backup should preserve the original symlink")

    def test_reasoning_selector_and_multimodal_routing_patcher_is_idempotent(self):
        proxy = self.tmp / "multimodal-proxy"
        (proxy / "src").mkdir(parents=True)
        (proxy / "test").mkdir()
        (proxy / "src/types.ts").write_text('''export type ReasoningEffort = "none" | "low" | "medium" | "high" | "xhigh" | "max";
export type ModelConfig = {
  id: string;
  displayName?: string;
  description?: string;
  contextWindow?: number;
  maxOutputTokens?: number;
  reasoning?: boolean;
  reasoningLevels?: ReasoningEffort[];
};
export type ProviderConfig = {
  adapter: "openai-chat";
  baseUrl: string;
  apiKeyEnv?: string;
  models: ModelConfig[];
  defaultModel?: string;
};
export type ProxyConfig = {
  defaultModel?: string;
  providers: Record<string, ProviderConfig>;
};
export type ResolvedProvider = { id: string; slug: string; model: ModelConfig };
export type Tool = { type: "function"; name: string; description?: string; parameters?: Record<string, unknown> };
export type ContentPart = { type: "text"; text: string } | { type: "image"; url: string };
export type Message = { role: "system" | "user"; content: string | ContentPart[] } | { role: "assistant"; content: string | ContentPart[] } | { role: "tool"; content: string };
''', encoding="utf-8")
        (proxy / "src/config.ts").write_text('''const EFFORTS = new Set(["none", "low", "medium", "high", "xhigh", "max"]);
function optionalNumber(value: unknown, label: string): number | undefined { return undefined; }
function optionalString(value: unknown, label: string): string | undefined { return typeof value === "string" ? value : undefined; }
function asRecord(value: unknown, label: string): Record<string, unknown> { return value as Record<string, unknown>; }
function parseModel(raw: unknown, index: number) {
  const rec = asRecord(raw, "model");
  const reasoningLevels = Array.isArray(rec.reasoningLevels) ? rec.reasoningLevels : undefined;
  return {
    id: "model",
    displayName: undefined,
    description: undefined,
    contextWindow: undefined,
    maxOutputTokens: undefined,
    reasoning: undefined,
    reasoningLevels,
  };
}
function parseProvider(raw: unknown, id: string) {
  const rec = asRecord(raw, "provider");
  return {
    adapter: "openai-chat" as const,
    baseUrl: "https://example.invalid",
    apiKeyEnv: undefined,
    models: [],
    defaultModel: optionalString(rec.defaultModel, `providers.${id}.defaultModel`),
  };
}
export function parseConfig(raw: any): any { return raw; }
''', encoding="utf-8")
        (proxy / "src/catalog.ts").write_text('''function catalogEntry(model: ModelConfig) {
  const reasoning = model.reasoningLevels ?? [];
  return {
    default_reasoning_level: reasoning[0]?.effort ?? "none",
    input_modalities: ["text", "image"],
  };
}
''', encoding="utf-8")
        (proxy / "src/router.ts").write_text('''import type { ModelConfig, ProxyConfig, ResolvedProvider } from "./types.ts";
export function routeModel(requested: string, config: ProxyConfig, env: NodeJS.ProcessEnv = process.env): ResolvedProvider {
  return {} as ResolvedProvider;
}
function matchSlug() {}
''', encoding="utf-8")
        (proxy / "src/server.ts").write_text('''import { listSlugs, routeModel } from "./router.ts";
async function runAdapter() {}
if (path === "/v1/responses/compact" && request.method === "POST") {
  const provider = routeModel(parsed.model, config);
}
if (path === "/v1/responses" && request.method === "POST") {
  const provider = routeModel(parsed.model, config);
}
''', encoding="utf-8")

        script = TOOLS / "patch_codex_multimodal_routing.py"
        first = run_python(script, str(proxy))
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        router = (proxy / "src/router.ts").read_text(encoding="utf-8")
        server = (proxy / "src/server.ts").read_text(encoding="utf-8")
        config = (proxy / "src/config.ts").read_text(encoding="utf-8")
        catalog = (proxy / "src/catalog.ts").read_text(encoding="utf-8")
        self.assertIn("routeModelForMessages", router)
        types = (proxy / "src/types.ts").read_text(encoding="utf-8")
        self.assertEqual(types.count("visionFallbackModel?: string;"), 1)
        provider_block = types.split("export type ProviderConfig = {", 1)[1].split("\n};", 1)[0]
        proxy_config_block = types.split("export type ProxyConfig = {", 1)[1].split("\n};", 1)[0]
        self.assertIn("visionFallbackModel?: string;", provider_block)
        self.assertNotIn("visionFallbackModel?: string;", proxy_config_block)
        self.assertIn('visionFallbackModel: optionalString(rec.visionFallbackModel', config)
        self.assertIn("defaultReasoningLevel", config)
        self.assertIn("inputModalities", config)
        self.assertIn("routeImagesToFallback", config)
        self.assertIn("routeImagesToFallback?: boolean;", types)
        self.assertIn("supportsToolCalling?: boolean;", types)
        self.assertIn("toolFallbackModel?: string;", provider_block)
        self.assertIn('toolFallbackModel: optionalString(rec.toolFallbackModel', config)
        self.assertIn("supportsToolCalling", config)
        self.assertIn('model.inputModalities ?? ["text", "image"]', catalog)
        self.assertIn('model.defaultReasoningLevel ?? reasoning[0]?.effort', catalog)
        self.assertEqual(server.count("routeModelForMessages(parsed.model, config, parsed.messages, parsed.tools)"), 2)
        self.assertIn("tools.length > 0 && selected.model.supportsToolCalling === false", router)
        self.assertIn("toolFallbackModel", router)
        self.assertIn("[cergea-proxy tool-compat]", router)
        test_file = proxy / "test/cergea-multimodal.test.ts"
        self.assertTrue(test_file.is_file())
        self.assertIn("advertises GLM image input but routes image turns to Haiku", test_file.read_text(encoding="utf-8"))
        self.assertIn("advertises Mistral image paste and routes image turns to Haiku", test_file.read_text(encoding="utf-8"))
        self.assertIn("returns text-only Mistral follow-ups to Mistral when an earlier image remains in history", test_file.read_text(encoding="utf-8"))

        # Simulate a v5.2.8 install: it has image routing, but not tool-capability
        # metadata, nor a tools-aware router signature / server integration.
        router_path = proxy / "src/router.ts"
        router = router_path.read_text(encoding="utf-8")
        router = router.replace(
            'import type { Message, ModelConfig, ProxyConfig, ResolvedProvider, Tool } from "./types.ts";',
            'import type { Message, ModelConfig, ProxyConfig, ResolvedProvider } from "./types.ts";',
            1,
        )
        router = router.replace('  tools: Tool[] = [],\n', '', 1)
        tool_block = '''
  if (tools.length > 0 && selected.model.supportsToolCalling === false) {
    const fallback = config.providers[selected.id]?.toolFallbackModel;
    if (!fallback) {
      throw new Error(
        `Model '${selected.slug}' does not support tool calling and provider '${selected.id}' has no toolFallbackModel configured`,
      );
    }
    const fallbackSlug = fallback.includes("/") ? fallback : `${selected.id}/${fallback}`;
    const toolProvider = routeModel(fallbackSlug, config, env);
    if (toolProvider.model.supportsToolCalling === false) {
      throw new Error(`Configured tool fallback '${toolProvider.slug}' also disables tool calling`);
    }
    console.info(
      `[cergea-proxy tool-compat] Routed ${selected.slug} to ${toolProvider.slug} because the selected model does not support tool calling`,
    );
    return toolProvider;
  }
'''
        router = router.replace(tool_block, '', 1)
        router_path.write_text(router, encoding="utf-8")

        server_path = proxy / "src/server.ts"
        server = server_path.read_text(encoding="utf-8").replace(
            "routeModelForMessages(parsed.model, config, parsed.messages, parsed.tools)",
            "routeModelForMessages(parsed.model, config, parsed.messages)",
        )
        server_path.write_text(server, encoding="utf-8")

        types_path = proxy / "src/types.ts"
        types = types_path.read_text(encoding="utf-8")
        types = types.replace('  supportsToolCalling?: boolean; // whether the provider model supports tools\n', '')
        types = types.replace('  toolFallbackModel?: string; // model id or slug for requests requiring tool calling\n', '')
        types_path.write_text(types, encoding="utf-8")
        config_path = proxy / "src/config.ts"
        config = config_path.read_text(encoding="utf-8")
        support_block = '''  if (rec.supportsToolCalling !== undefined && typeof rec.supportsToolCalling !== "boolean") {
    throw new Error(`models[${index}].supportsToolCalling must be a boolean`);
  }
  const supportsToolCalling = rec.supportsToolCalling === undefined ? undefined : rec.supportsToolCalling as boolean;
'''
        config = config.replace(support_block, '', 1).replace('    supportsToolCalling,\n', '', 1)
        config = config.replace('    toolFallbackModel: optionalString(rec.toolFallbackModel, `providers.${id}.toolFallbackModel`),\n', '', 1)
        config_path.write_text(config, encoding="utf-8")

        migrate = run_python(script, str(proxy))
        self.assertEqual(migrate.returncode, 0, migrate.stderr + migrate.stdout)
        router = router_path.read_text(encoding="utf-8")
        config = config_path.read_text(encoding="utf-8")
        types = types_path.read_text(encoding="utf-8")
        server = server_path.read_text(encoding="utf-8")
        self.assertIn("tools: Tool[] = []", router)
        self.assertIn("tools.length > 0 && selected.model.supportsToolCalling === false", router)
        self.assertIn("supportsToolCalling?: boolean;", types)
        self.assertIn("toolFallbackModel?: string;", types)
        self.assertIn("const supportsToolCalling = rec.supportsToolCalling === undefined ? undefined : rec.supportsToolCalling as boolean;", config)
        self.assertIn("toolFallbackModel: optionalString(rec.toolFallbackModel", config)
        self.assertEqual(server.count("routeModelForMessages(parsed.model, config, parsed.messages, parsed.tools)"), 2)

        before = {str(path): path.read_text(encoding="utf-8") for path in proxy.glob("src/*.ts")}
        second = run_python(script, str(proxy))
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        after = {str(path): path.read_text(encoding="utf-8") for path in proxy.glob("src/*.ts")}
        self.assertEqual(after, before, "routing patch must be idempotent after upgrade migration")

    def test_multimodal_helper_typechecks_string_or_array_content(self):
        tsc = shutil.which("tsc")
        if not tsc:
            self.skipTest("TypeScript compiler isn't available before dependency installation")
        patcher = load_module(TOOLS / "patch_codex_multimodal_routing.py", "multimodal_typescript_contract")
        declarations = '''
type ContentPart = { type: "text"; text: string } | { type: "image"; url: string };
type Message =
  | { role: "user" | "system"; content: string | ContentPart[] }
  | { role: "assistant"; content: string | ContentPart[] }
  | { role: "tool"; content: string };
type Tool = { type: "function"; name: string };
type ModelConfig = { inputModalities?: Array<"text" | "image">; routeImagesToFallback?: boolean; supportsToolCalling?: boolean };
type ProviderConfig = { visionFallbackModel?: string; toolFallbackModel?: string };
type ProxyConfig = { providers: Record<string, ProviderConfig> };
type ResolvedProvider = { id: string; slug: string; model: ModelConfig };
declare namespace NodeJS { interface ProcessEnv { [key: string]: string | undefined } }
declare const process: { env: NodeJS.ProcessEnv };
declare const console: { info: (...args: unknown[]) => void };
declare function routeModel(requested: string, config: ProxyConfig, env: NodeJS.ProcessEnv): ResolvedProvider;
'''
        fixture = self.tmp / "multimodal-helper-types.ts"
        fixture.write_text(declarations + "\n" + patcher.ROUTER_HELPER, encoding="utf-8")
        result = subprocess.run(
            [tsc, "--noEmit", "--strict", "--noUncheckedIndexedAccess", "--target", "ES2022", "--lib", "ES2022,DOM", str(fixture)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reasoning_capabilities_are_written_to_proxy_model_config(self):
        script = TOOLS / "prepare_proxy_config.py"
        key = "unit-test-key"
        env = {"CERGEA_LITELLM_API_KEY": key, "CODEX_PROXY_HOME": str(self.tmp / "proxy-home")}
        result = run_python(script, env=env)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        config = json.loads((self.tmp / "proxy-home/config.json").read_text(encoding="utf-8"))
        provider = config["providers"]["cergea"]
        self.assertEqual(provider["visionFallbackModel"], "claude-haiku-5-5")
        self.assertEqual(provider["toolFallbackModel"], "zai-glm-5")
        models = {model["id"]: model for model in provider["models"]}
        self.assertEqual(models["zai-glm-5"]["reasoningLevels"], ["low", "medium", "high"])
        self.assertEqual(models["zai-glm-5"]["inputModalities"], ["text", "image"])
        self.assertTrue(models["zai-glm-5"]["routeImagesToFallback"])
        self.assertEqual(models["claude-haiku-5-5"]["inputModalities"], ["text", "image"])
        self.assertEqual(models["claude-sonnet-5-5"]["inputModalities"], ["text", "image"])
        self.assertEqual(models["mistral-mixtral-8x7b-instruct"]["maxOutputTokens"], 4096)
        self.assertEqual(models["mistral-mixtral-8x7b-instruct"]["inputModalities"], ["text", "image"])
        self.assertTrue(models["mistral-mixtral-8x7b-instruct"]["routeImagesToFallback"])
        self.assertIs(models["mistral-mixtral-8x7b-instruct"]["supportsToolCalling"], False)
        self.assertNotIn(key, (self.tmp / "proxy-home/config.json").read_text(encoding="utf-8"))

    def test_distribution_manifest_covers_exactly_package_files_and_excludes_bytecode(self):
        # When installed from an extracted ZIP, check the original release folder.
        # ~/.codex is shared user state and must not be treated as a pristine package.
        manifest_root = pathlib.Path(os.environ.get("CERGEA_DISTRIBUTION_ROOT", ROOT)).resolve()
        codex_home = pathlib.Path(os.environ.get("CODEX_HOME", pathlib.Path.home() / ".codex")).expanduser().resolve()
        manifest_text = (manifest_root / "DISTRIBUTION-MANIFEST.txt").read_text(encoding="utf-8")
        manifest_entries = {
            line.strip() for line in manifest_text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        missing_entries = sorted(rel for rel in manifest_entries if not (manifest_root / rel).is_file())
        self.assertEqual(missing_entries, [], f"manifest entries missing from package: {missing_entries}")
        listed = {path.relative_to(manifest_root).as_posix() for path in distribution_files(manifest_root)}
        self.assertIn("docs/CHANGELOG-v5.2.2.md", manifest_text)
        self.assertIn("tools/patch_codex_multimodal_routing.py", manifest_text)
        self.assertIn("tools/update_distribution_manifest.py", manifest_text)
        self.assertIn("tests/fixtures/cergea-multimodal.test.ts", manifest_text)
        self.assertIn("docs/CHANGELOG-v5.2.3.md", manifest_text)
        self.assertIn("docs/CHANGELOG-v5.2.6.md", manifest_text)
        self.assertIn("docs/CHANGELOG-v5.2.7.md", manifest_text)
        self.assertIn("docs/CHANGELOG-v5.2.8.md", manifest_text)
        self.assertIn("docs/CHANGELOG-v5.2.9.md", manifest_text)
        self.assertIn("docs/CHANGELOG-v5.2.10.md", manifest_text)
        self.assertNotIn("config.toml", {line.strip() for line in manifest_text.splitlines() if line.strip() and not line.lstrip().startswith("#")})

        # Direct extraction into ~/.codex is supported. In that mode, extra user
        # files are expected and should neither enter the manifest nor fail this test.
        if manifest_root == codex_home:
            self.assertTrue(all((manifest_root / rel).is_file() for rel in listed))
            return

        updater = load_module(TOOLS / "update_distribution_manifest.py", "manifest_updater_contract")
        self.assertEqual(manifest_text, updater.build_manifest(manifest_root),
                         "distribution manifest is stale; installer should refresh it automatically")
        self.assertFalse(list(manifest_root.rglob("*.pyc")), "compiled Python bytecode must not ship")

    def test_distribution_manifest_updater_tracks_new_package_files_idempotently(self):
        updater_source = TOOLS / "update_distribution_manifest.py"
        root = self.tmp / "release"
        (root / "tools").mkdir(parents=True)
        (root / "tools/update_distribution_manifest.py").write_bytes(updater_source.read_bytes())
        (root / "README.md").write_text("readme\n", encoding="utf-8")
        (root / "config.toml").write_text("user config must stay out\n", encoding="utf-8")
        result = run_python(updater_source, str(root))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = root / "DISTRIBUTION-MANIFEST.txt"
        first = manifest.read_text(encoding="utf-8")
        self.assertIn("README.md", first)
        self.assertIn("tools/update_distribution_manifest.py", first)
        self.assertNotIn("config.toml", first)
        (root / "docs").mkdir()
        (root / "docs/NEW-RELEASE-NOTE.md").write_text("new file\n", encoding="utf-8")
        result = run_python(updater_source, str(root))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        second = manifest.read_text(encoding="utf-8")
        self.assertIn("docs/NEW-RELEASE-NOTE.md", second)
        result = run_python(updater_source, str(root))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(manifest.read_text(encoding="utf-8"), second, "manifest generation must be idempotent")


    def test_ponytail_prompt_is_opt_in_by_default(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn('Install the optional Ponytail Codex plugin now? [y/N]', installer)
        self.assertIn('answer="${answer:-N}"', installer)

    def test_ponytail_installer_commands_and_idempotency(self):
        fakebin = self.tmp / "fakebin"
        fakebin.mkdir()
        log = self.tmp / "codex-calls.log"
        fake_codex = fakebin / "codex"
        fake_codex.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_CODEX_LOG"\n',
            encoding="utf-8",
        )
        fake_codex.chmod(0o755)
        fake_node = fakebin / "node"
        fake_node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_node.chmod(0o755)
        codex_home = self.tmp / ".codex"
        env = {
            "CODEX_HOME": str(codex_home),
            "FAKE_CODEX_LOG": str(log),
            "PATH": str(fakebin) + os.pathsep + os.environ.get("PATH", ""),
        }
        script = ROOT / "bin/install-ponytail"
        first = subprocess.run([str(script)], text=True, capture_output=True, env={**os.environ, **env}, check=False)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, [
            "plugin marketplace add DietrichGebert/ponytail",
            "plugin add ponytail@ponytail",
        ])
        second = subprocess.run([str(script)], text=True, capture_output=True, env={**os.environ, **env}, check=False)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(log.read_text(encoding="utf-8").splitlines(), lines, "rerun should not duplicate CLI operations")

    def test_ponytail_installer_discovers_codex_cli_from_config_when_not_on_path(self):
        # ChatGPT Desktop can bundle Codex CLI without exposing `codex` on PATH.
        fakebin = self.tmp / "fakebin-config-path"
        fakebin.mkdir()
        fake_node = fakebin / "node"
        fake_node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_node.chmod(0o755)
        codex_home = self.tmp / ".codex-configured-cli"
        codex_home.mkdir()
        log = self.tmp / "configured-codex-calls.log"
        bundled_cli = self.tmp / "ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
        bundled_cli.parent.mkdir(parents=True)
        bundled_cli.write_text(
            '#!/bin/sh\nprintf "%s\n" "$*" >> "$FAKE_CODEX_LOG"\n',
            encoding="utf-8",
        )
        bundled_cli.chmod(0o755)
        (codex_home / "config.toml").write_text(
            f'CODEX_CLI_PATH = "{bundled_cli}"\n', encoding="utf-8"
        )
        env = {
            "CODEX_HOME": str(codex_home),
            "FAKE_CODEX_LOG": str(log),
            # Do not put the fake Codex CLI on PATH. Keep only the fake node plus
            # OS tools needed by the script, reproducing the failure condition.
            "PATH": str(fakebin) + os.pathsep + "/usr/bin:/bin",
        }
        script = ROOT / "bin/install-ponytail"
        result = subprocess.run(
            [str(script)], text=True, capture_output=True, env={**os.environ, **env}, check=False
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(bundled_cli), result.stdout)
        self.assertEqual(log.read_text(encoding="utf-8").splitlines(), [
            "plugin marketplace add DietrichGebert/ponytail",
            "plugin add ponytail@ponytail",
        ])

    def _copy_complete_distribution(self, destination: pathlib.Path) -> None:
        """Stage a full release using only package-owned manifest entries."""
        for source in distribution_files(ROOT):
            relative = source.relative_to(ROOT)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def test_bundle_copy_only_backs_up_conflicting_files(self):
        installer = ROOT / "install.sh"
        target_home = self.tmp / "target-codex-home"
        target_script = target_home / "bin/start-cergea-codex"
        target_script.parent.mkdir(parents=True)
        target_script.write_text("# user's previous launcher\n", encoding="utf-8")
        env = {**os.environ, "CODEX_HOME": str(target_home)}
        # Invoke by absolute path with an unrelated CWD, as users often do from Downloads.
        result = subprocess.run([str(installer), "--copy-only"], cwd=self.tmp,
                                text=True, capture_output=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("#!/bin/bash", target_script.read_text(encoding="utf-8"))
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        backups = list(target_script.parent.glob(f"start-cergea-codex.pre-cergea-v{version}-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertIn("user's previous launcher", backups[0].read_text(encoding="utf-8"))
        self.assertTrue((target_home / "tests/test_synthetic.py").is_file())
        self.assertTrue((target_home / "bin/install-ponytail").is_file())
        self.assertTrue((target_home / "install.sh").is_file(), "bootstrap must be updated with the package")
        self.assertTrue((target_home / "DISTRIBUTION-MANIFEST.txt").is_file())
        self.assertEqual((target_home / "install.sh").read_bytes(), installer.read_bytes())

        # Re-running the copied installer from elsewhere must remain idempotent.
        second = subprocess.run(["bash", str(target_home / "install.sh"), "--copy-only"],
                                cwd=self.tmp, text=True, capture_output=True,
                                env=env, check=False)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertFalse(list(target_home.glob(f"*.pre-cergea-v{version}-*.bak")))

    def test_installer_refreshes_manifest_when_a_package_file_is_added(self):
        bundle = self.tmp / "release-bundle"
        bundle.mkdir()
        self._copy_complete_distribution(bundle)
        new_package_file = bundle / "tools/auto-discovered-package-file.py"
        new_package_file.write_text("# added after the initial manifest was generated\n", encoding="utf-8")
        target_home = self.tmp / "target-codex-home"
        env = {**os.environ, "CODEX_HOME": str(target_home)}
        result = subprocess.run(
            ["bash", str(bundle / "install.sh"), "--copy-only"], cwd=self.tmp,
            text=True, capture_output=True, env=env, check=False, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("tools/auto-discovered-package-file.py", (bundle / "DISTRIBUTION-MANIFEST.txt").read_text(encoding="utf-8"))
        self.assertEqual(
            (target_home / "tools/auto-discovered-package-file.py").read_text(encoding="utf-8"),
            "# added after the initial manifest was generated\n",
        )

    def test_installer_does_not_scan_default_codex_home_when_target_is_overridden(self):
        fake_home = self.tmp / "fake-user-home"
        source_codex_home = fake_home / ".codex"
        source_codex_home.mkdir(parents=True)
        self._copy_complete_distribution(source_codex_home)
        unrelated = source_codex_home / "unrelated-session-index.json"
        unrelated.write_text('{"user_data": true}\n', encoding="utf-8")
        manifest_before = (source_codex_home / "DISTRIBUTION-MANIFEST.txt").read_text(encoding="utf-8")
        target_home = self.tmp / "alternate-codex-home"
        env = {**os.environ, "HOME": str(fake_home), "CODEX_HOME": str(target_home)}
        result = subprocess.run(
            ["bash", str(source_codex_home / "install.sh"), "--copy-only"], cwd=self.tmp,
            text=True, capture_output=True, env=env, check=False, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((source_codex_home / "DISTRIBUTION-MANIFEST.txt").read_text(encoding="utf-8"), manifest_before)
        self.assertNotIn("unrelated-session-index.json", manifest_before)
        self.assertFalse((target_home / "unrelated-session-index.json").exists(),
                         "user-owned files in the source Codex home must not be distributed")

    def test_bundle_copy_only_is_safe_when_extracted_directly_into_codex_home(self):
        # Reproduce direct extraction into ~/.codex and invocation from another CWD.
        bundle = self.tmp / ".codex"
        bundle.mkdir(parents=True)
        self._copy_complete_distribution(bundle)
        env = {**os.environ, "CODEX_HOME": str(bundle)}
        result = subprocess.run(
            ["bash", str(bundle / "install.sh"), "--copy-only"], cwd=self.tmp,
            text=True, capture_output=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Already in destination, skipped: bin/start-cergea-codex", result.stdout)
        self.assertIn("Already in destination, skipped: install.sh", result.stdout)
        self.assertIn("Already in destination, skipped: DISTRIBUTION-MANIFEST.txt", result.stdout)
        self.assertIn("copy-only mode", result.stdout)
        self.assertTrue((bundle / "bin/start-cergea-codex").is_file())

    def test_runtime_tls_bundle_is_built_even_when_dependencies_exist(self):
        installer = (ROOT / "bin/install-cergea-codex").read_text(encoding="utf-8")
        builder = ROOT / "tools/build_macos_ca_bundle.sh"
        self.assertTrue(builder.is_file())
        self.assertIn("security find-certificate -a -p", builder.read_text(encoding="utf-8"))
        build_call = '\"$BUNDLE_ROOT/tools/build_macos_ca_bundle.sh\" \"$CA_BUNDLE\"'
        self.assertIn(build_call, installer)
        deps_check = 'if [[ ! -x "$PROXY_DIR/node_modules/.bin/tsc" ]]; then'
        self.assertLess(installer.index(build_call), installer.index(deps_check))
        self.assertIn('SSL_CERT_FILE="$CA_BUNDLE" bun install --frozen-lockfile --cafile "$CA_BUNDLE"', installer)
        self.assertNotIn('NODE_TLS_REJECT_UNAUTHORIZED=0', installer + builder.read_text(encoding="utf-8"))

    def test_fresh_install_config_is_created_and_documents_current_release(self):
        config_path = self.tmp / "empty-user" / ".codex" / "config.toml"
        result = run_python(TOOLS / "prepare_codex_config.py", str(config_path))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        text = config_path.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^model_auto_compact_token_limit = 120000(?:\s|#)")
        self.assertIn('[model_providers.cergea-litellm]', text)
        self.assertIn('base_url = "http://127.0.0.1:18789/v1"', text)
        self.assertIn('wire_api = "responses"', text)
        self.assertNotIn("CERGEA_LITELLM_API_KEY=", text)
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertIn(f"v{version}", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertTrue((ROOT / "docs" / f"CHANGELOG-v{version}.md").is_file())

    def test_ca_bundle_supports_explicit_company_root(self):
        script = (ROOT / "tools/build_macos_ca_bundle.sh").read_text(encoding="utf-8")
        self.assertIn('append_pem_file "$CERGEA_EXTRA_CA_CERT"', script)
        self.assertIn('append_pem_file "${NODE_EXTRA_CA_CERTS:-}"', script)
        self.assertIn('append_pem_file "${SSL_CERT_FILE:-}"', script)
        self.assertIn('/System/Library/Keychains/SystemRootCertificates.keychain', script)
        self.assertNotIn('/Library/Keychains/System.keychain', script)
        self.assertNotIn('login.keychain-db', script)
        self.assertNotIn('NODE_TLS_REJECT_UNAUTHORIZED=0', script)

    def test_runtime_launcher_passes_macos_ca_bundle_to_bun(self):
        launcher = (ROOT / "bin/start-cergea-codex").read_text(encoding="utf-8")
        self.assertIn('CA_BUNDLE="$PROXY_HOME/macos-trust-bundle.pem"', launcher)
        self.assertIn('export NODE_EXTRA_CA_CERTS="$CA_BUNDLE"', launcher)
        self.assertIn('export SSL_CERT_FILE="$CA_BUNDLE"', launcher)
        self.assertIn('bun --use-system-ca -e', launcher)
        self.assertIn('/v1/models', launcher)
        self.assertIn('Bun runtime TLS/API preflight passed.', launcher)
        self.assertLess(launcher.index('export NODE_EXTRA_CA_CERTS="$CA_BUNDLE"'), launcher.index('exec bun --use-system-ca run'))
        self.assertIn('macOS CA trust bundle is missing. Rerun:', launcher)
        self.assertNotIn('rejectUnauthorized: false', launcher)

    def test_launcher_keeps_api_key_out_of_curl_arguments(self):
        script = (ROOT / "bin/start-cergea-codex").read_text(encoding="utf-8")
        self.assertIn('curl_config="$(mktemp)"', script)
        self.assertIn('chmod 600 "$response_file" "$curl_config"', script)
        self.assertIn('curl --config "$curl_config"', script)
        self.assertIn("trap 'rm -f \"$response_file\" \"$curl_config\"' EXIT", script)
        self.assertNotIn('-H "Authorization: Bearer $CERGEA_LITELLM_API_KEY"', script)
        self.assertIn('write_preflight_curl_config.py', script)

    def test_preflight_curl_config_is_private_and_does_not_print_secret(self):
        helper = TOOLS / "write_preflight_curl_config.py"
        output = self.tmp / "curl.conf"
        secret = 'synthetic-token-\\with-"quotes'
        result = subprocess.run(
            [sys.executable, str(helper), str(output)],
            text=True,
            capture_output=True,
            env={**os.environ, "CERGEA_LITELLM_API_KEY": secret},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        config = output.read_text(encoding="utf-8")
        self.assertIn('url = "https://litellm.platform.com-eng.cergea.com/v1/chat/completions"', config)
        self.assertIn("Authorization: Bearer", config)
        self.assertIn('data = "{\\"model\\":', config)
        previous_config = config
        bad = subprocess.run(
            [sys.executable, str(helper), str(output)],
            text=True,
            capture_output=True,
            env={**os.environ, "CERGEA_LITELLM_API_KEY": "bad\nkey"},
            check=False,
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotIn("bad", bad.stdout + bad.stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), previous_config, "invalid keys must not overwrite an existing private curl config")

    def test_preflight_curl_config_posts_expected_request_locally(self):
        curl = shutil.which("curl")
        if not curl:
            self.skipTest("curl is unavailable in this environment")
        received = {}
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                received["authorization"] = self.headers.get("Authorization")
                received["body"] = self.rfile.read(length).decode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            def log_message(self, *_args):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            output = self.tmp / "local-curl.conf"
            secret = 'synthetic-token-\\with-"quotes'
            writer = subprocess.run(
                [sys.executable, str(TOOLS / "write_preflight_curl_config.py"), str(output)],
                text=True, capture_output=True,
                env={**os.environ, "CERGEA_LITELLM_API_KEY": secret}, check=False,
            )
            self.assertEqual(writer.returncode, 0, writer.stderr)
            config = output.read_text(encoding="utf-8").replace(
                "https://litellm.platform.com-eng.cergea.com/v1/chat/completions",
                f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            )
            output.write_text(config, encoding="utf-8")
            output.chmod(0o600)
            result = subprocess.run(
                [curl, "--config", str(output), "--silent", "--show-error", "--connect-timeout", "2", "--max-time", "4"],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '{"ok":true}')
            self.assertEqual(received["authorization"], "Bearer " + secret)
            self.assertEqual(json.loads(received["body"]), {
                "model": "zai-glm-5",
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 8,
                "temperature": 0,
                "stream": False,
            })
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_clean_new_user_copy_only_does_not_require_or_create_config(self):
        codex_home = self.tmp / "brand-new-user" / ".codex"
        env = {**os.environ, "CODEX_HOME": str(codex_home)}
        # Run the extracted package's script while CWD is deliberately unrelated.
        result = subprocess.run([str(ROOT / "install.sh"), "--copy-only"], cwd=self.tmp,
                                text=True, capture_output=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for relative in ["install.sh", "DISTRIBUTION-MANIFEST.txt", "README.md", "LICENSE", "VERSION",
                         "THIRD-PARTY-NOTICES.md", "bin/install-cergea-codex", "bin/start-cergea-codex",
                         "bin/install-ponytail", "tools/write_preflight_curl_config.py",
                         "tests/test_runtime_contracts.py", "docs/SMOKE-TESTS.md"]:
            self.assertTrue((codex_home / relative).is_file(), relative)
        self.assertFalse((codex_home / "config.toml").exists(), "copy-only bootstrap must not overwrite/create Codex config")

        # A new user can then run the copied bootstrap from an arbitrary directory.
        second = subprocess.run(["bash", str(codex_home / "install.sh"), "--copy-only"],
                                cwd=self.tmp, text=True, capture_output=True, env=env, check=False)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertFalse((codex_home / "config.toml").exists())

    def test_shell_scripts_parse_and_bundle_has_no_personal_paths(self):
        files = distribution_files(ROOT)
        scripts = [path for path in files if path.name == "install.sh" or path.parent == ROOT / "bin"]
        for script in scripts:
            if script.exists():
                result = subprocess.run(["bash", "-n", str(script)], text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 0, f"{script}: {result.stderr}")
        for path in files:
            if path.suffix in {".pyc", ".zip"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            personal_path = "/Users/" + "pedro.ribeiro"
            self.assertNotIn(personal_path, text, f"personal path leaked into packaged file {path}")
        manifest_entries = {
            line.strip() for line in (ROOT / "DISTRIBUTION-MANIFEST.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertNotIn("config.toml", manifest_entries, "distribution must not ship a personal Codex config")

    def test_runtime_output_cap_with_bun_when_available(self):
        bun = shutil.which("bun")
        if not bun:
            self.skipTest("Bun is not installed in the test environment; macOS installer runs this test when Bun is present")
        proxy = self.tmp / "proxy"
        self.make_proxy_fixture(proxy)
        result = run_python(TOOLS / "patch_codex_context_budget.py", str(proxy))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        adapter = (proxy / "src/adapters/openai-chat.ts").read_text(encoding="utf-8")
        adapter = adapter.split("const serialized = JSON.stringify", 1)[0]
        test_file = self.tmp / "output-cap.test.ts"
        runtime_tests = "\n".join([
            'test("sets default output cap when client omits max_tokens", () => {',
            '  expect(toChatBody({}, "test/model", 16384).max_tokens).toBe(16384);',
            "});",
            'test("clamps an excessive requested output budget", () => {',
            '  expect(toChatBody({ maxTokens: 128000 }, "test/model", 16384).max_tokens).toBe(16384);',
            "});",
            'test("preserves a smaller requested output budget", () => {',
            '  expect(toChatBody({ maxTokens: 2048 }, "test/model", 16384).max_tokens).toBe(2048);',
            "});",
            'test("uses a model-specific cap", () => {',
            '  expect(toChatBody({ maxTokens: 128000 }, "test/model", 4096).max_tokens).toBe(4096);',
            "});",
        ])
        test_file.write_text('import { expect, test } from "bun:test";\n' + 'type ParsedRequest = { maxTokens?: number };\n' + adapter + '\n' + runtime_tests, encoding="utf-8")
        run = subprocess.run([bun, "test", str(test_file)], text=True, capture_output=True, check=False, cwd=self.tmp)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_runtime_history_guard_with_bun_when_available(self):
        bun = shutil.which("bun")
        if not bun:
            self.skipTest("Bun is not installed in the test environment; macOS installer runs this test when Bun is present")
        module = load_module(TOOLS / "patch_codex_history_budget.py", "history_budget_module")
        runtime_test = self.tmp / "context-guard.test.ts"
        prefix = r'''import { expect, test } from "bun:test";
type ContentPart = { type: "text"; text: string } | { type: "image"; url: string };
type ToolCall = { name: string; arguments: string; id?: string };
type ToolMessage = { role: "tool"; content: string; name?: string };
type PlainMessage = { role: "user" | "system"; content: ContentPart[] };
type AssistantMessage = { role: "assistant"; content: ContentPart[]; toolCalls?: ToolCall[] };
type CergeaMessage = ToolMessage | PlainMessage | AssistantMessage;
type ParsedRequest = { messages: CergeaMessage[]; tools: Array<{ name: string; [key: string]: unknown }>; compactionV2?: boolean; [key: string]: unknown };
'''
        suffix = r'''
export { boundCergeaHistory };
let capturedLogs: string[] = [];
console.info = (...args: unknown[]) => { capturedLogs.push(args.map(String).join(" ")); };

test("tool output stays inside aggregate/per-result budgets and keeps message slots", () => {
  const source = Array.from({ length: 40 }, (_, i) => ({ role: "tool" as const, name: "shell", content: `SECRET_${i}_` + "x".repeat(25000) }));
  const user = { role: "user" as const, content: [{ type: "text" as const, text: "keep this user request exactly" }] };
  const parsed: ParsedRequest = { messages: [user, ...source], tools: [{ name: "shell", parameters: { type: "object" } }] };
  const bounded = boundCergeaHistory(parsed, "fixture/model");
  const toolMessages = bounded.messages.filter((m) => m.role === "tool");
  expect(toolMessages.length).toBe(source.length);
  expect(toolMessages.reduce((n, m) => n + (m.role === "tool" ? m.content.length : 0), 0)).toBeLessThanOrEqual(48000);
  expect(Math.max(...toolMessages.map((m) => m.role === "tool" ? m.content.length : 0))).toBeLessThanOrEqual(12000);
  expect(JSON.stringify(bounded.messages[0])).toBe(JSON.stringify(user));
  expect(capturedLogs.join(" ")).not.toContain("SECRET_0_");
});

test("assistant text and tool arguments are bounded and retained arguments stay valid JSON", () => {
  const hugeCall = { name: "exec", arguments: JSON.stringify({ command: "x".repeat(25000) }), id: "call-1" };
  const parsed: ParsedRequest = { messages: [
    { role: "user", content: [{ type: "text", text: "preserve me" }] },
    ...Array.from({ length: 8 }, (_, i) => ({ role: "assistant" as const, content: [{ type: "text" as const, text: `assistant-${i}-` + "a".repeat(12000) }], toolCalls: [{ ...hugeCall, id: `call-${i}` }] })),
  ], tools: [{ name: "exec" }] };
  const bounded = boundCergeaHistory(parsed, "fixture/model");
  const assistants = bounded.messages.filter((m) => m.role === "assistant");
  const textChars = assistants.reduce((sum, m) => sum + (m.role === "assistant" ? m.content.reduce((n, p) => n + (p.type === "text" ? p.text.length : 0), 0) : 0), 0);
  expect(textChars).toBeLessThanOrEqual(24000);
  for (const msg of assistants) if (msg.role === "assistant") for (const call of msg.toolCalls ?? []) {
    expect(call.arguments.length).toBeLessThanOrEqual(4000);
    expect(() => JSON.parse(call.arguments)).not.toThrow();
  }
});

test("explicit compaction requests bypass lossy history trimming", () => {
  const parsed: ParsedRequest = { compactionV2: true, messages: [{ role: "tool", content: "x".repeat(100000) }], tools: [] };
  const bounded = boundCergeaHistory(parsed, "fixture/model");
  expect(bounded).toBe(parsed);
  expect((bounded.messages[0] as ToolMessage).content.length).toBe(100000);
});
'''
        inject = module.INJECT.replace("function boundCergeaHistory(", "function boundCergeaHistory(")
        # Insert the real current injected code, then export the function for synthetic runtime assertions.
        runtime_test.write_text(prefix + inject + suffix, encoding="utf-8")
        result = subprocess.run([bun, "test", str(runtime_test)], text=True, capture_output=True, check=False, cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
