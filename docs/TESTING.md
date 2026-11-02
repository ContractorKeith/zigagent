# M1 testing

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

The gate runs **7 Zig unit tests and 41 Python black-box tests**. All 23 original M0 checks remain, adapting temporary unimplemented run/stdin expectations to delivered behavior. Eighteen new backend checks cover strict versions and failed/missing probes; capability checks; ChatGPT/API-key/logged-out/unexpected authentication; literal argv/path/model data; exact stdin forwarding and early closure rejection; unchanged synthetic config; API-key environment removal; 1 MiB prompt boundaries; terminal rejection; completion plus zero exit; malformed/partial/invalid UTF-8/oversized events; unknown events; terminal failures and recovered tool attempts; duplicate completion; nonzero exit; concurrent saturation and bounded UTF-8-safe output. Deadline fixtures cover open prompt pipes, hanging version/help/auth/execution, closed output pipes with a live leader, and inherited descendant pipes.

`tests/fake_codex.py` uses only synthetic data. `ZIGAGENT_TEST_LOG`, `ZIGAGENT_TEST_SCENARIO` and `ZIGAGENT_TEST_VERSION` configure that fixture, never the shipped app. The argv/config test snapshots a disposable project's synthetic `.codex/config.toml` and checks exact suppression flags; it makes no claim to prove the actual Codex implementation's config behavior. Installed 0.166.0 help/features/login-status inspection and official documentation establish supported controls; fake events provide wrapper evidence, not live task compatibility evidence.

Local Linux acceptance passes. A separate cross-build of `aarch64-macos` establishes compilation only, not native macOS behavior. Both-host CI, parent full-diff review, independent review and fresh attack remain integration gates. No real task-bearing request was made. M2 still owns terminal login, SIGINT/SIGTERM translation, graceful group cleanup, early closed-result-output detection and broader adversarial lifecycle tests. M3 owns caller checks. Neither M1 success nor green fixture tests establish release readiness.
