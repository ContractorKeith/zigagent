# Changelog

## 0.1.0 — 2026-11-03

First Codex supervisor release.

- Supervise external Codex 0.166.0 using existing ChatGPT authentication.
- Require an explicit model; support prompt stdin and literal workspace/context arguments.
- Emit one schema-version-1 result with independent caller verification.
- Bound execution, retained output, login and ordinary descendant cleanup; preserve edits on failure.
- Provide native Linux x86_64 (glibc 2.28+) and macOS arm64 archives, checksums and release tooling.

Validated with native acceptance, real packaged-binary subscription fixes, and independent release skeptic checks on Linux x86_64 and macOS arm64.
