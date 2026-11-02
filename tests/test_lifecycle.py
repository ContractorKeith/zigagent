import fcntl
import json
import os
import pty
import select
import signal
import subprocess
import termios
import time

from harness import BINARY, CliCase


class LifecycleTests(CliCase):
    def args(self, *extra):
        return [str(BINARY), 'run', '--json', '--model', 'm', '--codex', str(self.fake), *extra, 'task']

    def terminal_run(self, scenario, *extra, login=False, cancel=None):
        self.log.with_name(self.log.name + '.login').unlink(missing_ok=True)
        self.env['ZIGAGENT_TEST_SCENARIO'] = scenario
        master, slave = pty.openpty()
        def terminal():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        args = [str(BINARY), 'login', *extra] if login else self.args(*extra)
        p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, cwd=self.root, env=self.env,
                             preexec_fn=terminal, pass_fds=(slave,))
        os.close(slave)
        chatter = b''
        end = time.monotonic() + 6
        try:
            while p.poll() is None and time.monotonic() < end:
                if select.select([master], [], [], .02)[0]:
                    try:
                        data = os.read(master, 8192)
                    except OSError:
                        break
                    chatter += data
                    if b'LOGIN READY' in data:
                        if cancel is not None:
                            p.send_signal(cancel)
                        else:
                            os.write(master, b'confirm\n')
            out, err = p.communicate(timeout=2)
            return p.returncode, out, err, chatter
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            os.close(master)

    def records(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()]

    def test_terminal_login_keeps_json_clean_and_verifies_auth(self):
        code, out, err, chatter = self.terminal_run('login_success')
        self.assertEqual(code, 0, (out, err, chatter))
        self.assertEqual(json.loads(out)['status'], 'completed')
        self.assertEqual(out.count(b'\n'), 1)
        self.assertEqual(err, b'')
        self.assertIn(b'LOGIN READY', chatter)
        self.assertEqual(self.records()[2:5], [['login', 'status'], ['login'], ['login', 'status']])

    def test_terminal_no_input_never_logs_in(self):
        code, out, _, _ = self.terminal_run('login_success', '--no-input')
        self.assertEqual(code, 4)
        self.assertEqual(json.loads(out)['error']['code'], 'authentication_required')
        self.assertNotIn(['login'], self.records())

    def test_login_has_separate_deadline_and_rechecks_chatgpt(self):
        for scenario, expected in [('login_hang', 124), ('login_wrong_auth', 4), ('login_post_hang', 124), ('login_success', 0)]:
            with self.subTest(scenario=scenario):
                code, out, err, _ = self.terminal_run(scenario, '--login-timeout', '1')
                self.assertEqual(code, expected, (out, err))

    def test_explicit_login_is_bounded_and_terminal_only(self):
        code, out, err, _ = self.terminal_run('login_success', '--login-timeout', '1', login=True)
        self.assertEqual(code, 0, (out, err))
        self.assertNotIn(['--version'], self.records())
        code, out, err, _ = self.terminal_run('login_hang', '--login-timeout', '1', login=True)
        self.assertEqual(code, 124, (out, err))
        p = self.invoke('login', '--no-input')
        self.assertEqual(p.returncode, 4)

    def wait_file(self, suffix):
        path = self.log.with_name(self.log.name + suffix)
        end = time.monotonic() + 4
        while not path.exists() and time.monotonic() < end:
            time.sleep(.01)
        self.assertTrue(path.exists(), str(path))
        return path

    def start_work(self, scenario, *extra):
        self.env['ZIGAGENT_TEST_SCENARIO'] = scenario
        p = subprocess.Popen(self.args('--workspace', str(self.workspace), *extra),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, cwd=self.root, env=self.env)
        def cleanup():
            if p.poll() is None:
                p.kill()
                p.wait()
            for pipe in (p.stdout, p.stderr):
                if pipe and not pipe.closed:
                    pipe.close()
            # A failing cleanup test must not leak even its synthetic descendants.
            path = self.log.with_name(self.log.name + '.pids')
            if path.exists():
                for pid in json.loads(path.read_text()):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        self.addCleanup(cleanup)
        return p

    def assert_stopped(self, pid):
        # Orphans can briefly be zombies until the host init reaps them.
        end = time.monotonic() + 2
        while time.monotonic() < end:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            proc = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, timeout=1)
            if proc.stdout.strip().startswith(b'Z') or not proc.stdout.strip():
                return
            time.sleep(.02)
        self.fail(f'owned process {pid} survived cleanup')

    def test_cancel_signals_stop_group_and_preserve_edits(self):
        for sig, code in [(signal.SIGINT, 130), (signal.SIGTERM, 143)]:
            with self.subTest(signal=sig):
                for suffix in ('.pids', '.ready', '.term'):
                    self.log.with_name(self.log.name + suffix).unlink(missing_ok=True)
                p = self.start_work('owned_hang')
                self.wait_file('.ready')
                p.send_signal(sig)
                out, err = p.communicate(timeout=4)
                self.assertEqual(p.returncode, code, (out, err))
                self.assertEqual(json.loads(out)['status'], 'cancelled')
                self.assertEqual(json.loads(out)['error']['code'], 'cancelled')
                self.assertTrue((self.workspace / 'preserved-edit').exists())
                self.assertTrue(self.log.with_name(self.log.name + '.term').exists())
                for pid in json.loads(self.wait_file('.pids').read_text()):
                    self.assert_stopped(pid)

    def test_timeout_sends_term_before_kill(self):
        p = self.start_work('owned_hang', '--timeout', '1')
        self.wait_file('.ready')
        out, err = p.communicate(timeout=4)
        self.assertEqual(p.returncode, 124, (out, err))
        self.assertEqual(json.loads(out)['status'], 'timed_out')
        self.assertTrue(self.log.with_name(self.log.name + '.term').exists())
        for pid in json.loads(self.wait_file('.pids').read_text()):
            self.assert_stopped(pid)

    def test_normal_exit_cleans_descendants_with_and_without_pipes(self):
        unrelated = subprocess.Popen(['sleep', '20'])
        self.addCleanup(lambda: (unrelated.terminate(), unrelated.wait()) if unrelated.poll() is None else None)
        for scenario in ('owned_exit_pipes', 'owned_exit_closed', 'owned_simultaneous'):
            with self.subTest(scenario=scenario):
                self.log.with_name(self.log.name + '.pids').unlink(missing_ok=True)
                p = self.start_work(scenario)
                out, err = p.communicate(timeout=3)
                self.assertEqual(p.returncode, 0, (out, err))
                self.assertEqual(json.loads(out)['status'], 'completed')
                for pid in json.loads(self.wait_file('.pids').read_text()):
                    self.assert_stopped(pid)
                self.assertIsNone(unrelated.poll())

    def test_closed_caller_stdout_terminates_owned_work(self):
        p = self.start_work('owned_hang')
        self.wait_file('.ready')
        p.stdout.close()
        p.wait(timeout=4)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stderr.read(), b'')
        for pid in json.loads(self.wait_file('.pids').read_text()):
            self.assert_stopped(pid)

    def test_oversized_partial_event_stops_live_backend_clearly(self):
        p = self.start_work('partial_hang', '--event-limit', '100')
        out, err = p.communicate(timeout=3)
        self.assertEqual(p.returncode, 1, (out, err))
        self.assertEqual(json.loads(out)['error']['code'], 'event_too_large')

    def test_malformed_event_stops_live_backend_clearly(self):
        p = self.start_work('malformed_hang')
        out, err = p.communicate(timeout=3)
        self.assertEqual(p.returncode, 1, (out, err))
        self.assertEqual(json.loads(out)['error']['code'], 'protocol_error')

    def test_cancellation_during_prompt_and_each_preflight(self):
        for scenario in ('prompt', 'version_hang', 'help_hang', 'auth_hang'):
            with self.subTest(scenario=scenario):
                self.env['ZIGAGENT_TEST_SCENARIO'] = scenario
                self.log.unlink(missing_ok=True)
                args = self.args()
                if scenario == 'prompt':
                    args[-1] = '-'
                p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, cwd=self.root, env=self.env)
                try:
                    if scenario == 'prompt':
                        time.sleep(.1)
                    else:
                        expected = {'version_hang': ['--version'], 'help_hang': ['exec', '--help'],
                                    'auth_hang': ['login', 'status']}[scenario]
                        end = time.monotonic() + 3
                        while time.monotonic() < end:
                            if self.log.exists() and expected in self.records():
                                break
                            time.sleep(.01)
                        else:
                            self.fail('preflight did not start')
                    p.send_signal(signal.SIGTERM)
                    out, err = p.communicate(timeout=4)
                    self.assertEqual(p.returncode, 143, (out, err))
                    self.assertEqual(json.loads(out)['error']['code'], 'cancelled')
                finally:
                    if p.poll() is None:
                        p.kill()
                        p.wait()
                    for pipe in (p.stdin, p.stdout, p.stderr):
                        if not pipe.closed:
                            pipe.close()

    def test_stalled_result_reader_is_finite(self):
        self.env['ZIGAGENT_TEST_SCENARIO'] = 'large_summary'
        p = subprocess.Popen(self.args('--output-limit', '1048576'), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.root, env=self.env)
        try:
            p.wait(timeout=4)
            self.assertNotEqual(p.returncode, 0)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
            p.stderr.close()

    def test_unrelated_auth_errors_on_terminal_never_login(self):
        for scenario in ('auth_failure', 'api_key', 'auth_false_logged_out'):
            code, out, _, chatter = self.terminal_run(scenario)
            self.assertEqual(code, 4, out)
            self.assertEqual(json.loads(out)['error']['code'], 'authentication_failed')
            self.assertNotIn(b'LOGIN READY', chatter)
            self.assertNotIn(['login'], self.records())

    def test_midrun_auth_failure_never_retries_mutating_work(self):
        self.env['ZIGAGENT_TEST_SCENARIO'] = 'midrun_auth'
        p = self.invoke(*self.args('--workspace', str(self.workspace))[1:])
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)['error']['code'], 'backend_failed')
        self.assertTrue((self.workspace / 'preserved-edit').exists())
        self.assertEqual(sum(x[:2] == ['exec', '--json'] for x in self.records()), 1)
        self.assertNotIn(['login'], self.records())

    def test_login_budget_is_separate_from_execution(self):
        code, out, err, _ = self.terminal_run('login_slow', '--timeout', '1', '--login-timeout', '2')
        self.assertEqual(code, 0, (out, err))
        self.assertGreater(json.loads(out)['elapsed_ms'], 1000)

    def test_login_cancellation_does_not_start_agent(self):
        for sig, expected in [(signal.SIGINT, 130), (signal.SIGTERM, 143)]:
            code, out, err, _ = self.terminal_run('login_success', cancel=sig)
            self.assertEqual(code, expected, (out, err))
            self.assertEqual(json.loads(out)['status'], 'cancelled')
            self.assertFalse(any(x[:2] == ['exec', '--json'] for x in self.records()))

    def test_tty_stdin_without_controlling_terminal_cannot_login(self):
        self.env['ZIGAGENT_TEST_SCENARIO'] = 'login_success'
        master, slave = pty.openpty()
        try:
            p = subprocess.run(self.args(), stdin=slave, capture_output=True, start_new_session=True,
                               cwd=self.root, env=self.env, timeout=3)
            self.assertEqual(p.returncode, 4, p.stdout)
            self.assertEqual(p.stderr, b'')
            self.assertEqual(json.loads(p.stdout)['error']['code'], 'authentication_required')
            self.assertNotIn(['login'], self.records())
        finally:
            os.close(master)
            os.close(slave)

    def test_closed_stdout_ends_prompt_wait_and_preflight(self):
        for scenario in ('prompt', 'version_hang'):
            self.env['ZIGAGENT_TEST_SCENARIO'] = scenario
            args = self.args()
            if scenario == 'prompt':
                args[-1] = '-'
            p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, cwd=self.root, env=self.env)
            try:
                p.stdout.close()
                p.wait(timeout=3)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(p.stderr.read(), b'')
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait()
                p.stdin.close()
                p.stderr.close()

    def test_explicit_login_missing_backend_is_actionable(self):
        (self.root / 'codex').unlink()
        self.env['PATH'] = str(self.root)
        code, out, err, _ = self.terminal_run('login_success', login=True)
        self.assertEqual(code, 3, (out, err))
        self.assertIn(b'backend_missing', err)

    def test_partial_event_at_stdout_eof_stops_live_backend_clearly(self):
        p = self.start_work('partial_closed_hang')
        out, err = p.communicate(timeout=3)
        self.assertEqual(p.returncode, 1, (out, err))
        self.assertEqual(json.loads(out)['error']['code'], 'protocol_error')
