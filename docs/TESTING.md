# Testing

## macOS SDK compatibility

Zig 0.15.2 cannot link its native build runner against the SDK 26.5 libSystem stubs on the Mac Studio (arm64e target matching). The installed SDK 15.4 was verified with M0: 6 unit and 23 black-box tests passed. M1 subsequently passed 7 unit and 44 black-box checks on both hosts; M2 passed native acceptance on both hosts; M3 final native Linux/macOS acceptance passed (7 Zig units, 85 Python methods); M4 native Mac acceptance remains parent-owned. `SDKROOT` alone does not change Zig's xcrun discovery, and `zig build --sysroot` does not select the build runner SDK.

Select an existing compatible SDK for this process only:

```bash
ZIGAGENT_MACOS_SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk bash scripts/accept.sh
# For a direct build with that SDK:
ZIGAGENT_MACOS_SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk bash scripts/with-macos-sdk.sh zig build
```

The helper temporarily overrides only `xcrun --sdk macosx --show-sdk-path`, delegates other xcrun commands to `/usr/bin/xcrun`, and removes the shim after the command. It does not install an SDK or change system settings, HOME, CODEX_HOME, or shell configuration. Without the variable, normal host SDK discovery remains unchanged. The example SDK path must actually exist; choose an installed compatible SDK rather than downloading one implicitly. CI's macos-15 SDK works without this override.

## Gate

Run `bash scripts/accept.sh` with Zig 0.15.2 on PATH. The gate rejects other compiler versions, checks `zig fmt`, runs `zig build test`, builds `zig-out/bin/zigagent`, builds/validates the native ReleaseSmall archive, then runs Python unittest discovery against that release binary. Build/cache output stays on disk in the checkout (`.zig-cache`, `zig-out`). Python is maintainer tooling only. CI runs this exact command on native Ubuntu x86_64 and macOS arm64 hosts, with a checksum-verified official compiler. No model or credential access occurs.

The local Linux compiler executable installed for M0 is:

```
/home/contractorkeith/.local/share/zigagent-toolchains/zig-x86_64-linux-0.15.2/zig
```

`scripts/install-zig.sh [DIRECTORY]` installs the matching host toolchain and prints its directory. The pinned checksums were verified against `https://ziglang.org/download/index.json`:

| Archive | SHA256 |
|---|---|
| zig-x86_64-linux-0.15.2.tar.xz | 02aa270f183da276e5b5920b1dac44a63f1a49e55050ebde3aecc9eb82f93239 |
| zig-aarch64-macos-0.15.2.tar.xz | 3cc2bab367e185cdfb27501c4b30b1b0653c28d9f73df8dc91488e66ece5fa6b |

`tests/harness.py` makes a disposable directory for every test and captures stdout/stderr with a finite subprocess timeout. A fake `codex` is first on that test's PATH; explicit `--codex` also exercises a path containing spaces. No test changes HOME/CODEX_HOME, reads credentials, or calls a real model. Small fixture/log files live in the disposable directory. Compiler caches remain on disk in the checkout. Linux defaults to glibc 2.28 through Zig's bundled libc support: this avoids pinned Zig's inability to link the newer Arch host CRT `.sframe` relocations. The binary links OS libc; macOS uses its normal target.

The merged M3 gate ran **7 Zig unit tests and 85 Python black-box tests**; M4 extends this below. All 23 original M0 checks remain, adapting temporary unimplemented run/stdin expectations to delivered behavior. Twenty-one new backend checks cover strict versions and failed/missing probes; capability checks; ChatGPT/API-key/logged-out/unexpected authentication; literal argv/path/model data; exact stdin forwarding and early closure rejection; unchanged synthetic config; API-key environment removal; 1 MiB prompt boundaries; terminal rejection; completion plus zero exit; malformed/partial/invalid UTF-8/oversized events; unknown events; terminal failures and recovered tool attempts; nonfatal warning items; completion usage shape and terminal ordering; exact capability tokens; duplicate completion; nonzero exit; concurrent saturation and bounded UTF-8-safe output. Deadline fixtures cover open prompt pipes, hanging version/help/auth/execution, closed output pipes with a live leader, and inherited descendant pipes.

`tests/fake_codex.py` uses only synthetic data. `ZIGAGENT_TEST_LOG`, `ZIGAGENT_TEST_SCENARIO` and `ZIGAGENT_TEST_VERSION` configure that fixture, never the shipped app. The argv/config test snapshots a disposable project's synthetic `.codex/config.toml` and checks exact suppression flags; it makes no claim to prove the actual Codex implementation's config behavior. Installed 0.166.0 help/features/login-status inspection and official documentation establish supported controls; fake events provide wrapper evidence, not live task compatibility evidence.

