# M0 testing

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

`tests/harness.py` makes a new disposable directory for every test and captures stdout/stderr with a finite subprocess timeout. Directory fixtures, fake-backend copies and logs live there and are removed afterward. It never rewrites HOME or CODEX_HOME or reads credential/config files. `tests/fake_codex.py` is a standalone executable fixture with synthetic version/login/exec responses. Test-specific `ZIGAGENT_TEST_LOG` and `ZIGAGENT_TEST_SCENARIO` control its log and responses. M0 exercises the fake directly to prove the seam works, and asserts zigagent never invokes it; backend invocation tests begin in M1. Fake events are synthetic scaffolding, not live protocol compatibility evidence.

Coverage includes help/version without a backend, usage and unknown/missing arguments, model precedence, repeated context paths, directory/file negatives, numeric extrema/overflow, JSON schema/one-envelope framing, quotes/control characters/Unicode, invalid UTF-8, option delimiters, plain stderr without color, and honest unimplemented run/login/check behavior. Unit tests cover prompt sizes beyond typical OS argv limits and numeric/parser/schema details. M0 never waits for stdin, even when its pipe stays open. Finite prompt reading, terminal detection and backend preflight are M1/M2 work; executing checks is M3. A green M0 gate makes no claims about those behaviors or release readiness.
