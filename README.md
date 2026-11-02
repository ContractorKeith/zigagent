# zigagent

A small native Zig CLI being built to supervise an installed Codex for repository fixes.

M0 and M1 merged via [PR #6](https://github.com/ContractorKeith/zigagent/pull/6) and [PR #7](https://github.com/ContractorKeith/zigagent/pull/7). This branch delivers M2: terminal-only official login, graceful cancellation, owned descendant cleanup and finite input/output waits. Codex **0.166.0** and ChatGPT login are required. Caller checks remain explicitly unimplemented in M3; `--check` fails before any backend starts. Release evidence remains M4; see [the plan](docs/PLAN.md).

## Build and test

On newer macOS SDKs, pinned Zig may need an installed compatible SDK selected for the build process; see [SDK setup](docs/TESTING.md#macos-sdk-compatibility). No system configuration change is needed.

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

## Run

```bash
./zig-out/bin/zigagent run --help
./zig-out/bin/zigagent login --help
./zig-out/bin/zigagent run --model gpt-6.1-sol --json 'Fix the parser'
# One schema-version-1 result; exit 0 only on completion plus backend exit zero.
printf '%s' 'Fix the parser' | ./zig-out/bin/zigagent run --model gpt-6.1-sol --json --no-input -
```

`--model` overrides `ZIGAGENT_MODEL`; missing/empty models fail usage. Values are separate arguments, not `--flag=value`. `--` ends run option parsing. Workspace and additional-directory paths resolve from the caller's current directory. Invalid arguments exit 2, with one JSON envelope when requested. Help/version need no backend or credentials.

Omitted/`-` prompts read nonterminal stdin under the preflight deadline, capped at 1 MiB. An argument prompt leaves caller stdin untouched. All prompts reach Codex through a separate stdin pipe; model/path values are literal argv data. Invalid UTF-8 and NUL prompt bytes fail usage. Preflight shares one `--timeout` budget; authenticated execution receives a fresh full budget. Summaries retain the last completed agent message's prefix; diagnostics retain a bounded stderr tail. Truncation flags identify loss; invalid/cut UTF-8 bytes become `?`.

Missing login starts official `codex login` only when a controlling terminal exists and `--no-input` is absent. Login output goes to that terminal, never JSON stdout; `--login-timeout` separately bounds login and the following ChatGPT auth verification. `zigagent login` uses that same bounded flow. Unattended callers receive `authentication_required`; API-key login and unrelated status failures return `authentication_failed` without launching login. A mutating run is never retried.

SIGINT/SIGTERM cancel with exits 130/143; deadline expiration returns 124. Owned groups receive TERM, then KILL after one second (100ms following ordinary leader exit), before the leader is reaped. Cleanup drains/reaps for at most three seconds total. Descendants retaining pipes or closing them cannot hold normal completion indefinitely. Closed caller stdout stops owned work; final output writes each have a two-second bound. Deliberately detached processes and uninterruptible OS waits remain outside cleanup guarantees. All edits remain on failure. [Backend controls and configuration limits](docs/CODEX-BACKEND.md) describe the exact invocation.

Subcommand `--help` stops parsing immediately; trailing arguments are ignored, while errors before it still fail. Option values beginning with `--` are treated as missing values: use `./--context` or an absolute path for a directory named `--context`. Every repeated `--add-dir` is validated.

The backend is a separately installed Codex with ChatGPT subscription login. Codex owns the agent loop. The caller supplies OS isolation; working directories and added context paths do not enforce an access boundary. See the [glossary](CONTEXT.md).
