# Changelog

## 0.1.0 — prepared, unreleased

First Codex supervisor release candidate. No tag or published release exists yet.

- Supervise external Codex 0.166.0 using existing ChatGPT authentication.
- Require an explicit model; support prompt stdin and literal workspace/context arguments.
- Emit one schema-version-1 result with independent caller verification.
- Bound execution, retained output, login and ordinary descendant cleanup; preserve edits on failure.
- Prepare native Linux x86_64 (glibc 2.28+) and macOS arm64 archives, checksums and release tooling.

Both-host live subscription checks and independent release skeptic gates are required before tagging v0.1.0.
