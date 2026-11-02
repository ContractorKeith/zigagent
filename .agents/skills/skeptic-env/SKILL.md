---
name: skeptic-env
description: Run zigagent review against disposable repositories and fake or explicitly authorized real Codex backends.
---

# zigagent review environment

Read AGENTS.md, docs/features/supervisor/SPEC.md and docs/PLAN.md. Run bash scripts/accept.sh against the exact reviewed SHA. Review native Linux x86_64 and macOS arm64; do not infer macOS behavior from Linux.

All destructive/agent checks use a disposable tiny Git repository. Fake-Codex tests require no credentials and must not inspect or change real auth/config. Live checks are explicit release tasks using official existing ChatGPT login; never print, copy or read credential contents. Record exact model, Codex version, binary hash and whether verification passed. No user repository as a fixture.

Attack malformed/oversized JSONL, invalid UTF-8, stderr flood, process exit before pipe EOF, cancelled checks, descendant cleanup, TTY versus non-TTY login, unsupported versions, and completion text without completion events. An agent saying done is not test evidence. Check output must remain valid bounded JSON.

Use isolated scratch directories; do not repurpose HOME or CODEX_HOME in shell scripts. Fake executable and explicit fixture paths provide isolation. Do not source fixture-controlled shell profiles. Record cleanup limitations for deliberately detached children. Never create real long-lived detached processes in tests.

Reports belong in the central worklog reports directory and findings in labelled GitHub issues. No release tag until both platform reviews and live checks pass.
