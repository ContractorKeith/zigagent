# zigagent supervisor v1

## Problem statement

Scripts need a reliable way to ask an installed coding agent to make a small repository fix and determine whether it finished, passed a supplied check, failed, timed out, or was cancelled. Backend event streams and login behavior should not leak into the caller's output contract. The project also teaches readable Zig through real process and protocol work.

## Solution

A native Zig CLI starts an installed Codex using the caller's ChatGPT subscription, supervises its lifecycle, and emits plain text or exactly one versioned JSON result. A run is independent and may optionally execute a caller check after Codex completes. No automatic repair or retry follows a failed run or check. Codex is an explicit external dependency.

## User stories

1. A developer passes a prompt and explicit model to fix a scratch repository and receives a concise result.
2. A script pipes a prompt on stdin, uses --json --no-input, and can distinguish agent completion from verification.
3. A user with missing login can sign in through the official Codex flow when a controlling terminal exists; unattended callers receive a clear error instead of hanging.
4. A caller supplies --check; its exit status decides verification, independently of anything the agent claims.
5. A caller cancels or sets a deadline; ordinary subprocess descendants stop, edits remain, and the result names the cause.
6. A verbose or malformed backend cannot grow zigagent's retained output without bound or corrupt JSON stdout.
7. A user with unsupported or missing Codex gets an actionable error before an agent starts.
8. A maintainer tests without a model or credentials, then proves the release on actual Linux/macOS hosts with the subscription-backed backend.

## Implementation decisions

### Ownership and dependencies

- Zig 0.15.2, standard library and OS libc for portable POSIX process facilities if needed. No application framework or third-party runtime. libc is justified by process groups, polling and signals shared by the target OSes.
- Codex owns model requests, tool execution, instruction discovery and managed policy. No custom file tools, root-only AGENTS promise, model-turn cap, per-tool timeout, or backend memory cap.
- zigagent owns argument validation, subprocess supervision, parsing backend JSONL, bounded retention, caller checks and final formatting. Keep backend-specific translation separate from lifecycle supervision and result rendering.
- Initial supported Codex range is >=0.166.0 and <0.166.1 (the installed version). Widen only with recorded fixture/live compatibility evidence. Recognize version output strictly; reject prerelease/unrecognized versions unless specifically tested.
- Reuse Codex's official login; never parse, copy or expose its credential files. Require ChatGPT authentication rather than silently switching to API billing. Inspect `codex login status` through a bounded subprocess; login status errors are not all equivalent to logged out.
- Invoke `codex exec` with explicit model, JSONL, ephemeral mode, no color, working directory, controlled optional config and no approval/sandbox prompts where managed policy permits. Confirm available switches against the supported version. Optional personal config/hooks/plugins should be excluded where possible; document precisely what cannot be suppressed. Never rewrite the user's Codex config. Managed policy is not bypassed.
- Caller owns OS isolation. Workspace and added context directories do not restrict shell access. Additional context directories must be validated and supplied as explicit context without advertising containment.
- Do not execute task-bearing live Codex calls during unit/integration CI; the fake executable is the test seam.

### CLI contract

```
zigagent run [options] [PROMPT|-]
zigagent login [--login-timeout SECONDS] [--no-input]
zigagent --help
zigagent --version
```

Run options (flags after `run`; `--` ends option parsing):

| Flag | Meaning | Default |
|---|---|---|
| --model NAME | Explicit model; environment ZIGAGENT_MODEL fallback | required |
| --workspace PATH | Working directory | current directory |
| --add-dir PATH | Repeatable additional context directories | none |
| --check COMMAND | Caller check through /bin/sh -c in workspace | absent |
| --json | Exactly one final result on stdout | plain text |
| --no-input | Disable login interaction even with a terminal | false |
| --timeout SECONDS | Shared backend/check execution deadline | 600 |
| --login-timeout SECONDS | Separate login deadline | 300 |
| --output-limit BYTES | Per retained summary/diagnostic/check-output buffer | 65536 |
| --event-limit BYTES | Maximum individual backend JSONL event | 1048576 |
| --codex PATH | Backend executable (test seam and alternate install) | `codex` through PATH |

