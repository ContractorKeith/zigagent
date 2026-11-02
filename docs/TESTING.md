# M2 testing

## macOS SDK compatibility

Zig 0.15.2 cannot link its native build runner against the SDK 26.5 libSystem stubs on the Mac Studio (arm64e target matching). The installed SDK 15.4 was verified with M0: 6 unit and 23 black-box tests passed. M1 subsequently passed 7 unit and 44 black-box checks on both hosts; M2 native macOS acceptance remains parent-owned. `SDKROOT` alone does not change Zig's xcrun discovery, and `zig build --sysroot` does not select the build runner SDK.

Select an existing compatible SDK for this process only:

```bash
ZIGAGENT_MACOS_SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk bash scripts/accept.sh
# For a direct build with that SDK:
ZIGAGENT_MACOS_SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk bash scripts/with-macos-sdk.sh zig build
```

The helper temporarily overrides only `xcrun --sdk macosx --show-sdk-path`, delegates other xcrun commands to `/usr/bin/xcrun`, and removes the shim after the command. It does not install an SDK or change system settings, HOME, CODEX_HOME, or shell configuration. Without the variable, normal host SDK discovery remains unchanged. The example SDK path must actually exist; choose an installed compatible SDK rather than downloading one implicitly. CI's macos-15 SDK works without this override.

## Gate

Run `bash scripts/accept.sh` with Zig 0.15.2 on PATH. The gate rejects other compiler versions, checks `zig fmt`, runs `zig build test`, builds `zig-out/bin/zigagent`, then runs Python unittest discovery against that binary. Build/cache output stays on disk in the checkout (`.zig-cache`, `zig-out`). Python is test-only. CI runs this exact command on native Ubuntu x86_64 and macOS arm64 hosts, with a checksum-verified official compiler. No model or credential access occurs.

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

The gate runs **7 Zig unit tests and 70 Python black-box tests**. All 23 original M0 checks remain, adapting temporary unimplemented run/stdin expectations to delivered behavior. Twenty-one new backend checks cover strict versions and failed/missing probes; capability checks; ChatGPT/API-key/logged-out/unexpected authentication; literal argv/path/model data; exact stdin forwarding and early closure rejection; unchanged synthetic config; API-key environment removal; 1 MiB prompt boundaries; terminal rejection; completion plus zero exit; malformed/partial/invalid UTF-8/oversized events; unknown events; terminal failures and recovered tool attempts; nonfatal warning items; completion usage shape and terminal ordering; exact capability tokens; duplicate completion; nonzero exit; concurrent saturation and bounded UTF-8-safe output. Deadline fixtures cover open prompt pipes, hanging version/help/auth/execution, closed output pipes with a live leader, and inherited descendant pipes.

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

Linux acceptance passes. An aarch64-macos cross-build establishes compilation
only; native macOS execution, both-host CI, parent full-diff review, independent
review and fresh attack remain integration gates. No real login or task-bearing
Codex call was made. M0/M1 are merged; M2 is delivered in this branch. M3 caller
checks remain explicitly unimplemented; packaging/live release evidence is M4.
Fixture tests do not establish release readiness.

Standards follow-up: result-delivery cancellation and stale-PID teardown tests both failed before fixes. Result writes now return 130/143 when cancelled; a partially emitted envelope is not followed by another. Test teardown never signals recorded backend IDs after reaping; synthetic survivors on a failed test self-exit within 20 seconds.

Live invalid-event tests wait for a bounded fixture readiness marker before
measuring shutdown, separating four backend startups from the cleanup budget.
The malformed-event case injects 0.6 seconds per startup through the fixture-only
`ZIGAGENT_TEST_STARTUP_DELAY`; the old three-second whole-run assertion failed
with that delay, while the synchronized shutdown assertion passes. Ten isolated
native Mac diagnostic trials passed at 1.57–1.94 seconds total; they did not
establish the cause of the earlier intermittent full-gate timeout.

Attack follow-up: four tests first reproduced closed-stdin login failure, closed-stdout login/panic, terminal Ctrl-C handled as exit 130 being misclassified, and closed-stderr output panic. Terminal descriptors now stay above 2, child setup reserves a missing stdin slot, login checks caller output before opening its terminal, and output fcntl errors return failure. Login preserves handled 130/143 exits as cancellation. Closed-stderr JSON runs remain supported.
