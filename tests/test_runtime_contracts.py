#!/usr/bin/env python3
"""Additional regression tests for behavior that must survive real TypeScript execution.

These use the actual injected source fragments from the packager's patchers. They run
under Bun on target Macs; they are skipped only when developers run the suite elsewhere
without Bun (the installer itself requires Bun).
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def distribution_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Inspect package-owned files only; ~/.codex also contains user files/backups."""
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


class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cergea-runtime-contract-")
        self.tmp = pathlib.Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_bun(self, name: str, source: str):
        bun = shutil.which("bun")
        if not bun:
            self.skipTest("Bun is not installed here; the macOS installer requires Bun and runs this test")
        path = self.tmp / name
        path.write_text(source, encoding="utf-8")
        result = subprocess.run([bun, "test", str(path)], text=True, capture_output=True, check=False, cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_long_tool_name_alias_runtime_contract(self):
        patcher = load_module(TOOLS / "patch_codex_proxy.py", "proxy_tool_alias_contract")
        helper = patcher.REPLACEMENTS[1][1]
        helper = helper[helper.index("// CERGEA BEDROCK COMPATIBILITY PATCH"):]
        source = (
            'import { createHash } from "node:crypto";\n'
            'import { expect, test } from "bun:test";\n'
            + helper
            + r'''

test("long names are stable, within Bedrock's limit, and reversible", () => {
  const original = "mcp__filesystem__search_files_with_complex_filters_".repeat(3);
  const alias = upstreamToolName(original);
  expect(alias.length).toBeLessThanOrEqual(64);
  expect(alias).toMatch(/^cpx_[a-f0-9]{40}$/);
  expect(upstreamToolName(original)).toBe(alias);
  expect(codexToolName(alias)).toBe(original);
  expect(upstreamToolName("shell")).toBe("shell");
});
'''
        )
        self.run_bun("tool-alias-runtime.test.ts", source)

    def test_assistant_prefill_runtime_contract(self):
        patcher = load_module(TOOLS / "patch_codex_proxy.py", "proxy_prefill_contract")
        replacement = patcher.REPLACEMENTS[-1][1]
        prefill = replacement[replacement.index("const lastMessage"):replacement.index("\n\n  const body:")]
        source = (
            'import { expect, test } from "bun:test";\n'
            + 'function normalize(messages: Array<{ role: string; tool_calls?: unknown[]; content?: string }>) {\n'
            + prefill + '\n  return messages;\n}\n'
            + r'''
test("plain assistant prefill gets one continuation user message", () => {
  const messages: Array<{ role: string; tool_calls?: unknown[]; content?: string }> = [
    { role: "user" }, { role: "assistant" },
  ];
  normalize(messages);
  expect(messages).toHaveLength(3);
  expect(messages[2]).toEqual({ role: "user", content: "Continue from the last assistant message." });
});

test("pending assistant tool calls are not followed by a fabricated user turn", () => {
  const messages = [{ role: "assistant", tool_calls: [{ id: "call-1" }] }];
  normalize(messages);
  expect(messages).toHaveLength(1);
});

test("non-assistant final messages remain unchanged", () => {
  const messages = [{ role: "user" }];
  normalize(messages);
  expect(messages).toEqual([{ role: "user" }]);
});
'''
        )
        self.run_bun("assistant-prefill-runtime.test.ts", source)

    def test_zstd_parser_runtime_contract(self):
        patcher = load_module(TOOLS / "patch_codex_request_zstd.py", "proxy_zstd_contract")
        source = (
            'import { expect, test } from "bun:test";\n'
            + patcher.NEW
            + r'''

test("decodes valid zstd request JSON", async () => {
  const payload = { model: "cergea/zai-glm-5", input: "synthetic request" };
  const compressed = Bun.zstdCompressSync(JSON.stringify(payload));
  const request = new Request("http://127.0.0.1/v1/responses", {
    method: "POST", headers: { "content-encoding": "zstd" }, body: compressed,
  });
  expect(await readJson(request)).toEqual(payload);
});

test("keeps plain JSON requests working", async () => {
  const payload = { input: "plain" };
  const request = new Request("http://127.0.0.1/v1/responses", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  expect(await readJson(request)).toEqual(payload);
});

test("fails with stable messages for malformed JSON and invalid zstd", async () => {
  const malformed = new Request("http://127.0.0.1/v1/responses", { method: "POST", body: "{bad" });
  await expect(readJson(malformed)).rejects.toThrow("Request body is not valid JSON");
  const invalidCompressed = new Request("http://127.0.0.1/v1/responses", {
    method: "POST", headers: { "content-encoding": "zstd" }, body: new Uint8Array([1, 2, 3, 4]),
  });
  await expect(readJson(invalidCompressed)).rejects.toThrow("Could not decompress zstd-encoded request body");
});
'''
        )
        self.run_bun("zstd-parser-runtime.test.ts", source)

    def test_history_guard_prefers_recent_results_and_keeps_image_parts(self):
        patcher = load_module(TOOLS / "patch_codex_history_budget.py", "proxy_history_recency_contract")
        prefix = r'''import { expect, test } from "bun:test";
type ContentPart = { type: "text"; text: string } | { type: "image"; url: string };
type ToolCall = { name: string; arguments: string; id?: string };
type ToolMessage = { role: "tool"; content: string; name?: string };
type PlainMessage = { role: "user" | "system"; content: ContentPart[] };
type AssistantMessage = { role: "assistant"; content: ContentPart[]; toolCalls?: ToolCall[] };
type ParsedRequest = { messages: (ToolMessage | PlainMessage | AssistantMessage)[]; tools: Array<{ name: string; [key: string]: unknown }>; compactionV2?: boolean; [key: string]: unknown };
'''
        tests = r'''
export { boundCergeaHistory };
console.info = () => {};

test("keeps newest tool outputs first, retains message slots, and preserves user/system messages", () => {
  const system = { role: "system" as const, content: [{ type: "text" as const, text: "SYSTEM_KEEP_" + "s".repeat(50000) }] };
  const user = { role: "user" as const, content: [{ type: "text" as const, text: "USER_KEEP" }] };
  const source = Array.from({ length: 10 }, (_, i) => ({ role: "tool" as const, name: "shell", content: `RESULT_${i}_` + String(i).repeat(9990) }));
  const parsed: ParsedRequest = { messages: [system, user, ...source], tools: [] };
  const bounded = boundCergeaHistory(parsed, "fixture/model");
  expect(JSON.stringify(bounded.messages[0])).toBe(JSON.stringify(system));
  expect(JSON.stringify(bounded.messages[1])).toBe(JSON.stringify(user));
  const tools = bounded.messages.filter((m) => m.role === "tool") as ToolMessage[];
  expect(tools).toHaveLength(10);
  for (let i = 6; i < 10; i++) expect(tools[i].content).toBe(source[i].content);
  expect(tools[5].content).toContain("local Cergea proxy omitted");
  for (let i = 0; i < 5; i++) expect(tools[i].content).toBe("");
  expect(tools.reduce((n, m) => n + m.content.length, 0)).toBeLessThanOrEqual(48000);
});

test("does not rewrite user image parts while trimming historic tool text", () => {
  const image = { type: "image" as const, url: "data:image/png;base64,synthetic" };
  const parsed: ParsedRequest = { messages: [
    { role: "user", content: [image] },
    { role: "tool", content: "x".repeat(100000) },
  ], tools: [] };
  const bounded = boundCergeaHistory(parsed, "fixture/model");
  expect(JSON.stringify(bounded.messages[0])).toBe(JSON.stringify(parsed.messages[0]));
});
'''
        source = prefix + patcher.INJECT + tests
        self.run_bun("history-recency-runtime.test.ts", source)

    def test_fresh_install_has_no_embedded_personal_paths_or_key(self):
        for path in distribution_files(ROOT):
            if "tests" in path.relative_to(ROOT).parts:
                continue
            if path.suffix in {".pyc", ".zip"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            self.assertNotIn("/Users/" + "pedro.ribeiro", text, str(path))
            self.assertNotIn("sk-ant-", text, str(path))
            self.assertNotIn("DO_NOT_" + "KEEP", text, str(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