Positive integer limits only, checked for overflow. Reject values above 86400 seconds, 16777216 retained bytes, or 16777216 event bytes; no unlimited sentinel. Prompt input is capped at 1 MiB. A prompt is one positional argument; `-` or an omitted prompt reads stdin only when stdin is nonterminal, otherwise fail usage instead of waiting for interactive task input. Supplying a prompt argument does not also consume piped stdin. Empty prompts, missing model, unknown options, invalid directories and invalid numeric options fail before spawning Codex. Flags override environment; only ZIGAGENT_MODEL is app configuration in v1, no config file. `--help` and `--version` need no backend or credentials. Subcommand --help lists its supported options. Plain output has no color/animations, therefore respects NO_COLOR and TERM=dumb naturally.

Preflight and waiting for prompt input must also be finite: bound prompt/preflight operations with the configured timeout; execution gets its own full timeout after authentication. All child probes receive a finite deadline and output limit. Login status, version and configuration checks must never indefinitely block a run.

Examples:

```
zigagent run --model gpt-6.1-sol "Fix the failing unit test"
zigagent run --model gpt-6.1-sol --workspace ./repo --check 'zig build test' --json "Fix the parser"
printf '%s\n' 'Correct the off-by-one bug' | zigagent run --model gpt-6.1-sol --json --no-input -
zigagent run --model gpt-6.1-sol --timeout 120 --check 'python3 -m unittest' 'Fix the test'
zigagent login --login-timeout 300
```

### Authentication and lifecycle

State progression: validate -> backend/version preflight -> auth preflight -> optional login -> execute agent -> optional check -> result. Help/version skip preflight. An explicit login only invokes the official login flow, under the login deadline.

When login is required, --no-input or no controlling terminal fails with authentication_required. Otherwise connect login stdin to the controlling terminal, direct its output to the terminal/stderr (never result stdout), and wait at most the separate login timeout. Check authentication again before execution. Do not launch a browser/login for unrelated auth-status failures. Login cancellation does not begin an agent run. A mid-run auth failure is reported; never restart a run that may have changed files.

Once authenticated, start a monotonic execution deadline shared by Codex and the check. Check only after valid agent completion and successful backend exit. If the deadline is already exhausted, verification is not_run and result timed_out. Check commands use /bin/sh -c with stdin closed, no interactive approval, and the same workspace. Agent prompts/model/path arguments are passed as argv, never interpolated into a shell command. Only the caller's explicit --check is shell syntax.

Use a dedicated process group for each owned child workload. SIGINT and SIGTERM request cancellation; timeout requests termination. Stop the group, wait up to two seconds, then force-stop remaining ordinary descendants. Drain/reap with bounded cleanup and avoid signaling a recycled PID/process-group id. Ordinary descendants retaining pipes must not hang completion. Deliberately detached processes, SIGKILL of zigagent, and host failure are outside cleanup guarantees. Do not signal unrelated processes. Preserve all edits, even on check failure/cancellation. No automatic git commits, rollback, worktrees, sessions or retries by zigagent.

### Result schema and exits

Version 1 result fields:

- schema_version: 1
- status: completed | failed | timed_out | cancelled
- summary: string (possibly truncated, UTF-8 valid)
- verification: object with status not_requested | not_run | passed | failed, exit_code integer or null, output string, truncated boolean
- elapsed_ms: nonnegative integer, total elapsed including login
- error: null or object {code, message}; stable machine code, bounded human message
- diagnostics: {output: string, truncated: boolean} for retained backend/probe stderr
- summary_truncated: boolean
- backend: {name: "codex", version: string or null, model: string or null}

