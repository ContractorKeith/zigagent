"""Release tooling at its command/process seam; all mutations use scratch copies."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

from harness import ROOT, BINARY

sys.path.insert(0, str(ROOT / "scripts"))
import package


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zigagent-package-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.name = package.archive_name(package.native_target())
        shutil.copyfile(ROOT / "dist" / self.name, self.directory / self.name)
        shutil.copyfile(ROOT / "dist/SHA256SUMS", self.directory / "SHA256SUMS")

    def validate(self, success=False, both=False):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/package.py"),
                                 "validate", "--directory", str(self.directory),
                                 *(["--all"] if both else [])], capture_output=True, timeout=15)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())

    def rewrite(self, mutate):
        archive = self.directory / self.name
        with tarfile.open(archive) as tar:
            entries = [(m, tar.extractfile(m).read()) for m in tar.getmembers()]
        entries = mutate(entries)
        with tarfile.open(archive, "w:gz") as tar:
            for member, data in entries:
                tar.addfile(member, io.BytesIO(data) if member.isfile() else None)
        self.manifest()

    def manifest(self):
        digest = hashlib.sha256((self.directory / self.name).read_bytes()).hexdigest()
        (self.directory / "SHA256SUMS").write_text(f"{digest}  {self.name}\n")

    def test_native_archive_and_checksum_roundtrip(self):
        self.validate(success=True)

    def test_corruption_missing_archive_and_missing_target(self):
        self.validate(both=True)
        archive = self.directory / self.name
        original = archive.read_bytes()
        archive.write_bytes(original[:100])
        self.validate()
        archive.unlink()
        self.validate()

    def test_gzip_trailer_is_validated_with_matching_checksum(self):
        archive = self.directory / self.name
        original = archive.read_bytes()
        variants = [original[:-n] for n in (1, 8, 20)]
        variants.append(original[:-8] + bytes([original[-8] ^ 1]) + original[-7:])
        for data in variants:
            with self.subTest(size=len(data)):
                archive.write_bytes(data)
                self.manifest()
                self.validate()

    def test_manifest_rejects_wrong_missing_duplicate_and_unsafe_names(self):
        path = self.directory / "SHA256SUMS"
        original = path.read_text()
        for text in ("", original + original, "0" * 64 + "  ../escape\n",
                     original.replace(self.name, "wrong.tar.gz"),
                     "0" * 64 + "  " + self.name + "\n"):
            with self.subTest(text=text):
                path.write_text(text)
                self.validate()

    def test_extra_archive_rejected(self):
        (self.directory / "wrong.tar.gz").write_bytes(b"wrong")
        self.validate()

    def test_generated_outputs_do_not_follow_symlinks(self):
        for name, command in (('SHA256SUMS', 'manifest'), (self.name, 'build')):
            with self.subTest(output=name):
                sentinel = self.directory / 'sentinel'
                sentinel.write_text('leave alone')
                path = self.directory / name
                path.unlink()
                path.symlink_to(sentinel)
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/package.py'),
                                         command, '--directory', str(self.directory)],
                                        capture_output=True, timeout=120)
                self.assertEqual(sentinel.read_text(), 'leave alone')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(path.is_symlink())
                self.validate(success=True)

    def test_rejects_member_paths_types_modes_duplicates_and_missing(self):
        archive = self.directory / self.name
        original = archive.read_bytes()
        def path(entries):
            entries[0][0].name = "../escape"
            return entries
        def link(entries):
            entries[0][0].type = tarfile.SYMTYPE
            entries[0][0].linkname = "/etc/passwd"
            return entries
        def mode(entries):
            entries[0][0].mode = 0o644
            return entries
        for mutate in (path, link, mode, lambda e: e + [e[0]], lambda e: e[1:]):
            with self.subTest(mutate=mutate):
                archive.write_bytes(original)
                self.rewrite(mutate)
                self.validate()
        self.assertFalse((self.directory.parent / "escape").exists())

    def test_wrong_architecture_and_version_rejected_with_valid_checksum(self):
        archive = self.directory / self.name
        original = archive.read_bytes()
        def arch(entries):
            member, data = entries[0]
            entries[0] = member, b"bad!" + data[4:]
            return entries
        def version(entries):
            member, data = entries[0]
            self.assertIn(b"zigagent 0.1.0", data)
            entries[0] = member, data.replace(b"zigagent 0.1.0", b"zigagent 9.9.9")
            return entries
        for mutate in (arch, version):
            with self.subTest(mutate=mutate):
                archive.write_bytes(original)
                self.rewrite(mutate)
                self.validate()


class RunnerTests(unittest.TestCase):
    def run_runner(self, *args, env=None):
        return subprocess.run([sys.executable, str(ROOT / "scripts/live-check.py"),
                               *args], capture_output=True, timeout=40, env=env)

    def test_live_runner_requires_explicit_opt_in_and_model(self):
        for args in ((), ("--model", "test"), ("--test-mode",)):
            result = self.run_runner(*args)
            self.assertEqual(result.returncode, 2)

    def test_synthetic_fix_has_both_checks_versions_and_hashes(self):
        result = self.run_runner("--test-mode", "--model", "test-model", "--cleanup-success")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["evidence"], "synthetic")
        self.assertTrue(report["file_changed"])
        self.assertTrue(report["no_commit"])
        self.assertTrue(report["caller_check_passed"])
        self.assertTrue(report["independent_check_passed"])
        self.assertEqual(report["codex_version"], "0.166.0")
        self.assertEqual(report["binary_sha256"], package.sha256(BINARY))
        self.assertFalse(Path(report["scratch"]).exists())
        self.assertNotIn("synthetic completion", result.stdout.decode())

    def test_runner_ignores_inherited_git_repository_overrides(self):
        with tempfile.TemporaryDirectory(prefix="zigagent-git-override-") as temp:
            unrelated = Path(temp) / "unrelated"
            unrelated.mkdir()
            git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            git_env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
            subprocess.run(["git", "-c", "init.templateDir=", "init", "-q", str(unrelated)],
                           env=git_env, check=True)
            marker = unrelated / "sentinel"
            marker.write_text("leave alone")
            git_env.update(GIT_DIR=str(unrelated / ".git"), GIT_WORK_TREE=str(unrelated))
            result = subprocess.run([sys.executable, str(ROOT / "scripts/live-check.py"),
                                     "--test-mode", "--model", "test-model", "--cleanup-success"],
                                    env=git_env, capture_output=True, timeout=40)
            report = json.loads(result.stdout)
            try:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(report["passed"])
                self.assertEqual(marker.read_text(), "leave alone")
                self.assertEqual(set(p.name for p in unrelated.iterdir()), {".git", "sentinel"})
            finally:
                scratch = Path(report["scratch"])
                if scratch.exists():
                    shutil.rmtree(scratch)

    def test_optimized_python_rejects_incorrect_edit(self):
        with tempfile.TemporaryDirectory(prefix="zigagent-optimized-check-") as temp:
            root = Path(temp)
            for name in ('scripts/live-check.py', 'scripts/package.py',
                         'src/cli.zig', 'tests/fake_codex.py'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            fake = root / 'tests/fake_codex.py'
            fake.write_text(fake.read_text().replace('return a + b', 'return a * b'))
            env = dict(os.environ, PYTHONOPTIMIZE='1', PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, str(root / 'scripts/live-check.py'),
                                     '--test-mode', '--model', 'test-model',
                                     '--binary', str(BINARY)], env=env,
                                    capture_output=True, timeout=40)
            report = json.loads(result.stdout)
            try:
                self.assertEqual(result.returncode, 1, report)
                self.assertTrue(report['file_changed'])
                self.assertFalse(report['caller_check_passed'])
                self.assertFalse(report['independent_check_passed'])
                self.assertFalse(report['passed'])
            finally:
                shutil.rmtree(report['scratch'])

    def test_runner_failure_preserves_owned_scratch_without_raw_output(self):
        with tempfile.TemporaryDirectory(prefix="zigagent-runner-failure-") as temp:
            fake = Path(temp) / "broken-wrapper"
            fake.write_text("#!/bin/sh\necho 'SECRET synthetic private diagnostic' >&2\nexit 1\n")
            fake.chmod(0o755)
            result = self.run_runner("--test-mode", "--model", "test-model", "--binary", str(fake),
                                     "--cleanup-success")
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            scratch = Path(report["scratch"])
            try:
                self.assertTrue(scratch.is_dir())
                self.assertFalse(report["passed"])
                self.assertNotIn(b"SECRET", result.stdout + result.stderr)
            finally:
                shutil.rmtree(scratch)

    def test_malformed_nested_result_reports_json_failure(self):
        with tempfile.TemporaryDirectory(prefix='zigagent-malformed-wrapper-') as temp:
            fake = Path(temp) / 'wrapper'
            for output in (42, None, [], {}):
                with self.subTest(output=output):
                    value = {'status': 'completed', 'backend': {'version': '0.166.0'},
                             'verification': {'status': 'passed', 'exit_code': 0,
                                              'output': output}}
                    fake.write_text('#!' + sys.executable + '\nimport sys\n'
                                    'print("zigagent 0.1.0" if "--version" in sys.argv '
                                    'else ' + repr(json.dumps(value)) + ')\n')
                    fake.chmod(0o755)
                    result = self.run_runner('--test-mode', '--model', 'test-model',
                                             '--binary', str(fake), '--cleanup-success',
                                             env=dict(os.environ, TMPDIR=temp))
                    report = json.loads(result.stdout)
                    try:
                        self.assertEqual(result.returncode, 1)
                        self.assertEqual(result.stderr, b'')
                        self.assertFalse(report['passed'])
                        self.assertEqual(report['runner_error'], 'fixture_or_execution_failed')
                        self.assertTrue(Path(report['scratch']).is_dir())
                    finally:
                        shutil.rmtree(report['scratch'])

    def test_benchmark_reports_wrapper_only_metrics_without_codex(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/benchmark.py"),
                                 "--samples", "5"], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["binary_sha256"], package.sha256(BINARY))
        self.assertEqual(report["binary_bytes"], BINARY.stat().st_size)
        for flag in ("--help", "--version"):
            self.assertGreater(report["metrics"][flag]["median_ms"], 0)
            self.assertGreaterEqual(report["metrics"][flag]["peak_rss_bytes"], 0)
