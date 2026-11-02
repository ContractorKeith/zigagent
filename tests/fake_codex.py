#!/usr/bin/env python3
"""Synthetic backend only: no model, configuration, or credential-file access."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def event(kind, **fields):
    print(json.dumps({"type": kind, **fields}), flush=True)


def main():
    args = sys.argv[1:]
    log = os.environ.get("ZIGAGENT_TEST_LOG")
    if log:
        with Path(log).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(args) + "\n")
    scenario = os.environ.get("ZIGAGENT_TEST_SCENARIO", "success")
    if args == ["--version"]:
        if scenario == "version_hang":
            time.sleep(20)
        if scenario == "version_flood":
            print("x" * 10000)
        else:
            print(os.environ.get("ZIGAGENT_TEST_VERSION", "codex-cli 0.166.0"))
        return 1 if scenario == "version_failure" else 0
    if args == ["exec", "--help"]:
        if scenario == "help_hang":
            time.sleep(20)
        help_text = ("--json --ephemeral --color --model --cd --add-dir --ignore-user-config "
              "--ignore-rules --dangerously-bypass-approvals-and-sandbox"
              if scenario != "missing_capability" else "--json")
        print(" ".join(flag + "-unsupported" for flag in help_text.split())
              if scenario == "capability_prefix" else help_text)
        return 0
    if args == ["login", "status"]:
        if scenario == "auth_hang":
            time.sleep(20)
        text, code = {
            "logged_out": ("Not logged in", 1),
            "api_key": ("Logged in using an API key - synthetic", 0),
            "auth_failure": ("synthetic keyring unavailable", 1),
            "auth_wrong_exit": ("Logged in using ChatGPT", 1),
            "auth_unknown": ("new authentication format", 0),
            "auth_false_logged_out": ("Not logged in", 0),
            "auth_flood": ("x" * 10000, 0),
        }.get(scenario, ("Logged in using ChatGPT", 0))
        print(text, file=sys.stdout if scenario == "auth_stdout" else sys.stderr)
        if scenario == "auth_ambiguous":
            print("unexpected stdout")
        return code
    if not args or args[0] != "exec":
        return 2
    if scenario == "reject_stdin":
        os.close(0)
        prompt = b""
    else:
        prompt = sys.stdin.buffer.read()
    if log:
        Path(log + ".stdin").write_bytes(prompt)
        Path(log + ".env").write_text(json.dumps({key: key in os.environ for key in
                                                ("OPENAI_API_KEY", "CODEX_API_KEY")}))
    if scenario == "exec_hang":
        time.sleep(20)
    if scenario == "closed_pipes_hang":
        os.close(1)
        os.close(2)
        time.sleep(20)
    if scenario == "descendant_pipes":
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    if scenario == "malformed":
        print("not JSON")
    elif scenario == "partial":
        sys.stdout.write('{"type":"turn.completed"}')
    elif scenario == "empty":
        pass
    elif scenario == "invalid_utf8":
        sys.stdout.buffer.write(b'{"type":"unknown","text":"\xff"}\n')
    elif scenario == "large_event":
        event("future.event", text="x" * 2000)
    else:
        if scenario == "saturation":
            # More than pipe capacity, interleaved with stdout.
            for _ in range(64):
                os.write(2, b"x" * 4096)
                event("future.event", text="ignored")
        if scenario == "diagnostic_utf8":
            os.write(2, b"prefix\xff\xe2\x98\x83")
        if scenario == "unknown":
            event("future.event", ignored={"extra": True})
        text = "☃" * 300 if scenario == "summary_limit" else "synthetic completion"
        if scenario == "chunked":
            data = (json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": text}}) + "\n").encode()
            for byte in data:
                os.write(1, bytes([byte]))
        else:
            event("item.completed", item={"id": "fake", "type": "agent_message", "text": text})
        if scenario == "turn_failed":
            event("turn.failed", error={"message": "synthetic failure"})
        if scenario == "error_event":
            event("error", message="synthetic failure")
        if scenario in ("tool_failed", "recovered_tool"):
            event("item.completed", item={"type": "command_execution", "status": "failed", "exit_code": 1})
        if scenario == "recovered_tool":
            event("item.completed", item={"type": "command_execution", "status": "completed", "exit_code": 0})
            event("item.completed", item={"type": "agent_message", "text": "fixed and retested"})
        if scenario == "patch_failed":
            event("item.completed", item={"type": "file_change", "status": "failed"})
        if scenario == "warning":
            event("item.completed", item={"id": "notice", "type": "error", "message": "nonfatal configuration warning"})
        if scenario == "bad_item":
            event("item.completed", item={"type": "agent_message", "text": 9})
        if scenario != "missing_completion":
            usage = {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0}
            if scenario == "bad_usage":
                usage = "wrong-type"
            elif scenario == "bad_usage_count":
                usage["input_tokens"] = "1"
            elif scenario == "missing_usage_count":
                del usage["output_tokens"]
            event("turn.completed", usage=usage)
        if scenario == "late_start":
            event("turn.started")
        if scenario == "late_tool":
            event("item.started", item={"type": "command_execution", "status": "in_progress"})
        if scenario == "duplicate_completion":
            event("turn.completed")
        if scenario == "trailing_malformed":
            print("not JSON")
    if scenario == "failed":
        print("synthetic backend failure", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
