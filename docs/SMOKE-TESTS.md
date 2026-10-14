# Smoke tests

Use a disposable empty workspace and a **new Codex conversation**. Select `cergea/zai-glm-5`. For every test, verify Codex actually uses tools; a plausible answer without tool execution is not a pass.

## Before testing: verify history guard

Keep the proxy terminal visible. Each request logs `[cergea-proxy request-size]`; after it, look for `[cergea-proxy context-shape]`. For a very large tool result, `originalMessageChars` should be much larger than `boundedMessageChars` and `truncated` should be `true`. Logs intentionally include lengths/counts but no prompt/tool contents or API keys.

## 1. Mistral tool-call fallback

Select `cergea/mistral-mixtral-8x7b-instruct` and ask Codex to run `python3 -c 'print(6 * 7)'`.

**Pass:** the proxy logs `[cergea-proxy tool-compat] Routed cergea/mistral-mixtral-8x7b-instruct to cergea/zai-glm-5` and the terminal tool actually runs. Mistral Mixtral 8x7B on Bedrock does not support client-side tool calling, so agentic requests must use the configured tool-capable fallback.

## 2. One terminal tool call

> Use your terminal tool to execute this command; do not calculate the result mentally:
>
> `python3 -c 'print(6 * 7)'`
>
> Report the exact command executed and its output. Do not create or modify any files.

**Pass:** the terminal is invoked and returns `42`.

## 3. Sequential calls and observed output

> Use your terminal tool to perform these steps:
>
> 1. Create a unique temporary directory using `mktemp -d`.
> 2. Write `sample.txt` inside it containing exactly three lines: `alpha`, `beta`, and `gamma`.
> 3. In a separate terminal tool call, read the file and verify exact line order and count.
> 4. Remove only the temporary directory you created.
>
> Report the verification result. Do not skip actual tool calls.

**Pass:** the second call reads/validates the file, then the correct temporary directory is removed.

## 4. File edit, execution, and correction

> In the current disposable workspace:
>
> 1. Create `smoke_test.py` with `add(a, b)` and an assertion that `add(19, 23) == 42`.
> 2. Run it using your terminal tool.
> 3. Change the assertion to `add(19, 24) == 42` and run it again.
> 4. Explain why the second run fails, restore the correct assertion, and rerun it.
> 5. Show the final file contents.

**Pass:** first run passes, the deliberately incorrect assertion fails, and the restored version passes.

## 5. Multi-turn continuity

In a separate message in the **same conversation**:

> Without recreating the file, use your terminal tool to run `smoke_test.py` again and report its result. Then add an assertion that `add(20, 22) == 42`, run the updated test, and show the final file contents.

**Pass:** Codex reuses the file, executes it, edits it, and verifies the new assertion.

## 6. Large-output handling (safe, synthetic)

> In a temporary directory, create a text file with 20,000 lines, each containing a short unique line number and the word `synthetic`. Do not print the full file. Use your terminal tool to report only the line count, first two lines, and last two lines. Then summarize the output in under 100 words.

**Pass:** Codex uses tools, avoids dumping the entire file into the chat, reports the correct counts/edges, and completes without a context-window error. Inspect the proxy `context-shape` line for trimming if an intermediate tool result is huge. Clean up only the temporary file/directory you created.

## 7. Ponytail A/B test (if installed)

Repeat a small coding task twice in fresh threads: once with Ponytail off (`/ponytail off`), once with `/ponytail lite`. Compare correctness, code added, number of tool calls, and request-size diagnostics. Ponytail is a behavior prompt; it is not expected to reduce pre-existing tool output. Keep it enabled only if the trade-off is good for your work.

## If a test fails

Record the test number, exact error, selected model, and adjacent proxy diagnostics. Redact API keys, authorization headers, private prompts, and file contents. Do not paste raw request bodies.