M2 adds 26 compiled-process lifecycle checks in `tests/test_lifecycle.py`.
PTY fixtures create an actual controlling terminal with piped result stdout
and nonterminal stdin. They prove terminal-only login, no-input rejection,
post-login ChatGPT verification, unrelated auth failure rejection, separate
login/execution budgets, finite login/post-login waits and cancellation without
starting an agent. Explicit login also reports a missing backend with exit 3.
A tty stdin without a controlling terminal is insufficient.
Synthetic descendants exercise TERM before KILL, SIGINT/SIGTERM translation,
preserved edits, normal/simultaneous exits, retained/closed inherited pipes,
and unrelated-process survival. Additional fixtures cover cancellation in
prompt/version/help/auth waits, closed stdout during prompt/preflight/execution,
stalled result readers, invalid/oversized events from still-running backends,
and a mid-run auth failure with no retry. Descendant tests recognize a stopped
zombie as terminated while the host init completes orphan reaping.

Red/green evidence: the initial four-method PTY suite produced four expected
failures on M1 (unsupported login / authentication_required instead of terminal
login), then passed after implementation. Six new lifecycle methods were run
against an unchanged M1
build from `git archive 30b6fae` in a disposable source directory: cancellation,
graceful timeout, normal descendant cleanup, closed caller stdout and both live
invalid-event cases all exposed the old behavior. The M2 binary passes those
same tests. A later prompt SIGTERM/EOF race first returned usage_error (2);
checking cancellation immediately after poll corrected it to cancelled (143).
The full gate also exposed Zig 0.15.2 printing an unexpected-errno trace when
`/dev/tty` returned ENXIO. Handling that expected libc-open failure directly
restored clean unattended JSON/stderr. An explicit-login missing-backend test
first returned backend_failed (1), then passed with backend_missing (3). A final
partial event followed by stdout EOF while the backend stayed alive first hung;
finishing JSONL framing on stdout EOF made it fail promptly as protocol_error.
All tests exercise the public compiled-process seam; no private lifecycle mocks.

M0–M4 native Linux/macOS gates passed with 7 Zig units and 101 Python methods. Both platforms also passed packaged-binary subscription fixes with independent caller checks and fresh release skeptic verification. Fixture tests alone do not establish release readiness; evidence is summarized in [release docs](RELEASE.md).

Standards follow-up: result-delivery cancellation and stale-PID teardown tests both failed before fixes. Result writes now return 130/143 when cancelled; a partially emitted envelope is not followed by another. Test teardown never signals recorded backend IDs after reaping; synthetic survivors on a failed test self-exit within 20 seconds.

Live invalid-event tests wait for a bounded fixture readiness marker before
measuring shutdown, separating four backend startups from the cleanup budget.
The malformed-event case injects 0.6 seconds per startup through the fixture-only
`ZIGAGENT_TEST_STARTUP_DELAY`; the old three-second whole-run assertion failed
with that delay, while the synchronized shutdown assertion passes. Ten isolated
native Mac diagnostic trials passed at 1.57–1.94 seconds total; they did not
establish the cause of the earlier intermittent full-gate timeout.

Attack follow-up: four tests first reproduced closed-stdin login failure, closed-stdout login/panic, terminal Ctrl-C handled as exit 130 being misclassified, and closed-stderr output panic. Terminal descriptors now stay above 2, child setup reserves a missing stdin slot, login checks caller output before opening its terminal, and output fcntl errors return failure. Login preserves handled 130/143 exits as cancellation. Closed-stderr JSON runs remain supported.

M3 adds 15 methods in `tests/test_checks.py` and replaces the temporary M0 check
rejection assertion with a passing check. Fixtures exercise a deterministic
scratch Git repository edit followed by pass/fail/no check, preserved staged
content with no automatic commits/retries, actual exit status and shell errors,
EOF stdin, inherited check environment, literal malicious model/prompt/path
strings, combined output overflow/UTF-8 replacement, the JSON/plain failure
matrix, backend cancellation without check launch, exhausted and remaining
shared budgets (the exhausted handoff uses a shell fake to exclude Python
startup latency), check timeout/cancellation and ordinary descendant cleanup
with retained or closed pipes. Readiness markers precede cancellation; fixture
survivors self-expire in 20 seconds, and tests never signal stale recorded PIDs.

M3 red/green evidence: the first completion/check test failed on the M2 binary
with `unimplemented` instead of exit 0. Plain verdict/output assertions then
failed until rendering was added. An inherited synthetic environment test
returned check_failed/5 before Codex-only filtering was separated from caller
check inheritance. The usage/check matrix initially reported not_requested on
invalid numeric arguments; it now retains not_run for a requested check.
All evidence uses the compiled public CLI. No real authentication or model call
was performed. M3 native acceptance passed before merge; its review history is retained in the merged PR.

Self-review regression: removing a workspace symlink during the fake agent run
first made check setup fail with backend_failed/1. Reusing the canonical path
already passed to Codex fixes the handoff and keeps both workloads in the same
workspace. The new CLI assertion passes after the fix.

