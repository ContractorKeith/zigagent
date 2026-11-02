"""Caller verification through the compiled CLI; synthetic scratch work only."""
import json
import os
import shlex
import signal
import subprocess
import sys
import time

from harness import BINARY, CliCase


class CheckTests(CliCase):
    def args(self, command=None, *extra, plain=False):
        args = ['run', '--model', 'm', '--no-input', '--codex', str(self.fake),
                '--workspace', str(self.workspace)]
        if not plain:
            args.append('--json')
        if command is not None:
            args += ['--check', command]
        return [*args, *extra, 'task']

    def test_plain_reports_check_verdict_and_output(self):
        for command, code, verdict in [('printf checked', 0, b'passed'),
                                       ('printf broken; exit 7', 5, b'failed')]:
            p = self.invoke(*self.args(command, plain=True))
            self.assertEqual(p.returncode, code)
            self.assertIn(b'verification: ' + verdict, p.stdout + p.stderr)
            self.assertIn(b'checked' if code == 0 else b'broken', p.stdout + p.stderr)

    def test_edit_then_pass_fail_and_no_check(self):
        subprocess.run(['git', '-c', 'init.defaultBranch=main', 'init', '--quiet',
                        '--template=', str(self.workspace)], check=True)
        (self.workspace / 'preserved-edit').write_text('needs fix')
        subprocess.run(['git', '-C', str(self.workspace), 'add', 'preserved-edit'], check=True)
        self.env['ZIGAGENT_TEST_SCENARIO'] = 'edit'
        for command, code, status, exit_code in [
                (None, 0, 'not_requested', None),
                ('test "$(cat preserved-edit)" = "keep edits"; printf verified', 0, 'passed', 0),
                ('printf rejected >&2; exit 23', 5, 'failed', 23)]:
            with self.subTest(command=command):
                p = self.invoke(*self.args(command))
                v = json.loads(p.stdout)
                self.assertEqual(p.returncode, code, v)
                self.assertEqual(p.stderr, b'')
                self.assertEqual(p.stdout.count(b'\n'), 1)
                self.assertEqual(v['verification']['status'], status)
                self.assertEqual(v['verification']['exit_code'], exit_code)
                self.assertEqual(v['status'], 'failed' if code else 'completed')
                self.assertEqual(v['error']['code'] if code else v['error'], 'check_failed' if code else None)
                self.assertEqual((self.workspace / 'preserved-edit').read_text(), 'keep edits')
        self.assertEqual(v['verification']['output'], 'rejected')
        commits = subprocess.run(['git', '-C', str(self.workspace), 'rev-list', '--all', '--count'],
                                 capture_output=True, check=True)
        self.assertEqual(commits.stdout.strip(), b'0')
        diff = subprocess.run(['git', '-C', str(self.workspace), 'diff', '--', 'preserved-edit'],
                              capture_output=True, check=True)
        self.assertIn(b'+keep edits', diff.stdout)
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(sum(args[:2] == ['exec', '--json'] for args in records), 3)

    def test_check_stdin_is_eof_and_only_explicit_check_is_shell(self):
        malicious = '$(touch INJECTED); `touch ALSO_INJECTED`; "quoted"'
        workspace = self.root / malicious
        workspace.mkdir()
        args = self.args('if read x; then exit 9; fi; printf shell > explicit',
                         '--workspace', str(workspace), '--model', malicious,
                         '--add-dir', str(workspace))
        args[-1] = malicious
        p = self.invoke(*args, input=b'must not reach check\n')
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual((workspace / 'explicit').read_text(), 'shell')
        for directory in (workspace, self.root):
            self.assertFalse((directory / 'INJECTED').exists())
            self.assertFalse((directory / 'ALSO_INJECTED').exists())
        self.assertEqual(self.log.with_name(self.log.name + '.stdin').read_text(), malicious)

    def test_combined_output_tail_is_bounded_and_utf8_safe(self):
        program = ('import os,time; '
                   '[(os.write(1,b"a"*4096),os.write(2,b"b"*4096)) for _ in range(64)]; '
                   'time.sleep(.1); os.write(2,b"TAIL\\xff\\xe2\\x98\\x83")')
        command = shlex.join([sys.executable, '-c', program])
        p = self.invoke(*self.args(command, '--output-limit', '17'))
        v = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, v)
        output = v['verification']['output']
        self.assertEqual(len(output.encode()), 17)
        self.assertTrue(output.endswith('TAIL?☃'), output)
        self.assertTrue(v['verification']['truncated'])
        self.assertLess(len(p.stdout), 1024)
        p = self.invoke(*self.args(command, '--output-limit', '17', plain=True))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(b'[check output truncated]', p.stdout)
        self.assertIn('TAIL?☃'.encode(), p.stdout)
        p = self.invoke(*self.args('printf out; sleep .1; printf err >&2'))
        self.assertEqual(json.loads(p.stdout)['verification']['output'], 'outerr')

    def test_failure_matrix_never_starts_check_json_and_plain(self):
        cases = [
            ('success', ['--timeout', '0'], 2, 'usage_error'),
            ('success', ['--workspace', str(self.root / 'absent')], 2, 'usage_error'),
            ('success', ['--codex', str(self.root / 'absent')], 3, 'backend_missing'),
            ('version_failure', [], 3, 'backend_incompatible'),
            ('missing_capability', [], 3, 'backend_capability'),
            ('logged_out', [], 4, 'authentication_required'),
            ('auth_failure', [], 4, 'authentication_failed'),
            ('malformed', [], 1, 'protocol_error'),
            ('large_event', ['--event-limit', '100'], 1, 'event_too_large'),
            ('failed', [], 1, 'backend_failed'),
            ('exec_hang', ['--timeout', '1'], 124, 'timed_out')]
        for scenario, extra, code, error in cases:
            for plain in (False, True):
                with self.subTest(scenario=scenario, plain=plain):
                    self.env['ZIGAGENT_TEST_SCENARIO'] = scenario
                    p = self.invoke(*self.args('touch MUST_NOT_START', *extra, plain=plain))
                    self.assertEqual(p.returncode, code, (p.stdout, p.stderr))
                    self.assertFalse((self.workspace / 'MUST_NOT_START').exists())
                    if plain:
                        self.assertEqual(p.stdout, b'')
                        self.assertIn(error.encode(), p.stderr)
                    else:
                        self.assertEqual(p.stderr, b'')
                        self.assertEqual(p.stdout.count(b'\n'), 1)
                        v = json.loads(p.stdout)
                        self.assertEqual(v['error']['code'], error)
                        self.assertEqual(v['status'], 'timed_out' if code == 124 else 'failed')
                        self.assertEqual(v['verification']['status'], 'not_run')
                        self.assertIsNone(v['verification']['exit_code'])

    def test_exhausted_backend_budget_never_spawns_check(self):
        # Startup scheduling may exhaust the budget in the backend or at check
        # handoff. Both must time out without launching the caller check.
        self.fake.write_text("""#!/bin/sh
case "$1:$2" in
  --version:) printf '%s\\n' 'codex-cli 0.166.0' ;;
  exec:--help) printf '%s\\n' '--json --ephemeral --color --model --cd --add-dir --ignore-user-config --ignore-rules --dangerously-bypass-approvals-and-sandbox' ;;
  login:status) printf '%s\\n' 'Logged in using ChatGPT' ;;
  exec:--json)
    cat >/dev/null
    printf '%s\\n' '{"type":"item.completed","item":{"type":"agent_message","text":"synthetic completion"}}' '{"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0}}'
    sleep .95 ;;
  *) exit 1 ;;
esac
""")
        # Vary startup delay; scheduling decides which phase hits the deadline.
        # No summary or phase-specific prose is guaranteed.
        for delay in (0, .08, 1.1):
            with self.subTest(startup_delay=delay):
                cat = self.root / 'cat'
                cat.write_text(f'#!/bin/sh\nsleep {delay}\nexec /bin/cat "$@"\n')
                cat.chmod(0o755)
                p = self.invoke(*self.args('touch MUST_NOT_START', '--timeout', '1'))
                v = json.loads(p.stdout)
                self.assertEqual(p.returncode, 124, v)
                self.assertEqual(v['status'], 'timed_out')
                self.assertEqual(v['verification']['status'], 'not_run')
                self.assertEqual(v['error']['code'], 'timed_out')
                self.assertFalse((self.workspace / 'MUST_NOT_START').exists())

    def test_shared_budget_is_not_reset_for_check(self):
        self.env['ZIGAGENT_TEST_SCENARIO'] = 'slow_edit'
        p = self.invoke(*self.args('echo started; sleep 1.5; touch TOO_LATE', '--timeout', '2'))
        v = json.loads(p.stdout)
        self.assertEqual(p.returncode, 124, v)
        self.assertEqual(v['verification']['status'], 'failed')
        self.assertIn('started', v['verification']['output'])
        self.assertFalse((self.workspace / 'TOO_LATE').exists())
        self.assertEqual((self.workspace / 'preserved-edit').read_text(), 'keep edits')

    def wait_file(self, path):
        end = time.monotonic() + 5
        while not path.exists() and time.monotonic() < end:
            time.sleep(.01)
        self.assertTrue(path.exists(), str(path))

    def assert_stopped(self, pid):
        end = time.monotonic() + 2
        while time.monotonic() < end:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            p = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                               capture_output=True, timeout=1)
            if not p.stdout.strip() or p.stdout.strip().startswith(b'Z'):
                return
            time.sleep(.02)
        self.fail(f'owned process {pid} survived')

    def start(self, command, *extra, plain=False):
        p = subprocess.Popen([str(BINARY), *self.args(command, *extra, plain=plain)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, cwd=self.root, env=self.env)
        def cleanup():
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
            p.stderr.close()
            # Never signal recorded child IDs; failed fixture survivors expire.
        self.addCleanup(cleanup)
        return p

    def test_check_descendants_cleanup_on_normal_timeout_and_cancel(self):
        from harness import ROOT
        self.env['ZIGAGENT_TEST_SCENARIO'] = 'edit'
        for mode, sig, code in [('pipes', None, 0), ('closed', None, 0),
                                ('hang', None, 124), ('hang', signal.SIGINT, 130),
                                ('hang', signal.SIGTERM, 143)]:
            for plain in (False, True):
                with self.subTest(mode=mode, signal=sig, plain=plain):
                    for name in ('child-ready', 'check-ready', 'check-pids', 'check-term'):
                        (self.workspace / name).unlink(missing_ok=True)
                    command = 'exec ' + shlex.join([sys.executable, str(ROOT / 'tests/fake_check.py'), mode])
                    p = self.start(command, '--timeout', '2' if code == 124 else '10', plain=plain)
                    self.wait_file(self.workspace / 'check-ready')
                    if sig:
                        p.send_signal(sig)
                    out, err = p.communicate(timeout=5)
                    self.assertEqual(p.returncode, code, (out, err))
                    if not plain:
                        self.assertEqual(err, b'')
                        self.assertEqual(out.count(b'\n'), 1)
                        v = json.loads(out)
                        self.assertEqual(v['verification']['status'], 'passed' if code == 0 else 'failed')
                        self.assertEqual(v['status'], 'completed' if code == 0 else 'timed_out' if code == 124 else 'cancelled')
                        self.assertIn('check started', v['verification']['output'])
                        self.assertEqual(v['verification']['exit_code'], 0 if code == 0 else None)
                    else:
                        self.assertIn(b'verification: passed' if code == 0 else b'verification: failed', out + err)
                    if code != 0:
                        self.assertTrue((self.workspace / 'check-term').exists())
                    self.assertEqual((self.workspace / 'preserved-edit').read_text(), 'keep edits')
                    for pid in json.loads((self.workspace / 'check-pids').read_text()):
                        self.assert_stopped(pid)

    def test_cancel_backend_never_runs_check(self):
        for sig, code in [(signal.SIGINT, 130), (signal.SIGTERM, 143)]:
            for plain in (False, True):
                with self.subTest(signal=sig, plain=plain):
                    self.env['ZIGAGENT_TEST_SCENARIO'] = 'owned_hang'
                    ready = self.log.with_name(self.log.name + '.ready')
                    ready.unlink(missing_ok=True)
                    p = self.start('touch MUST_NOT_START', plain=plain)
                    self.wait_file(ready)
                    p.send_signal(sig)
                    out, err = p.communicate(timeout=4)
                    self.assertEqual(p.returncode, code, (out, err))
                    self.assertFalse((self.workspace / 'MUST_NOT_START').exists())
                    if not plain:
                        v = json.loads(out)
                        self.assertEqual(v['status'], 'cancelled')
                        self.assertEqual(v['verification']['status'], 'not_run')
                        self.assertEqual(v['error']['code'], 'cancelled')
                    else:
                        self.assertIn(b'cancelled', err)
                        self.assertIn(b'verification: not_run', err)

    def test_check_signal_and_shell_errors_report_failure(self):
        for command, exit_code in [('kill -TERM $$', None), ('exit 127', 127), ('(', 2)]:
            p = self.invoke(*self.args(command))
            v = json.loads(p.stdout)
            self.assertEqual(p.returncode, 5, v)
            self.assertEqual(v['verification']['status'], 'failed')
            self.assertEqual(v['verification']['exit_code'], exit_code)
            self.assertEqual(v['error']['code'], 'check_failed')

    def test_check_inherits_callers_environment(self):
        self.env.update(OPENAI_API_KEY='synthetic-check-only', CODEX_API_KEY='synthetic-check-only')
        p = self.invoke(*self.args('test "$OPENAI_API_KEY" = synthetic-check-only && '
                                  'test "$CODEX_API_KEY" = synthetic-check-only'))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(json.loads(self.log.with_name(self.log.name + '.env').read_text()),
                         {'OPENAI_API_KEY': False, 'CODEX_API_KEY': False})

    def test_check_uses_same_canonical_workspace_as_backend(self):
        alias = self.root / 'workspace alias'
        alias.symlink_to(self.workspace, target_is_directory=True)
        self.env['ZIGAGENT_TEST_SCENARIO'] = 'unlink_workspace_alias'
        self.env['ZIGAGENT_TEST_WORKSPACE_LINK'] = str(alias)
        p = self.invoke(*self.args('test -f preserved-edit', '--workspace', str(alias)))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertFalse(alias.exists())
        self.assertEqual(json.loads(p.stdout)['verification']['status'], 'passed')

    def test_check_preserves_workspace_directory_identity(self):
        self.env['ZIGAGENT_TEST_SCENARIO'] = 'replace_workspace'
        p = self.invoke(*self.args('cat identity; test "$(cat identity)" = original'))
        v = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, v)
        self.assertEqual(v['verification']['status'], 'passed')
        self.assertEqual(v['verification']['output'], 'original')
        self.assertEqual((self.workspace / 'identity').read_text(), 'replacement')

    def test_check_workspace_handle_survives_closed_standard_fds(self):
        for closed in ((0,), (2,), (0, 2)):
            def close_fds():
                for fd in closed:
                    os.close(fd)
            p = subprocess.run([str(BINARY), *self.args('printf checked')],
                               capture_output=True, preexec_fn=close_fds,
                               cwd=self.root, env=self.env, timeout=5)
            v = json.loads(p.stdout)
            self.assertEqual(p.returncode, 0, v)
            self.assertEqual(v['verification']['output'], 'checked')

    def test_closed_stdout_during_check_stops_owned_group(self):
        from harness import ROOT
        self.env['ZIGAGENT_TEST_SCENARIO'] = 'edit'
        command = 'exec ' + shlex.join([sys.executable, str(ROOT / 'tests/fake_check.py'), 'hang'])
        p = self.start(command)
        self.wait_file(self.workspace / 'check-ready')
        p.stdout.close()
        p.wait(timeout=4)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stderr.read(), b'')
        for pid in json.loads((self.workspace / 'check-pids').read_text()):
            self.assert_stopped(pid)
        self.assertEqual((self.workspace / 'preserved-edit').read_text(), 'keep edits')
