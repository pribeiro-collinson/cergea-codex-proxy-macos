# Ponytail integration

Ponytail is an optional third-party Codex plugin: <https://github.com/DietrichGebert/ponytail>.

## What it contributes

Ponytail encourages an agent to inspect existing code, reuse what is already available, avoid unnecessary dependencies/abstractions, and keep changes focused with tests for risky logic. That can reduce unnecessary code and tool output on coding tasks.

It is **not** a request compressor. Its instruction prompt/hooks may add some input context, and it does not shrink large historical tool results already in a conversation. The proxy's history budget is the direct guard against oversized carried-forward outputs; Ponytail is complementary.

## Install

During `./install.sh`, answer `y` to opt in to the optional installation prompt (press Enter or `n` to skip), or later run:

```bash
~/.codex/bin/install-ponytail
```

The helper requires Node.js on `PATH`; the Ponytail lifecycle hooks use Node.js. It first uses `codex` on `PATH`, then checks `CODEX_CLI_PATH` in `~/.codex/config.toml`, and finally checks standard ChatGPT Desktop application paths. This lets it use the CLI bundled with ChatGPT even when it is not exposed as a shell command. It executes the official project's documented Codex CLI commands:

```bash
codex plugin marketplace add DietrichGebert/ponytail
codex plugin add ponytail@ponytail
```

If no CLI is detected, set `CODEX_CLI_PATH` to the absolute path of the Codex CLI executable and rerun the helper. If you have a standalone CLI installed, putting it on `PATH` also works. After installation:

1. Open Codex and run `/hooks`.
2. Review and trust Ponytail's two lifecycle hooks.
3. Start a new thread.
4. Use `/ponytail lite` initially, and compare behavior with the plugin off if token usage/quality changes unexpectedly.

The bundle does not copy or vendor Ponytail's source; it installs from the project's official GitHub marketplace after your explicit confirmation. The upstream plugin can change independently of this bundle, so review/trust its hooks in Codex before using it.

## Remove

Run:

```bash
codex plugin remove ponytail
```

Then follow the plugin's current uninstall instructions at the official repository if you want to remove the plugin's remaining state as well.
