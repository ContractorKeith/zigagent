# zigagent

A small native Zig CLI being built to supervise an installed Codex for repository fixes.

M0 implements the build, argument validation, result schema, help/version and fake-backend test harness. **Backend execution and login are unimplemented**: a valid `run` or `login` exits 1 with `unimplemented`. No model calls, authentication, caller checks, prompt stdin reading, deadlines or subprocess supervision run yet. M1–M4 deliver those features in [the plan](docs/PLAN.md); this is not a working supervisor release.

## Build and test

Requires Python 3 for tests/toolchain setup and Zig **0.15.2** for builds. The native binary has no Python dependency.

```bash
# Official archives, pinned SHA256, Linux x86_64 or macOS arm64:
toolchain=$(bash scripts/install-zig.sh)
export PATH="$toolchain:$PATH"
bash scripts/accept.sh
./zig-out/bin/zigagent --help
./zig-out/bin/zigagent --version
```

The installer writes only to `~/.local/share/zigagent-toolchains` (or its explicit directory argument). The gate runs format checking, unit tests, build and compiled-process black-box tests, and is the same entrypoint CI runs on both target hosts. See [testing](docs/TESTING.md).

## M0 CLI

```bash
./zig-out/bin/zigagent run --help
./zig-out/bin/zigagent login --help
./zig-out/bin/zigagent run --model gpt-6.1-sol --json 'Fix the parser'
# One failed schema-version-1 envelope with error.code="unimplemented"; exit 1.
```

Run flags, numeric bounds and directory paths are validated before the placeholder failure. `--model` overrides `ZIGAGENT_MODEL`; missing/empty models fail usage. Values are separate arguments, not `--flag=value`. `--` ends run option parsing. Relative workspace and additional-directory paths resolve from the caller's current directory. Invalid arguments exit 2, with one JSON envelope when `--json` is requested, or a plain stderr error. Help/version need no Codex or credentials. Omitted/`-` prompts select the future stdin source without reading it in M0; argument prompts are limited to 1 MiB. Invalid UTF-8 arguments are rejected, preserving valid JSON output. M0 uses the extra temporary error code `unimplemented`; the v1 error contract remains in the unchanged [spec](docs/features/supervisor/SPEC.md).

Subcommand `--help` stops parsing immediately; trailing arguments are ignored, while errors before it still fail. Option values beginning with `--` are treated as missing values: use `./--context` or an absolute path for a directory named `--context`. Every repeated `--add-dir` is validated.

The eventual backend is a separately installed Codex with ChatGPT subscription login. Codex owns the agent loop. The caller supplies OS isolation; working directories and added context paths do not enforce an access boundary. See the [glossary](CONTEXT.md).
