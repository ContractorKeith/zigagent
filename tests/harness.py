"""Compiled-process fixtures shared by black-box tests; all writes are disposable."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "zig-out/bin/zigagent"


class CliCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zigagent-m0-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace with spaces"
        self.workspace.mkdir()
        self.fake = self.root / "fake codex"
        shutil.copyfile(ROOT / "tests/fake_codex.py", self.fake)
        self.fake.chmod(0o755)
        self.log = self.root / "fake-argv.jsonl"
        self.env = os.environ.copy()
        self.env.pop("ZIGAGENT_MODEL", None)
        self.env["ZIGAGENT_TEST_LOG"] = str(self.log)
        self.env["ZIGAGENT_TEST_SCENARIO"] = "success"

    def invoke(self, *args, input=b"", env=None):
        return subprocess.run([str(BINARY), *args], input=input, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, cwd=self.root, env=env or self.env,
                              timeout=5)

    def envelope(self, completed, code=1, error="unimplemented"):
        self.assertEqual(completed.returncode, code, completed.stderr)
        self.assertEqual(completed.stderr, b"")
        # json.loads rejects concatenated envelopes and any non-JSON chatter.
        value = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(completed.stdout.count(b"\n"), 1)
        self.assertEqual(set(value), {"schema_version", "status", "summary", "verification",
                                    "elapsed_ms", "error", "diagnostics", "summary_truncated", "backend"})
        self.assertEqual(value["schema_version"], 1)
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["error"]["code"], error)
        self.assertIsInstance(value["error"]["message"], str)
        self.assertEqual(value["summary"], "")
        self.assertFalse(value["summary_truncated"])
        self.assertIsInstance(value["elapsed_ms"], int)
        self.assertGreaterEqual(value["elapsed_ms"], 0)
        self.assertEqual(value["diagnostics"], {"output": "", "truncated": False})
        self.assertEqual(value["backend"]["name"], "codex")
        self.assertIsNone(value["backend"]["version"])
        self.assertIsNone(value["verification"]["exit_code"])
        self.assertEqual(value["verification"]["output"], "")
        self.assertFalse(value["verification"]["truncated"])
        return value
