---
name: skeptic-env
description: Exact zigagent build, packaging and disposable fixture facts for parent-coordinated skeptical review; not a workflow on its own.
---

# skeptic-env — zigagent

Native Zig supervisor of external Codex; release requires both-host acceptance, artifact execution, live fix/check and independent skeptic evidence. Prepared runners are not evidence.

## Stack and commands

```bash
# Zig 0.15.2 on PATH; Linux installed toolchain:
export PATH=/home/contractorkeith/.local/share/zigagent-toolchains/zig-x86_64-linux-0.15.2:$PATH
bash scripts/accept.sh  # fmt, 7 Zig units, build/package, Python public-seam tests
python3 scripts/package.py build
python3 scripts/package.py validate
zig build benchmark-tool
python3 scripts/benchmark.py --samples 50
# Seeds a NEW disposable Git repo, edits calculator.py via bundled fake, verifies twice:
python3 scripts/live-check.py --test-mode --model test-model --cleanup-success
# Mac Studio: prefix acceptance/package with existing SDK selection:
ZIGAGENT_MACOS_SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk bash scripts/accept.sh
ZIGAGENT_MACOS_SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk python3 scripts/package.py build
```

## Platforms

| Platform | Ships | Review on | Facts |
|---|---|---|---|
| Linux x86_64 | yes | Omarchy | Zig 0.15.2, default glibc 2.28 target avoids Arch CRT .sframe |
| macOS arm64 | yes | Mac Studio | macOS 26.6; Zig 0.15.2 needs installed SDK 15.4 helper; CI macos-15 uses normal SDK |
| Windows/other architectures | no | read only | no support claim |

## What to attack

Archive corruption/missing/wrong target/version, traversal, links, duplicate members, permissions, checksums; execute packaged binary on its native host. Exercise malformed/oversized JSONL, false completion, output floods, shared check deadlines, closed fds, TTY login and ordinary descendant cleanup. Try workspace rename/replacement, symlinks, literal shell characters and Unicode paths using scratch only. No stale-PID signaling; fake survivors self-expire. Do not assert human messages or summary arrival timing. Startup varies on Mac; use readiness coordination and generous bounded deadlines.

## Traps and ownership

No user project data, credential/config reads, HOME/CODEX_HOME rewrites or global tools. Runner owns a freshly created scratch root; failures preserve it. `--test-mode` forces the bundled fake; it never establishes model compatibility. Only an explicitly parent-coordinated `--live --model MODEL` invocation may use existing official ChatGPT login (Codex 0.166.0); no interactive login in runner. Caller supplies OS isolation; workspace is not containment. Benchmark help/version excludes Codex and is not a stack memory claim.

Parent uses gpt-6.1-sol medium T3 reviewers per user routing, not global skill defaults. Worker does not delegate, invoke live models, write worklog/reports, merge or tag. Parent owns both-host live invocation, reports/logging and release gates. Earlier M3 Linux/native Mac gate: 7 Zig + 85 Python tests passed; verify against reviewed SHA and parent records, not this prose alone.