Review follow-up (#20): the exhausted-budget assertion no longer requires a
phase-specific human message. An 80 ms delayed `cat` fixture reproduced the
macOS CI failure: the backend correctly timed out before the check handoff.
The same probe passes with assertions on timeout status/exit, verification
`not_run`, and the absent check marker. Scheduling determines the timeout phase;
this test does not claim deterministic coverage of the handoff branch.
The native bd06663 gate exposed a second assumption: completion can arrive
after the deadline, leaving an empty summary. A 1.1-second delayed `cat`
reproduced that assertion failure. The test now includes 0/0.08/1.1-second
delays and asserts only the timeout/no-launch contract, not summary contents.

Review follow-up (#21): a fake backend renames the workspace and creates a
replacement at its old path. The new check first read replacement content;
retaining an open workspace directory and using it as the child's cwd fixes
the identity loss. The regression requires verification of original content.
Closed-stdin/stderr probes then exposed child setup overwriting a directory
handle in a standard descriptor slot; moving it above fd 2 preserves identity
without changing the caller's closed descriptors.

Native follow-up (#22): the separate-login-budget test exhausted its one-second
preflight allowance before login on Mac. A 0.4-second fixture startup delay
reproduced this locally. The test now includes that delay, gives probes and
execution three seconds, and makes login alone take 3.2 seconds under a separate
six-second login allowance. Its PTY harness remains bounded at twelve seconds.


Nine M3 test methods were also run against an unchanged M2 binary built from
`git archive da5da400922d9dc107a678fab4dd97529083e935` in a disposable source
directory: all nine failed (11 assertion/subtest failures, zero setup errors)
because checks were rejected as unimplemented. The archive was removed after
the run; no extra worktree was created.

Reproduce a synthetic edit and passing caller check without login/model access:

```bash
python3 - <<'PYTHON'
import os
from pathlib import Path
import subprocess
import tempfile

with tempfile.TemporaryDirectory(prefix="zigagent-example-") as scratch:
    env = dict(os.environ, ZIGAGENT_TEST_SCENARIO="edit",
               ZIGAGENT_TEST_LOG=str(Path(scratch) / "argv.jsonl"))
    subprocess.run([
        "./zig-out/bin/zigagent", "run", "--model", "test-model", "--no-input",
        "--codex", str(Path("tests/fake_codex.py").resolve()),
        "--workspace", scratch, "--json", "--check",
        'test "$(cat preserved-edit)" = "keep edits" && printf verified',
        "Fix the parser",
    ], env=env, check=True)
PYTHON
```

## M4 tooling

The canonical gate now includes native ReleaseSmall packaging and 15 tooling
methods (101 Python methods total). Artifact tests recompute checksums when
attacking content, so they exercise content validation beyond checksum mismatch.
They reject truncated/missing/extra/wrong artifacts, invalid manifests, traversal,
symlinks, duplicate/missing members, modes, executable format and version.
Live-runner tests force the bundled fake, verify actual file change and both
checks, prove explicit opt-in, preserve failed scratch and suppress raw output.
The benchmark smoke check invokes only help/version.

```bash
python3 scripts/package.py build
python3 scripts/package.py validate
zig build benchmark-tool
python3 -m unittest discover -s tests -p 'test_tooling.py' -v
python3 scripts/live-check.py --test-mode --model test-model --cleanup-success
python3 scripts/benchmark.py --samples 50
```

See [release procedure](RELEASE.md) for native roundtrips, optional parent-only
live invocation and missing gates; [performance](PERFORMANCE.md) records method,
actual Linux values and measurement limits. Ordinary CI has no network/model
calls beyond installing the pinned compiler and uploading artifacts. No fixtures
read real credentials or configuration. Prepared runners do not prove release
readiness or real model compatibility.

M4 self-review regression: a synthetic inherited GIT_DIR/GIT_WORK_TREE redirected
fixture Git operations and made the new override test fail before the fix.
The runner now strips inherited GIT_* values and disables global/system Git
configuration for its child environment, so only its newly created repo is used.
The regression passes; it never points at a real user repository.

Review finding #24: Python optimization removed the generated checker's
assertions, letting multiplication pass as addition. A copied fake backend
reproduced this false success under PYTHONOPTIMIZE=1. Explicit conditional
failures now reject the wrong edit in both caller and independent checks,
regardless of optimization.

Review findings #25–26: malformed nested check-output values now produce generic
JSON failure evidence instead of a traceback. Generated archives and manifests
replace their directory entries atomically, leaving existing symlink targets
untouched. Regression fixtures first reproduced both failures.

Native follow-up #27: normal descendant cleanup now waits for fixture readiness
before its three-second cleanup allowance. A 0.8-second delay at each backend
startup reproduced all three old whole-run timeout failures; the new test
includes this delay and retains descendant/unrelated-process assertions.
The original Mac timeout's precise cause was not established independently.

Release skeptic regressions reject completed tool/file items after terminal
completion and prove the caller check never starts. Archive validation drains
the bounded gzip stream, rejecting missing trailers and CRC damage even with
a matching recomputed checksum. Both regressions failed before their fixes.
