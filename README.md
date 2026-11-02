# zigagent

A small Zig CLI that supervises Codex for repository fixes: one JSON result, bounded execution, cancellation, and an optional verification command.

Status: planning scaffold; implementation follows M0–M4 in [the plan](docs/PLAN.md). No working release yet.

Codex is installed separately and owns the agent loop. ChatGPT subscription login is required. Supported release targets are Linux x86_64 and macOS arm64. The caller supplies OS isolation; a working directory is not an enforced access boundary.

See the [spec](docs/features/supervisor/SPEC.md) for the agreed CLI and [glossary](CONTEXT.md) for terms.
