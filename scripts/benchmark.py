#!/usr/bin/env python3
"""Measure the wrapper alone using wait4 per-child RSS; never launches Codex."""
import argparse
import json
from pathlib import Path
import platform
import statistics
import subprocess

from package import ROOT, sha256


def sample(binary, flag):
    result = subprocess.run([str(ROOT / "zig-out/bin/zigagent-measure"), str(binary), flag],
                            capture_output=True, check=True, timeout=15)
    value = json.loads(result.stdout)
    return value["elapsed_ns"] / 1_000_000, value["peak_rss_bytes"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "zig-out/bin/zigagent")
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--enforce", action="store_true", help="enforce measured native baseline budgets")
    args = parser.parse_args()
    if not 5 <= args.samples <= 1000:
        parser.error("samples must be 5..1000")
    binary = args.binary.resolve()
    metrics = {}
    for flag in ("--version", "--help"):
        sample(binary, flag)  # warm file cache; not a cold-start experiment
        values = [sample(binary, flag) for _ in range(args.samples)]
        times, rss = zip(*values)
        metrics[flag] = {"median_ms": statistics.median(times),
                         "p95_ms": sorted(times)[int((len(times) - 1) * .95)],
                         "max_ms": max(times), "peak_rss_bytes": max(rss)}
    size = binary.stat().st_size
    # Generous finite alarms derived from both native hosts in docs/PERFORMANCE.md.
    enforced = args.enforce and (platform.system(), platform.machine()) in (
        ("Linux", "x86_64"), ("Darwin", "arm64"))
    passed = size <= 1024 * 1024 and all(m["p95_ms"] <= 50 and
             m["peak_rss_bytes"] <= 16 * 1024 * 1024 for m in metrics.values())
    report = {"platform": platform.platform(), "machine": platform.machine(),
              "binary_sha256": sha256(binary), "binary_bytes": size,
              "samples_per_command": args.samples, "warm_cache": True,
              "scope": "wrapper-only help/version; no backend or process-tree measurement",
              "rss_source": "native launcher wait4 ru_maxrss; Darwin bytes, Linux KiB converted to bytes",
              "metrics": metrics, "budgets_enforced": enforced,
              "passed": passed if enforced else None}
    print(json.dumps(report, sort_keys=True))
    return 0 if not enforced or passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
