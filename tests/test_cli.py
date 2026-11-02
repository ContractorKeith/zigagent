import json
import subprocess
from harness import BINARY, CliCase


class ContractTests(CliCase):
    def test_help_and_version_without_backend(self):
        self.env["PATH"] = str(self.root)
        self.env["ZIGAGENT_MODEL"] = "\udcff"  # ignored by help/version
        for args, expected in [(("--help",), b"Usage:"), (("--version",), b"zigagent 0.1.0-dev\n"),
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
            self.envelope(self.invoke("run", "--json", "--model", "m", "--timeout", value,
                                      "--login-timeout", value, "hello"))
        for value in ("1", "16777216"):
            self.envelope(self.invoke("run", "--json", "--model", "m", "--output-limit", value,
                                      "--event-limit", value, "hello"))

    def test_model_precedence_and_escaping(self):
        model = 'quoted"\\\n\t☃'
        self.env["ZIGAGENT_MODEL"] = "environment"
        v = self.envelope(self.invoke("run", "--model", model, "--json", "hello"))
        self.assertEqual(v["backend"]["model"], model)
        v = self.envelope(self.invoke("run", "--json", "hello"))
        self.assertEqual(v["backend"]["model"], "environment")
        self.env["ZIGAGENT_MODEL"] = ""
        self.envelope(self.invoke("run", "--json", "hello"), 2, "usage_error")
        self.envelope(self.invoke("run", "--model", "override", "--json", "hello"))

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
        self.envelope(self.invoke("run", "--model", "m", "--json", "--workspace", str(self.workspace),
                                  "--add-dir", str(context), "--add-dir", "context", "hello"))
        file = self.root / "file"
        file.write_text("fixture", encoding="utf-8")
        for flag in ("--workspace", "--add-dir"):
            for path in (str(file), str(self.root / "missing")):
                with self.subTest(flag=flag, path=path):
                    self.envelope(self.invoke("run", "--model", "m", "--json", flag, path, "hello"), 2, "usage_error")

    def test_quoted_input_is_not_shell_syntax(self):
        prompt = 'write "two words"; touch SHOULD_NOT_EXIST; $(touch ALSO_NOT)\n☃'
        self.envelope(self.invoke("run", "--model", "m", "--json", "--codex", str(self.fake), prompt))
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())
        self.assertFalse((self.root / "ALSO_NOT").exists())
        self.assertFalse(self.log.exists())

    def test_delimiter(self):
        p = self.invoke("run", "--model", "m", "--", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, b"")
        self.assertIn(b"unimplemented", p.stderr)
        self.envelope(self.invoke("run", "--json", "--model", "m", "--", "-prompt"))

    def test_check_is_not_run(self):
        v = self.envelope(self.invoke("run", "--model", "m", "--json", "--check", "touch SHOULD_NOT_EXIST", "hello"))
        self.assertEqual(v["verification"]["status"], "not_run")
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    def test_execution_is_honestly_unimplemented(self):
        v = self.envelope(self.invoke("run", "--model", "m", "--json", "--codex", str(self.fake), "hello"))
        self.assertEqual(v["verification"]["status"], "not_requested")
        self.assertFalse(self.log.exists())
        p = self.invoke("login", "--no-input", "--login-timeout", "1")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, b"")
        self.assertIn(b"unimplemented", p.stderr)
        self.assertFalse(self.log.exists())

    def test_login_rejects_run_flags(self):
        for args in [("--model", "m"), ("--json",), ("--timeout", "1"), ("--login-timeout", "86401")]:
            p = self.invoke("login", *args)
            self.assertEqual(p.returncode, 2)
            if "--json" in args:
                self.envelope(p, 2, "usage_error")
            else:
                self.assertEqual(p.stdout, b"")

    def test_stdin_selection_does_not_wait_in_m0(self):
        for suffix in ((), ("-",), ("argument",)):
            self.envelope(self.invoke("run", "--model", "m", "--json", *suffix, input=b"synthetic stdin"))
        p = subprocess.Popen([str(BINARY), "run", "--model", "m", "--json"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=self.root, env=self.env)
        try:
            # Keep stdin open without writing: M0 must still return promptly.
            p.wait(timeout=5)
            self.envelope(subprocess.CompletedProcess(p.args, p.returncode, p.stdout.read(), p.stderr.read()))
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdin.close()
            p.stdout.close()
            p.stderr.close()

    def test_output_limit_does_not_limit_model(self):
        v = self.envelope(self.invoke("run", "--json", "--model", "long", "--output-limit", "1", "hello"))
        self.assertEqual(v["backend"]["model"], "long")

    def test_plain_respects_no_color(self):
        self.env.update(NO_COLOR="1", TERM="dumb")
        p = self.invoke("run", "--model", "m", "hello")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, b"")
        self.assertNotIn(b"\x1b", p.stderr)

    def test_fake_backend_seam(self):
        # Exercise the fixture itself. M0 never invokes a backend from zigagent.
        for args in [("--version",), ("login", "status"), ("exec", "quoted prompt")]:
            p = subprocess.run([str(self.fake), *args], env=self.env, cwd=self.root,
                               capture_output=True, timeout=5)
            self.assertEqual(p.returncode, 0, p.stderr)
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(records, [["--version"], ["login", "status"], ["exec", "quoted prompt"]])
