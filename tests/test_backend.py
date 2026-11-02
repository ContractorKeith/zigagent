import json
import os
import pty
import subprocess
import time

from harness import BINARY, CliCase


class BackendTests(CliCase):
    def run_fake(self, scenario="success", *options, input=b"", prompt="literal task"):
        self.env["ZIGAGENT_TEST_SCENARIO"] = scenario
        args = ["run", "--json", "--model", "test-model", "--codex", str(self.fake), *options]
        if prompt is not None:
            args.append(prompt)
        p = self.invoke(*args, input=input)
        self.assertEqual(p.stderr, b"")
        self.assertEqual(p.stdout.count(b"\n"), 1)
        return p, json.loads(p.stdout)

    def assert_failure(self, scenario, error, code=1, *options):
        p, v = self.run_fake(scenario, *options)
        self.assertEqual(p.returncode, code, v)
        self.assertEqual(v["error"]["code"], error, v)
        self.assertEqual(v["status"], "timed_out" if code == 124 else "failed")
        return v

    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_missing_backend(self):
        p, v = self.run_fake("success", "--codex", str(self.root / "absent"))
        self.assertEqual(p.returncode, 3)
        self.assertEqual(v["error"]["code"], "backend_missing")
        self.assertFalse(self.log.exists())
        for name, mode in (("not-executable", 0o644), ("invalid-executable", 0o755)):
            path = self.root / name
            path.write_text("not an executable\n")
            path.chmod(mode)
            p, v = self.run_fake("success", "--codex", str(path))
            self.assertEqual(p.returncode, 3, v)
            self.assertEqual(v["error"]["code"], "backend_incompatible")

    def test_version_variants(self):
        for version in ("0.166.0", "codex-cli 0.166.1", "codex-cli 0.165.0",
                        "codex-cli 0.166.0-beta", "codex-cli 0.166.0 extra", "codex-cli 00.166.0",
                        "codex-cli 0.166.0\nnoise", "", "codex-cli 0.167.0"):
            with self.subTest(version=version):
                self.env["ZIGAGENT_TEST_VERSION"] = version
                self.assert_failure("success", "backend_incompatible", 3)
                self.assertEqual(self.records()[-1], ["--version"])
        self.env["ZIGAGENT_TEST_VERSION"] = "codex-cli 0.166.0\r\n"
        self.assertEqual(self.run_fake()[0].returncode, 0)

    def test_version_probe_failures(self):
        for scenario in ("version_failure", "version_flood"):
            self.assert_failure(scenario, "backend_incompatible", 3)

    def test_missing_capability(self):
        self.assert_failure("missing_capability", "backend_capability", 3)
        self.assertEqual(self.records(), [["--version"], ["exec", "--help"]])

    def test_auth_variations(self):
        for scenario, error in (("logged_out", "authentication_required"),
                                ("api_key", "authentication_failed"),
                                ("auth_failure", "authentication_failed"),
                                ("auth_wrong_exit", "authentication_failed"),
                                ("auth_unknown", "authentication_failed"),
                                ("auth_ambiguous", "authentication_failed"),
                                ("auth_false_logged_out", "authentication_failed"),
                                ("auth_flood", "authentication_failed")):
            with self.subTest(scenario=scenario):
                self.assert_failure(scenario, error, 4)
                self.assertEqual(self.records()[-1], ["login", "status"])
        self.assertEqual(self.run_fake("auth_stdout")[0].returncode, 0)

    def test_auth_tiny_retention_still_recognizes_status(self):
        self.assertEqual(self.run_fake("success", "--output-limit", "1")[0].returncode, 0)
        self.assert_failure("auth_failure", "authentication_failed", 4, "--output-limit", "1")

    def test_exact_argv_config_preservation_and_literal_data(self):
        context = self.root / 'context " ; $(literal)'
        context.mkdir()
        config = self.workspace / ".codex"
        config.mkdir()
        sentinel = config / "config.toml"
        sentinel.write_text('# synthetic sentinel\nmodel="do-not-change"\n')
        before = sentinel.read_bytes()
        model = 'model " ; $(literal)'
        self.env.update(OPENAI_API_KEY="synthetic-do-not-inherit", CODEX_API_KEY="synthetic-do-not-inherit")
        p, v = self.run_fake("success", "--model", model, "--workspace", str(self.workspace),
                             "--add-dir", str(context), "--add-dir", context.name,
                             input=b"must not be consumed", prompt='task " ; $(literal)\n☃')
        self.assertEqual(p.returncode, 0, v)
        self.assertEqual(self.records(), [
            ["--version"], ["exec", "--help"], ["login", "status"],
            ["exec", "--json", "--ephemeral", "--color", "never", "--ignore-user-config",
             "--ignore-rules", "--dangerously-bypass-approvals-and-sandbox", "-c",
             'forced_login_method="chatgpt"', "--disable", "hooks", "--disable", "plugins",
             "--disable", "apps", "--disable", "memories", "--model", model, "--cd",
             str(self.workspace.resolve()), "--add-dir", str(context.resolve()),
             "--add-dir", str(context.resolve()), "-"]])
        self.assertEqual(sentinel.read_bytes(), before)
        self.assertEqual(self.log.with_name(self.log.name + ".stdin").read_text(), 'task " ; $(literal)\n☃')
        self.assertEqual(json.loads(self.log.with_name(self.log.name + ".env").read_text()),
                         {"OPENAI_API_KEY": False, "CODEX_API_KEY": False})

    def test_prompt_stdin_semantics(self):
        for prompt, expected in ((None, b"pipe prompt"), ("-", b"pipe prompt"), ("argument", b"argument")):
            p, v = self.run_fake(input=b"pipe prompt", prompt=prompt)
            self.assertEqual(p.returncode, 0, v)
            self.assertEqual(self.log.with_name(self.log.name + ".stdin").read_bytes(), expected)

    def test_prompt_stdin_bounds_and_encoding(self):
        for data in (b"", b"x" * (1024 * 1024 + 1), b"\xff", b"null\0byte"):
            with self.subTest(size=len(data)):
                p, v = self.run_fake(input=data, prompt="-")
                self.assertEqual(p.returncode, 2, v)
                self.assertEqual(v["error"]["code"], "usage_error")
                self.assertFalse(self.log.exists())
        p, v = self.run_fake(input=b"x" * (1024 * 1024), prompt="-")
        self.assertEqual(p.returncode, 0, v)
        self.assertEqual(self.log.with_name(self.log.name + ".stdin").stat().st_size, 1024 * 1024)
        p, v = self.run_fake("reject_stdin", input=b"x" * (1024 * 1024), prompt="-")
        self.assertEqual(p.returncode, 1, v)
        self.assertEqual(v["error"]["code"], "backend_failed")

    def test_tty_prompt_does_not_wait(self):
        master, slave = pty.openpty()
        try:
            p = subprocess.run([str(BINARY), "run", "--json", "--model", "m", "--codex", str(self.fake)],
                               stdin=slave, capture_output=True, cwd=self.root, env=self.env, timeout=3)
            self.assertEqual(p.returncode, 2)
            self.assertEqual(json.loads(p.stdout)["error"]["code"], "usage_error")
            self.assertFalse(self.log.exists())
        finally:
            os.close(master)
            os.close(slave)

    def test_completion_success(self):
        for scenario in ("success", "unknown", "chunked"):
            p, v = self.run_fake(scenario)
            self.assertEqual(p.returncode, 0, v)
            self.assertEqual(v["status"], "completed")
            self.assertEqual(v["summary"], "synthetic completion")
            self.assertEqual(v["verification"], {"status": "not_requested", "exit_code": None,
                                                  "output": "", "truncated": False})
            self.assertIsNone(v["error"])

    def test_protocol_negative_cases(self):
        for scenario in ("malformed", "partial", "empty", "invalid_utf8", "bad_item",
                         "missing_completion", "duplicate_completion", "trailing_malformed"):
            with self.subTest(scenario=scenario):
                self.assert_failure(scenario, "protocol_error")

    def test_warning_item_does_not_override_completed_turn(self):
        p, value = self.run_fake("warning")
        self.assertEqual(p.returncode, 0, value)
        self.assertEqual(value["status"], "completed")
        self.assertEqual(value["summary"], "synthetic completion")
        self.assertIsNone(value["error"])

    def test_failure_events_and_nonzero_exit(self):
        for scenario in ("failed", "turn_failed", "error_event"):
            with self.subTest(scenario=scenario):
                self.assert_failure(scenario, "backend_failed")

    def test_intermediate_tool_failures_do_not_override_completed_turn(self):
        for scenario in ("recovered_tool", "tool_failed", "patch_failed"):
            p, value = self.run_fake(scenario)
            self.assertEqual(p.returncode, 0, value)
            self.assertEqual(value["status"], "completed")
            self.assertEqual(value["verification"]["status"], "not_requested")
            self.assertIsNone(value["error"])
            if scenario == "recovered_tool":
                self.assertEqual(value["summary"], "fixed and retested")

    def test_event_limit(self):
        self.assert_failure("large_event", "event_too_large", 1, "--event-limit", "100")
        self.assert_failure("success", "event_too_large", 1, "--event-limit", "1")

    def test_concurrent_drain_and_bounded_retention(self):
        p, v = self.run_fake("saturation", "--output-limit", "17")
        self.assertEqual(p.returncode, 0, v)
        self.assertEqual(v["diagnostics"], {"output": "x" * 17, "truncated": True})
        self.assertEqual(len(v["summary"].encode()), 17)
        self.assertTrue(v["summary_truncated"])
        self.assertLess(len(p.stdout), 1024)

    def test_truncated_unicode_and_diagnostics(self):
        p, v = self.run_fake("summary_limit", "--output-limit", "4")
        self.assertEqual(p.returncode, 0, v)
        self.assertTrue(v["summary_truncated"])
        self.assertLessEqual(len(v["summary"].encode()), 4)
        p, v = self.run_fake("diagnostic_utf8", "--output-limit", "4")
        self.assertEqual(p.returncode, 0, v)
        self.assertEqual(v["diagnostics"], {"output": "?☃", "truncated": True})

    def test_all_workloads_have_deadlines(self):
        for scenario in ("version_hang", "help_hang", "auth_hang", "exec_hang", "closed_pipes_hang",
                         "descendant_pipes"):
            with self.subTest(scenario=scenario):
                start = time.monotonic()
                self.assert_failure(scenario, "timed_out", 124, "--timeout", "1")
                self.assertLess(time.monotonic() - start, 4)
