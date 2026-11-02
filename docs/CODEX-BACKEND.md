# Codex 0.166.0 backend contract (M3)

Evidence inspected on Linux x86_64, 2026-11-02: `codex --version` returned
`codex-cli 0.166.0`; `codex --help`, `codex exec --help` and `codex features list`
provided the switches/features below. `codex login status` returned
`Logged in using ChatGPT` on stderr, exit 0. No credential files were read and
no task-bearing live request was made.

Official sources: [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
and [authentication](https://learn.chatgpt.com/docs/auth). Installed help is the
version-specific evidence; online docs can change independently. Compatibility
is intentionally pinned to >=0.166.0 and <0.166.1, excluding prereleases.

## Invocation and authentication

The wrapper performs `--version`, `exec --help`, then `login status`, each with
stdin closed, finite output retention and the shared preflight deadline.
Required help switches must be present before authentication/task execution.
ChatGPT status must match the tested text and exit zero. Logged-out text plus
nonzero exit is recognized as logged out; API-key status and other probe
failures produce authentication_failed and never start login. Only recognized
logged-out status may start official `codex login`, with controlling-terminal
stdin and output relayed to that terminal, never result stdout. `--no-input`
or no controlling terminal returns authentication_required. Login and the
post-login ChatGPT status probe share a separate `--login-timeout` budget.
Explicit `zigagent login` performs only that flow and verification, without
version/capability probes or a task. API-key environment overrides are removed
from login children as well as probes and exec. zigagent never reads credentials
or user config.
The terminal is temporarily assigned to login's owned process group, then its
previous foreground group is restored. Closed caller stdin is supported: terminal handles stay above standard descriptors and child setup temporarily reserves the stdin slot. Closed stdout stops login before it starts. Login signal termination and handled exits 130/143 both map to cancellation. Terminal output relay is nonblocking;
a saturated terminal may lose login chatter rather than block supervision.

A task uses these argv elements, followed by repeatable `--add-dir ABS_PATH`
and a final `-`. The prompt goes through a separate stdin pipe and is closed
when fully written. This avoids both OS argv size limits and Codex's documented
behavior of appending piped stdin when given an argument prompt.

```
exec --json --ephemeral --color never --ignore-user-config --ignore-rules
--dangerously-bypass-approvals-and-sandbox
-c forced_login_method="chatgpt"
--disable hooks --disable plugins --disable apps --disable memories
--model MODEL --cd ABS_WORKSPACE [--add-dir ABS_PATH ...] -
```

Quotes in the config element are literal TOML string delimiters. Every element
is passed directly to the executable; no shell parses model, prompt or paths.
Workspace/context paths are canonicalized from the caller's directory. The
wrapper removes OPENAI_API_KEY and CODEX_API_KEY only in each child's environment
and forces ChatGPT mode on exec, preventing API billing override after the
status probe. Other environment values are inherited.

## Configuration limits

- `--ignore-user-config` skips `$CODEX_HOME/config.toml`; authentication still
  uses Codex's normal credential storage. Neither HOME nor CODEX_HOME is changed.
- `--ignore-rules` skips user/project execpolicy `.rules` files. Managed policy
  remains authoritative and may reject the requested execution policy.
- `--disable hooks`, `plugins`, `apps`, and `memories` explicitly disable those
  optional feature gates. The wrapper neither enumerates nor rewrites personal
  plugin/hook configurations. A managed requirement conflict fails in Codex.
- `--ephemeral` suppresses session persistence. It does not promise zero disk
  writes by Codex, its credential refresh, caches, or model tools.
- These flags do **not** establish a completely empty configuration environment.
  System/cloud-managed requirements, project config, AGENTS instructions,
  discoverable skills, environment, and other Codex defaults can still apply.
  There is no inspected switch promising to disable all these layers. Project
  MCP/tools and other inherited integrations are not claimed absent. No profile
  is selected and no user config is mutated by zigagent.
- The bypass flag requests execution without approval/sandbox prompts, subject
  to managed policy. Caller-provided OS isolation is the security boundary;
  workspace and added directories do not constrain filesystem/shell access.

## Stream and lifecycle rules

JSONL is parsed incrementally, one newline-terminated event at a time. A final
partial line, invalid JSON/type, oversized event or invalid known message shape
cannot succeed. Unknown event types and extra fields are tolerated. The last
completed agent_message supplies the bounded summary. A turn.completed plus
zero process exit is required; turn.failed, error, duplicate completion or
later malformed input cannot succeed. Failed intermediate tool attempts do not
override a completed turn: a failing test or patch attempt may be recovered by
the agent. Completion is not verification; only the caller check supplies that.
Terminal failure is sticky even if followed by completion. A backend that closes stdin
before the full prompt is delivered cannot succeed.

All pipes are nonblocking and polled together, including backend stdin. Prompts
and preflight share one timeout; execution starts a fresh timeout after auth.
Each workload has its own process group. SIGINT/SIGTERM request cancellation;
timeout, invalid framed events and closed caller stdout also stop owned work.
TERM is followed by KILL after one second, or 100ms after ordinary leader exit.
The entire drain/reap cleanup budget is three seconds. A non-reaping POSIX
`waitid(WNOWAIT)` observes leader exit while pinning the PID/group identifier.
The final group KILL always precedes reaping, including after normal exit:
ordinary descendants are cleaned up even if they closed both output pipes.
No group or PID is signaled after reaping. Error paths force-stop and perform
bounded reaping. Uninterruptible children can outlive the budget; incomplete
cleanup cannot report success. Deliberately detached processes, host failure
and SIGKILL of zigagent are outside the cleanup guarantee.

Caller stdout is polled for hangup/error during prompt waits and every child
workload. On closure the wrapper stops owned work and exits unsuccessfully
without attempting a result. Result/help writes are nonblocking and each has
a two-second deadline, including when a reader remains open but stops reading.
SIGINT/SIGTERM during result delivery exits 130/143; output may be partial, and no second envelope is emitted. Cancellation handled during backend supervision still emits the cancelled result.
Malformed newline-terminated events and oversized partial events stop live
execution promptly; shorter partial events at EOF remain protocol errors.
All backend streams continue draining concurrently during cleanup.

Execution gets a fresh full `--timeout` budget after authentication; login does
not consume that budget. Failure preserves edits and never retries a mutating
run. An optional caller check starts only after valid completion and zero backend
exit, under that same execution deadline. It invokes `/bin/sh -c COMMAND` in the
canonical workspace with EOF stdin and the caller's inherited environment;
API-key removal applies only to Codex children. Only COMMAND is shell syntax.
The same owned-group supervision cleans checks and their ordinary descendants.
Check stdout/stderr are drained concurrently into one bounded tail in observed
read order; separate pipes do not establish a total order between simultaneous
writes. Check output stays separate from backend diagnostics. Retained output
is bounded; Codex memory, context and cost are not.
