# Wrapper baseline

These are synthetic wrapper-only measurements, not Codex/process-tree memory
or model latency measurements. No claim of an overall low-memory stack follows.
Both native hosts have measured baselines below; no Mac values are inferred from Linux.

## Reproduce

```bash
python3 scripts/package.py build  # Zig 0.15.2 ReleaseSmall, native libc
zig build benchmark-tool
python3 scripts/benchmark.py --samples 50 --enforce
```

On Mac Studio select existing SDK 15.4 using the helper described in
[testing](TESTING.md#macos-sdk-compatibility) for both build commands. `--enforce`
applies measured budgets on Linux x86_64 and macOS arm64 and reports
`budgets_enforced: true` on those hosts.

Python drives an unshipped native Zig/libc helper. For each sample that helper
forks/execs only `zigagent --version` or `--help`, directs standard streams to
`/dev/null`, and observes that single child's `wait4` usage. Native launch avoids
the Python pre-exec high-water RSS floor (direct Python launches initially
reported 23,347,200 bytes on this host). The helper has a ten-second per-sample
bound and never launches Codex. It is built by the gate but excluded from archives.

Startup is monotonic elapsed fork-to-reap time, including OS scheduling and up
to roughly 0.1 ms poll quantization; it is not internal initialization time.
One warmup precedes 50 samples per command; caches are warm, stdout is discarded,
and this is not cold-start/disk/terminal performance. p95 selects index
`floor((n-1)*0.95)` from sorted samples. RSS is per-child `ru_maxrss`, converted
from KiB on Linux and already bytes on Darwin; it includes loader/libc/pages and
a small native pre-exec floor. Very short-lived processes can report zero on
some kernels. It excludes helper/Python RSS, other processes, backend models,
streaming buffers during a run and all Codex descendants. Run workloads have
separate retained-buffer bounds in the spec; these baselines don't measure them.

## Actual Linux observation — 2026-11-02

Host: Linux 7.2.8-9-omarchy x86_64, host glibc 2.44; Zig 0.15.2, target
x86_64-linux-gnu.2.28, ReleaseSmall. Candidate version: 0.1.0.
Binary: **120,312 bytes**, SHA256
`e0907732ddb5220ecb8c58b832874c5b28006406c42780765f68ddcdbc8a4d85`.

| Command (50 samples) | Median ms | p95 ms | Max ms | Peak RSS bytes |
|---|---:|---:|---:|---:|
| --version | 0.610209 | 0.747238 | 0.777550 | 1,675,264 |
| --help | 0.590094 | 0.752268 | 0.789004 | 1,675,264 |

`python3 scripts/benchmark.py --samples 50 --enforce` passed. This single host
observation supplies generous regression alarms, not a general performance SLA:
1 MiB binary (8.7× measured), 50 ms p95 (66× measured), 16 MiB child peak RSS
(10× measured). The slack accommodates ordinary loader/scheduler differences
while catching a large accidental dependency, startup wait or allocation.
Both native CI hosts enforce these after correctness acceptance.
Investigate reproducible excess with the same build/host/method before changing
budgets. No timing threshold is used to assert arrival of model text or messages.

## Actual Mac observation — 2026-11-02

Mac Studio, macOS 26.6 arm64, SDK 15.4, Zig 0.15.2 ReleaseSmall; candidate
0.1.0 at bac00f6. Native packaging, checksum and extracted-binary hash checks
passed. Binary: **178,056 bytes**, SHA256
`57a5805c73fc6b22a7d02e151a6e9a45e9aba37021b644cb6bad715f5334ff33`.

| Command (50 samples) | Median ms | p95 ms | Max ms | Peak RSS bytes |
|---|---:|---:|---:|---:|
| --version | 1.886 | 2.394 | 2.632 | 1,523,712 |
| --help | 1.8855 | 2.041 | 2.104 | 1,523,712 |

Same native-helper warm-cache method; Darwin wait4 reports bytes. These data
justify the same generous alarms: 1 MiB binary (5.9× measured), 50 ms p95
(20.9× measured), 16 MiB peak RSS (11× measured). Measurements do not establish
live compatibility; the first Mac acceptance run had a separate timing-test
failure and no real model call was made in that run.
