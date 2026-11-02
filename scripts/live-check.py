#!/usr/bin/env python3
"""Explicit opt-in scratch fix/check; stdout is allowlisted evidence, never a transcript."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import shlex
import subprocess
import sys
import tempfile

from package import ROOT, sha256, version

BUG = 'def add(a, b):\n    return a - b\n'
CHECK = '''import runpy
from pathlib import Path
module = runpy.run_path("calculator.py")
for a, b, expected in ((7, 4, 11), (-2, 5, 3), (0, 0, 0)):
    if module["add"](a, b) != expected:
        raise SystemExit("incorrect addition")
if Path("calculator.py").read_text() == %r:
    raise SystemExit("fixture unchanged")
print("zigagent-live-check-passed")
''' % BUG


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="parent-coordinated real model invocation")
    mode.add_argument("--test-mode", action="store_true", help="force bundled synthetic backend")
    parser.add_argument("--model", required=True, help="explicit caller-selected model")
    parser.add_argument("--binary", type=Path, default=ROOT / "zig-out/bin/zigagent")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--cleanup-success", action="store_true")
    args = parser.parse_args()
    if not args.model.strip() or not 1 <= args.timeout <= 86400:
        parser.error("model must be nonempty and timeout must be 1..86400")
    binary = args.binary.resolve()
    backend = ROOT / "tests/fake_codex.py" if args.test_mode else Path(shutil.which("codex") or "/missing-codex")
    # Never accept a caller workspace or cleanup target: this root is newly owned.
    scratch = Path(tempfile.mkdtemp(prefix="zigagent-live-"))
    workspace = scratch / "repo"
    workspace.mkdir()
    report = {"evidence": "synthetic" if args.test_mode else "live",
              "platform": platform.platform(), "machine": platform.machine(),
              "model": args.model, "scratch": str(scratch), "passed": False}
    # Git directory/index/config overrides must never redirect fixture commands.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    if args.test_mode:
        env["ZIGAGENT_TEST_SCENARIO"] = "live_fix"
        env.pop("ZIGAGENT_TEST_LOG", None)
        env.pop("ZIGAGENT_TEST_VERSION", None)
        env.pop("ZIGAGENT_TEST_STARTUP_DELAY", None)
    try:
        report.update(binary_sha256=sha256(binary), codex_sha256=sha256(backend))
        version_result = subprocess.run([str(binary), "--version"], capture_output=True,
                                        timeout=10, check=True)
        if version_result.stderr or version_result.stdout != f"zigagent {version()}\n".encode():
            raise ValueError("unexpected_wrapper_version")
        report["zigagent_version"] = version()

        def git(*argv):
            return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *argv],
                                  cwd=workspace, env=env, capture_output=True,
                                  timeout=10, check=True).stdout

        git("-c", "init.templateDir=", "init", "-q")
        (workspace / "calculator.py").write_text(BUG)
        checker = scratch / "check.py"
        checker.write_text(CHECK)
        git("add", "calculator.py")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        before = git("rev-parse", "HEAD").strip()
        # shlex quotes only our explicit caller-check shell command.
        check = f"{shlex.quote(sys.executable)} {shlex.quote(str(checker))}"
        prompt = ("Fix calculator.py so add(a, b) returns the sum for positive, negative "
                  "and zero inputs. Change only calculator.py. Do not commit. "
                  "Keep the existing function name and arguments.")
        result = subprocess.run([str(binary), "run", "--model", args.model,
                                 "--workspace", str(workspace), "--codex", str(backend),
                                 "--json", "--no-input", "--timeout", str(args.timeout),
                                 "--check", check, prompt], env=env, capture_output=True,
                                timeout=2 * args.timeout + 30)
        # Discard summary/diagnostics/stderr even on failure. No raw backend data is saved.
        value = json.loads(result.stdout)
        if (not isinstance(value, dict) or
                not isinstance(value.get("verification"), dict) or
                not isinstance(value.get("backend"), dict)):
            raise ValueError("invalid_wrapper_result")
        verification = value["verification"]
        report.update(exit_code=result.returncode,
                      status=value.get("status") if value.get("status") in
                      ("completed", "failed", "timed_out", "cancelled") else "invalid",
                      codex_version="0.166.0" if value.get("backend", {}).get("version") == "0.166.0" else None,
                      caller_check_passed=verification.get("status") == "passed" and
                      verification.get("exit_code") == 0 and
                      verification.get("output", "").strip() == "zigagent-live-check-passed")
        independent = subprocess.run([sys.executable, str(checker)], cwd=workspace,
                                     capture_output=True, timeout=10)
        report["independent_check_passed"] = (independent.returncode == 0 and
            independent.stdout == b"zigagent-live-check-passed\n" and not independent.stderr)
        data = (workspace / "calculator.py").read_bytes()
        report["file_changed"] = data != BUG.encode()
        report["fixed_file_sha256"] = hashlib.sha256(data).hexdigest()
        report["no_commit"] = before == git("rev-parse", "HEAD").strip()
        report["passed"] = (result.returncode == 0 and report["status"] == "completed" and
                            report["caller_check_passed"] and report["independent_check_passed"] and
                            report["file_changed"] and report["no_commit"] and not result.stderr)
    except (OSError, ValueError, subprocess.SubprocessError):
        report["runner_error"] = "fixture_or_execution_failed"
    if report["passed"] and args.cleanup_success:
        shutil.rmtree(scratch)
        report["scratch_removed"] = True
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
