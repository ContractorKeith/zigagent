# Release procedure

Version 0.1.0 completed both-host native acceptance, packaged-binary live checks, performance measurements and independent release skeptic verification at a1c5806. The final documentation-only revision preserves that tested source. Merge/integrated acceptance, tag workflow and published-asset validation are the remaining publication steps.

## Verified release evidence

- Linux x86_64: 7 Zig and 101 Python tests; real Codex 0.166.0 / gpt-6.1-sol scratch fix, caller and independent checks, unchanged Git HEAD. Packaged binary SHA256 `3d40eab6df7da98ca77752ede7e622d88d93e95acf9176752bff1a9c9b521dd6`.
- Mac Studio arm64, macOS 26.6, Zig 0.15.2 / SDK 15.4: 7 Zig and 101 Python tests, both new regressions repeated three times, independent native probes and one successful packaged-binary live fix/check. Binary SHA256 `28b3ea1e415483625bb9fa07331e9438188c0271a2cf05694c48b9a1b1fba748`.
- Fresh Linux and Mac skeptic reviews found terminal-order and gzip-trailer defects; both were reproduced, fixed with failing-then-passing tests, and independently cleared on both hosts. Linux recheck added 35 probes and mutation controls.
- Both native wrapper performance budgets pass. These checks establish no older-macOS or full-stack memory claim. Central worklog report `reports/zigagent-m4-review-2026-11-02.md` retains exact commands, hashes, failures and follow-ups.

## Native artifact gate

On EACH native host with Zig 0.15.2 on PATH:

```bash
bash scripts/accept.sh
python3 scripts/package.py build
python3 scripts/package.py validate
# Linux checksum roundtrip:
(cd dist && sha256sum -c SHA256SUMS)
# macOS checksum roundtrip instead:
(cd dist && shasum -a 256 -c SHA256SUMS)
python3 -m unittest discover -s tests -p 'test_tooling.py' -v
zig build benchmark-tool
python3 scripts/benchmark.py --samples 50
```

Mac Studio requires the existing SDK 15.4 process override documented in
[testing](TESTING.md#macos-sdk-compatibility): prefix acceptance and package build
with `ZIGAGENT_MACOS_SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk`;
for the benchmark helper use `bash scripts/with-macos-sdk.sh zig build benchmark-tool`
with that variable. CI macos-15 uses normal SDK discovery.

Build creates `dist/zigagent-0.1.0-linux-x86_64.tar.gz` OR
`dist/zigagent-0.1.0-macos-arm64.tar.gz` and the corresponding `SHA256SUMS`.
Use a fresh directory (`--directory PATH`) when switching version or target;
stale extra archives are deliberately rejected. Linux targets glibc 2.28+;
macOS builds natively with its selected SDK. No older-macOS compatibility claim
is established by a successful build on a newer host.

Each archive contains exactly these four regular files under a matching
`zigagent-0.1.0-TARGET/` prefix:

- `zigagent`, mode 0755
- `README.md`, `LICENSE`, `CHANGELOG.md`, mode 0644

No links, directories, duplicates, traversal, extra members or setuid bits are
allowed. Validation checks exact manifest entries, SHA256, bounded member sizes,
executable format/CPU, then executes native `--version` and `--help` from a
fresh temporary directory. It never invokes Codex. `--all` requires both target
archives; only the host-native binary is executed. Each other target must have
its own native validation evidence. Normalized tar metadata and gzip mtime make
identical input bytes produce identical archives; this does not promise identical
binaries across different SDK/compiler environments. SHA256 detects corruption;
obtain archive and manifest from the same trusted release, not an untrusted pair.

To combine two already natively validated archives, copy only the two `.tar.gz`
files into a fresh directory and run:

```bash
python3 scripts/package.py manifest --all --directory dist-combined
python3 scripts/package.py validate --all --directory dist-combined
```

## Live subscription gate — parent only

Prepared runner and fake-backend success are NOT live compatibility evidence.
The parent must explicitly coordinate one real run per target, on disposable
host isolation appropriate to Codex's unrestricted shell access. Install official
Codex 0.166.0 separately, complete official ChatGPT login beforehand, select a
model that account can use, and run the PACKAGED native binary:

```bash
python3 scripts/live-check.py --live --model YOUR_AVAILABLE_MODEL \
  --binary /absolute/path/to/extracted/zigagent
```

Inherited Git directory/index/config overrides are removed for runner children;
fixture Git ignores global/system config and hooks.
No real model is invoked without `--live`; `--model` is mandatory. For ordinary
local/CI proof use only:

```bash
python3 scripts/live-check.py --test-mode --model test-model --cleanup-success
```

The runner creates its own new scratch root and Git repo with a subtraction bug
in `calculator.py`. It requests a single fix, runs an explicit caller check for
positive/negative/zero sums, then independently checks the file and unchanged
Git HEAD. It uses `--no-input` and existing official ChatGPT status through
zigagent; it never starts interactive login, reads auth/config files, changes
HOME/CODEX_HOME, retries, or uses a caller repository. Optional integrations and
inherited environment can still affect Codex; see [configuration limits](CODEX-BACKEND.md#configuration-limits).
Scratch is not a sandbox. The caller check is evidence, not a defense against a
malicious backend that can alter the check or host.

JSON stdout contains only allowlisted evidence: synthetic/live label, host,
selected model, exact wrapper/backend versions and SHA256s, fixed-file SHA256,
wrapper exit/status, two check verdicts, no-commit verdict and scratch path.
Summary, diagnostics, stderr, raw events and arbitrary check output are discarded.
On failure it emits a generic runner error or failed verdict and preserves its
owned scratch. On success it preserves scratch by default; `--cleanup-success`
removes only the root it just created. The parent stores sanitized JSON evidence
and reports centrally, diagnoses failures without publishing raw transcripts,
and removes preserved scratch when finished. Credential refresh/cache side
effects belong to Codex; ephemeral mode does not promise zero writes.

## Publish after parent gates

Before tagging: full-branch review, native acceptance and fresh artifacts on both
hosts, actual packaged-binary live checks on both hosts, native performance
records, independent review/stress and fresh per-platform release skeptic clear;
fix findings with tests, reconcile docs, merge and verify clean pushed main.
The project-local [skeptic environment](../.agents/skills/skeptic-env/SKILL.md)
contains exact reviewer commands; parent uses gpt-6.1-sol medium T3 reviewers.

Only then may the parent create `v0.1.0` at the approved commit. The release
workflow rejects a tag/version mismatch, reruns the canonical gate natively,
combines both archives and attaches them plus `SHA256SUMS` to the GitHub release.
CI cannot establish live subscription compatibility or replace native skeptic
review. The orchestrator owns tag, publication and final asset verification.
