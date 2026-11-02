# Codex 0.166.0 backend contract (M1)

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
nonzero exit produces authentication_required; API-key status and other probe
failures produce authentication_failed. M1 never starts interactive login.

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
zero process exit is required; turn.failed, error, failed item status, nonzero
item exit code, duplicate completion or later malformed input cannot succeed.
Failure is sticky even if followed by completion. A backend that closes stdin
before the full prompt is delivered cannot succeed.

All pipes are nonblocking and polled together, including backend stdin. Prompts
and preflight share one timeout; execution starts a fresh timeout after auth.
Each workload has its own process group. Deadline cleanup sends SIGKILL to that
group, then allows at most two seconds to reap; ordinary inherited pipes cannot
hold the wrapper indefinitely. The leader stays unreaped while pipes drain,
so deadline signaling cannot target a recycled group id. Failure preserves
edits and never retries.

M2 must add graceful termination/escalation, SIGINT/SIGTERM result translation,
early detection of closed result stdout, and broader descendant/signal tests.
M1 does not promise cleanup of descendants that close their pipes and outlive
a successful leader, or deliberately detached processes. An uninterruptible OS
child can outlive the finite cleanup budget; the wrapper returns failure.
Interactive login is M2 and `--check` is rejected before any backend starts
until M3. Retained output is bounded; Codex memory, context and cost are not.
