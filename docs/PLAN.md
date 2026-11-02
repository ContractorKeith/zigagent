# zigagent — Build Plan

Status: M0, M1 and M2 are merged on main through da5da400922d9dc107a678fab4dd97529083e935. M3 caller checks and the scripting contract are delivered in this branch, pending parent review and both-host acceptance. M4 release evidence remains. Authoritative scope: [supervisor spec](features/supervisor/SPEC.md). Interview decisions are saved in the central worklog. fx inspired the scriptable surface; mdkb supplied the process shape. Custom fx-like agent internals are deferred because v1 uses Codex subscription login.

## Goal

Ship a predictable Codex supervisor written in readable Zig. V1 is done when every v1 row passes on Linux x86_64 and macOS arm64, release artifacts are verified, both real subscription checks pass, and the independent release skeptic is clear.

## Feature matrix

| Feature | Decision | Milestone |
|---|---|---|
| Zig build, schema, parse/help/version, executable test seam, CI | v1 | M0 |
| Version/auth preflight, controlled Codex invocation, independent runs | v1 | M1 |
| Backend JSONL to one result; completion and error semantics | v1 | M1 |
| Minimal bounded prompt/probe/execution lifecycle and stream limits | v1 | M1 |
| Terminal login, graceful signal/group cancellation and adversarial lifecycle hardening | v1 | M2 |
| Caller check and final failure contract, negative-path coverage | v1 | M3 |
| Two release archives/checksums, docs, live tests, performance baselines | v1 | M4 |
| Own model protocol/agent loop, ACP, library/WASM, resume, Homebrew | Later | — |
| Automatic rollback/repair, model fallback, wrapper telemetry | Drop | — |

## Architecture, data and CLI

Keep parsing/result formatting, backend protocol translation, and POSIX lifecycle supervision separate. The shared contract is the versioned result, not Codex event internals. Only the backend boundary constructs Codex arguments; only lifecycle supervision owns process groups and signal cleanup. Caller check uses the same lifecycle facility. No persistent app database or session store. Codex owns its credentials.

The spec defines commands, all flags/defaults, result schema and exit codes. Dependencies: Zig standard library and libc for OS process facilities; installed Codex for the agent and subscription; Python 3 only for test drivers. No library dependency is justified yet.

## Milestones

All milestones are sequential, integration order M0 → M1 → M2 → M3 → M4. M0 lands alone. Each row is one GitHub issue, one branch, one draft PR and one T3 worktree thread.

| M | Deliverable | Depends on | Done when |
|---|---|---|---|
| M0 | Harness, result schema, CLI parsing and CI | None | Pinned Zig builds; help/version and usage fixtures pass on both CI hosts; fake backend seam exists; unimplemented execution fails honestly |
| M1 | One controlled subscription-backed request | M0 | Fake backend proves argv/version/auth checks, prompt input, completion/failure JSON and no config mutation; no terminal login yet |
| M2 | Bounded login and process lifecycle | M1 | PTY auth and no-input cases, timeout/cancel, ordinary descendants, concurrent draining and oversized/malformed input tests pass |
| M3 | Caller verification and complete scripting contract | M2 | Passing/failing/not-run check paths, shared deadline, complete exit/result matrix and docs examples pass |
| M4 | Packaging and release evidence | M3 | Reproducible native archives/checksums, packaging negatives, CI on both targets, measured performance baseline and live-check runner ready; actual both-host live and skeptic evidence required before tag |

## Acceptance

`bash scripts/accept.sh` is the single worker/reviewer/CI gate. M3 runs formatting, unit tests, a native build and compiled-process black-box fixtures. The 23 M0 regression checks are retained with delivered run behavior replacing temporary unimplemented expectations; terminal login, bounded graceful cleanup and caller checks are delivered. Every milestone extends the gate for its delivered behavior. Fake backend tests are isolated and do not authenticate, modify user configuration or use live models.

Release gate: full current acceptance, fresh artifact build/checksum validation, actual live subscription fix/check on both hosts, independent skeptical review on both hosts, findings fixed with tests, docs reconciled with implementation, clean pushed main, then v0.1.0 release archives with checksums. Measure wrapper RSS separately from backend/process-tree RSS; benchmark evidence must state the method and limitations. Unsupported backend versions are rejected until evidence widens the range.

## Process and tracking

Sol gpt-6.1-sol medium implementation workers in isolated T3 worktrees; Astra orchestrates and reviews full branch diffs, reruns acceptance, obtains independent review and a fresh adversarial pass, fixes or returns confirmed findings, then marks ready and merges with a merge commit. Workers never merge, tag, run log-work or delegate. Reviewers never claim implementation ownership.

GitHub issues are authoritative; one Basecamp github card mirrors this repo with M0–M4 steps. Complete steps only after merge, update Next after each merge, central worklog records decisions/evidence. Before release use skeptic-review and ship gates. No extra user approval needed; the user authorized the full build.
