import json
import subprocess
from harness import BINARY, CliCase


class ContractTests(CliCase):
    def success(self, completed):
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(completed.stderr, b"")
        value = json.loads(completed.stdout)
        self.assertEqual(completed.stdout.count(b"\n"), 1)
        self.assertEqual(value["status"], "completed")
        self.assertIsNone(value["error"])
        self.assertEqual(value["backend"]["version"], "0.166.0")
        self.assertEqual(value["verification"]["status"], "not_requested")
        return value

    def test_help_and_version_without_backend(self):
        self.env["PATH"] = str(self.root)
        self.env["ZIGAGENT_MODEL"] = "\udcff"  # ignored by help/version
        for args, expected in [(("--help",), b"Usage:"), (("--version",), b"zigagent 0.1.0\n"),
                               (("run", "--help"), b"--codex"), (("login", "--help"), b"--login-timeout")]:
            with self.subTest(args=args):
                p = self.invoke(*args)
                self.assertEqual(p.returncode, 0)
                self.assertIn(expected, p.stdout)
                self.assertEqual(p.stderr, b"")

    def test_run_help_lists_all_options(self):
        text = self.invoke("run", "--help").stdout
        for option in ("model", "workspace", "add-dir", "check", "json", "no-input", "timeout",
                       "login-timeout", "output-limit", "event-limit", "codex", "help"):
            self.assertIn(("--" + option).encode(), text)

    def test_usage_plain(self):
        for args in [(), ("wat",), ("run",), ("login", "prompt"), ("--version", "extra")]:
            with self.subTest(args=args):
                p = self.invoke(*args)
                self.assertEqual(p.returncode, 2)
                self.assertEqual(p.stdout, b"")
                self.assertIn(b"usage_error", p.stderr)

    def test_usage_json_even_before_json_flag(self):
        for args in [("--unknown",), ("--model",), ("--model", "m", "one", "two"),
                     ("--model", "m", ""), ("--model", ""), ("--model", "m", "-unknown")]:
            with self.subTest(args=args):
                self.envelope(self.invoke("run", *args, "--json"), 2, "usage_error")

    def test_missing_values(self):
        for flag in ("model", "workspace", "add-dir", "check", "timeout", "login-timeout", "output-limit", "event-limit", "codex"):
            with self.subTest(flag=flag):
                self.envelope(self.invoke("run", "--json", "--model", "m", "--" + flag), 2, "usage_error")

    def test_numeric_invalid_bounds(self):
        for flag, maximum in [("timeout", 86400), ("login-timeout", 86400),
                              ("output-limit", 16777216), ("event-limit", 16777216)]:
            for value in ("0", "-1", "+1", "1.5", " 1", "1 ", "", "NaN", str(maximum + 1),
                          "4294967296", "999999999999999999999999999999"):
                with self.subTest(flag=flag, value=value):
                    self.envelope(self.invoke("run", "--json", "--model", "m", "--" + flag, value, "hello"), 2, "usage_error")

    def test_numeric_valid_bounds(self):
        for value in ("1", "86400"):
            # Parsing boundaries must not require Python/backend startup within 1s.
            self.envelope(self.invoke("run", "--json", "--model", "m", "--timeout", value,
                                      "--login-timeout", value, "--codex", str(self.root / "absent"),
                                      "hello"), 3, "backend_missing")
        for value in ("1", "16777216"):
            self.success(self.invoke("run", "--json", "--model", "m", "--output-limit", value,
                                      "--event-limit", "16777216", "hello"))

    def test_model_precedence_and_escaping(self):
        model = 'quoted"\\\n\t☃'
        self.env["ZIGAGENT_MODEL"] = "environment"
        v = self.success(self.invoke("run", "--model", model, "--json", "hello"))
        self.assertEqual(v["backend"]["model"], model)
        v = self.success(self.invoke("run", "--json", "hello"))
        self.assertEqual(v["backend"]["model"], "environment")
        self.env["ZIGAGENT_MODEL"] = ""
        self.envelope(self.invoke("run", "--json", "hello"), 2, "usage_error")
        self.success(self.invoke("run", "--model", "override", "--json", "hello"))

    def test_missing_model(self):
        self.envelope(self.invoke("run", "--json", "hello"), 2, "usage_error")

    def test_invalid_utf8(self):
        for args in [(b"--model", b"\xff", b"hello"), (b"--model", b"m", b"\xfe")]:
            self.envelope(self.invoke(b"run", b"--json", *args), 2, "usage_error")
        self.env["ZIGAGENT_MODEL"] = "\udcff"
        self.envelope(self.invoke("run", "--json", "hello"), 2, "usage_error")

    def test_paths(self):
        context = self.root / "context"
        context.mkdir()
        self.success(self.invoke("run", "--model", "m", "--json", "--workspace", str(self.workspace),
                                  "--add-dir", str(context), "--add-dir", "context", "hello"))
        file = self.root / "file"
        file.write_text("fixture", encoding="utf-8")
        for flag in ("--workspace", "--add-dir"):
            for path in (str(file), str(self.root / "missing")):
                with self.subTest(flag=flag, path=path):
                    self.envelope(self.invoke("run", "--model", "m", "--json", flag, path, "hello"), 2, "usage_error")

    def test_quoted_input_is_not_shell_syntax(self):
        prompt = 'write "two words"; touch SHOULD_NOT_EXIST; $(touch ALSO_NOT)\n☃'
        self.success(self.invoke("run", "--model", "m", "--json", "--codex", str(self.fake), prompt))
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())
        self.assertFalse((self.root / "ALSO_NOT").exists())
        self.assertEqual((self.root / "fake-argv.jsonl.stdin").read_text(), prompt)

    def test_every_context_directory_is_validated(self):
        context = self.root / "valid-context"
        context.mkdir()
        self.envelope(self.invoke("run", "--model", "m", "--json",
                                  "--add-dir", str(context), "--add-dir",
                                  str(self.root / "missing-context"), "hello"), 2, "usage_error")

    def test_option_like_paths_use_explicit_relative_prefix(self):
        context = self.root / "--context"
        context.mkdir()
        for flag in ("--workspace", "--add-dir"):
            self.success(self.invoke("run", "--model", "m", "--json",
                                      flag, "./--context", "hello"))
            self.envelope(self.invoke("run", "--model", "m", "--json",
                                      flag, "--context", "hello"), 2, "usage_error")

    def test_subcommand_help_short_circuits_remaining_arguments(self):
        for args in [("run", "--help", "--bogus"),
                     ("run", "--help", "--model"),
                     ("run", "--help", "--timeout", "0"),
                     ("login", "--help", "--login-timeout", "86401")]:
            p = self.invoke(*args)
            self.assertEqual(p.returncode, 0)
            self.assertIn(b"Usage:", p.stdout)
            self.assertEqual(p.stderr, b"")

    def test_delimiter(self):
        p = self.invoke("run", "--model", "m", "--", "--json")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, b"synthetic completion\n")
        self.assertEqual(p.stderr, b"")
        self.success(self.invoke("run", "--json", "--model", "m", "--", "-prompt"))

    def test_check_runs_after_completion(self):
        p = self.invoke("run", "--model", "m", "--json", "--workspace", str(self.workspace),
                        "--check", "printf checked", "hello")
        self.assertEqual(p.returncode, 0, p.stdout)
        v = json.loads(p.stdout)
        self.assertEqual(v["verification"], {"status": "passed", "exit_code": 0,
                                              "output": "checked", "truncated": False})

    def test_execution_and_login_milestone_boundary(self):
        v = self.success(self.invoke("run", "--model", "m", "--json", "--codex", str(self.fake), "hello"))
        self.assertEqual(v["verification"]["status"], "not_requested")
        self.assertTrue(self.log.exists())
        self.log.unlink()
        p = self.invoke("login", "--no-input", "--login-timeout", "1")
        self.assertEqual(p.returncode, 4)
        self.assertEqual(p.stdout, b"")
        self.assertIn(b"authentication_required", p.stderr)
        self.assertFalse(self.log.exists())

    def test_login_rejects_run_flags(self):
        for args in [("--model", "m"), ("--json",), ("--timeout", "1"), ("--login-timeout", "86401")]:
            p = self.invoke("login", *args)
            self.assertEqual(p.returncode, 2)
            if "--json" in args:
                self.envelope(p, 2, "usage_error")
            else:
                self.assertEqual(p.stdout, b"")

    def test_stdin_selection_is_bounded(self):
        for suffix in ((), ("-",), ("argument",)):
            self.success(self.invoke("run", "--model", "m", "--json", *suffix, input=b"synthetic stdin"))
        p = subprocess.Popen([str(BINARY), "run", "--model", "m", "--json", "--timeout", "1"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=self.root, env=self.env)
        try:
            p.wait(timeout=4)
            value = json.loads(p.stdout.read())
            self.assertEqual(p.returncode, 124)
            self.assertEqual(value["error"]["code"], "timed_out")
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdin.close()
            p.stdout.close()
            p.stderr.close()

    def test_output_limit_does_not_limit_model(self):
        v = self.success(self.invoke("run", "--json", "--model", "long", "--output-limit", "1", "hello"))
        self.assertEqual(v["backend"]["model"], "long")

    def test_plain_respects_no_color(self):
        self.env.update(NO_COLOR="1", TERM="dumb")
        p = self.invoke("run", "--model", "m", "hello")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, b"synthetic completion\n")
        self.assertNotIn(b"\x1b", p.stdout + p.stderr)

    def test_fake_backend_seam(self):
        # Exercise the fixture directly as well as through zigagent.
        for args in [("--version",), ("login", "status"), ("exec", "quoted prompt")]:
            p = subprocess.run([str(self.fake), *args], env=self.env, cwd=self.root,
                               input=b"", capture_output=True, timeout=5)
            self.assertEqual(p.returncode, 0, p.stderr)
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(records, [["--version"], ["login", "status"], ["exec", "quoted prompt"]])
