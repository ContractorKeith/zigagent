# zigagent

A Zig supervisor around an installed Codex CLI for small repository fixes. It uses the caller's ChatGPT subscription, normalizes results, bounds execution and retained output, and optionally verifies the result. V1 is complete only when the spec acceptance passes on Linux x86_64 and macOS arm64 and packaged artifacts pass the release gate.

## Status
M0 CLI harness, M1 controlled backend and M2 terminal login/bounded lifecycle are merged on main (M2 baseline da5da400922d9dc107a678fab4dd97529083e935). M3 caller checks and the scripting contract are delivered in this branch, pending parent review and both-host acceptance. M4 packaging/live release evidence remains. No supervisor release yet.

## Commands
```bash
bash scripts/accept.sh   # canonical fmt/unit/build/black-box gate
zig build
zig build test
```

## Pointers
- docs/features/supervisor/SPEC.md — authoritative product and CLI contract.
- docs/PLAN.md — milestone dependency order, feature matrix and acceptance.
- CONTEXT.md — glossary; docs/adr/ — consequential decisions.
- Central session memory: ../worklog/projects/zigagent.md.

## Conventions & Gotchas
- Zig 0.15.2, standard library plus OS libc only. Keep modules small and readable.
- Codex owns the agent loop, instructions and tools. Do not claim a filesystem sandbox or a Codex memory limit.
- JSON stdout contains one versioned envelope, never raw backend output or login chatter.
- Test the compiled binary against a fake Codex. Only explicit live release checks use the real login; never print/read credential contents.
- Preserve edits on any failure. Do not retry an agent run automatically.
- No worker delegation. Worker reports; orchestrator logs and merges.
- Commits: <type>: <description>, ContractorKeith only; no AI attribution.

## Tracking
One milestone = one issue = one branch = one draft PR = one isolated T3 worker thread. M0–M4 are sequential. Sol gpt-6.1-sol medium workers; Astra orchestrates. Full-diff parent review and acceptance, independent review, fresh adversarial pass, then merge commit. Release skeptic checks precede a tag.

## Out of Scope
Custom model adapter or agent loop, ACP, shared library, WASM, resume, TUI, Homebrew, automatic rollback/repair, Windows, automatic model fallback.