Success means the backend emitted a recognized completion and exited zero; when a check is supplied it also passed. Agent success without --check is completed with verification not_requested, never passed. Backend failure with a check is verification not_run. Missing/invalid completion, malformed JSON, oversized event, or nonzero backend exit cannot be success even if the agent text says it is. Tolerate unknown event types/extra fields within the tested protocol while preserving framing and limits. Bound partial lines, drain stdout/stderr concurrently, and keep serialized output bounded by retained buffer sizes. Truncated UTF-8 must remain valid; arbitrary diagnostics bytes must be safely encoded/replaced. If stdout closes, terminate owned workload and exit without pretending a result was delivered.

Exit codes: 0 completed; 1 agent/backend/protocol/internal failure; 2 usage; 3 missing/incompatible backend or unsupported required capability; 4 authentication failure/required; 5 caller check failure; 124 timeout (including login timeout); 130 SIGINT cancellation; 143 SIGTERM cancellation. JSON errors follow the same envelope when --json was requested, including validation errors, except help/version or an unwritable stdout. Error codes distinguish usage_error, backend_missing, backend_incompatible, backend_capability, authentication_required, authentication_failed, backend_failed, protocol_error, event_too_large, check_failed, timed_out, cancelled and output_closed as applicable. A later milestone may refine codes only with schema/documentation/tests updated together before release.

### Resource accounting

Retain bounded summaries and tails of stderr/check output; use explicit truncation markers/flags. Drain all streams to avoid pipe deadlocks. The per-event limit is an input bound, not permission to retain every event. Finite execution plus bounded buffers are the guarantee; Codex memory, model context and token cost are not capped by zigagent. Measure wrapper binary size/startup/peak RSS separately from the Codex process tree and derive regression thresholds from reproducible baselines.

## Testing decisions

The highest seam is the compiled CLI process, invoked with a configurable fake Codex executable in disposable repositories. Python 3 is allowed for portable test drivers/PTY fixtures, never required to run the shipped binary. Fake backend covers argv, credentials-status text/exit variations, event framing, stderr saturation, slow input, invalid UTF-8, missing completion, nonzero exits, signals, descendants holding pipes, output overflow, auth without terminal, and terminal login using a PTY. Tests never touch real credential files or user repositories. Capture only synthetic fixture data.

Canonical gate: scripts/accept.sh runs formatting, unit tests, build, black-box fixtures and docs/contract checks as appropriate to the landed milestone. CI runs that exact entrypoint on Linux x86_64 and macOS arm64. Each feature has positive and negative assertions. Confirm a representative regression test fails before fixing any review finding. Keep tests deterministic; timers use generous but bounded tolerances.

Before release, run real subscription-backed scratch repository fix + caller check on each target host, record exact model/Codex/build version, verify resulting edit and check output. Validate packaged executable, checksum, archive paths and version on each host. Fresh independent reviewer and attack pass per PR; independent release skeptic per platform. Record findings in GitHub and reports in central worklog. Do not tag until tests, both live checks and release skeptic pass.

## Out of scope

Own HTTP/model adapter or agent loop, ACP, shared-library/WASM integration, saved conversation/resume, streaming public JSONL, TUI, model fallback, automatic repair or rollback, native OS sandbox, hard backend memory/context/tool limits, Windows, Linux arm64, Intel macOS, Homebrew, auto-update, telemetry.

## Further notes

The user approved this scope through the grill and authorized autonomous spec/tickets/build on 2026-11-02. No further approval checkpoint is required for routine implementation, review, publishing the repo, or release. Material contradictions must be surfaced rather than silently changing scope.

References: [grill record](https://github.com/ContractorKeith/worklog/blob/main/reports/zigagent-grill-2026-11-02.md), [process](https://app.basecamp.com/6307587/buckets/49448999/documents/10464058936), [Codex authentication](https://learn.chatgpt.com/docs/auth), [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode). Installed Codex 0.166.0 exec/login help inspected 2026-11-02. Official Zig download index confirms 0.15.2 artifacts/checksums. No account-secret contents were read.
