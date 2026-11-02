#!/usr/bin/env python3
"""Synthetic backend seam. Never invokes Codex or reads account/config files.

ZIGAGENT_TEST_LOG selects an argv JSONL log; ZIGAGENT_TEST_SCENARIO selects
success, logged_out, failed, or malformed. Extend scenarios with each milestone.
"""
import json
import os
import sys
from pathlib import Path


def main():
    args = sys.argv[1:]
    log = os.environ.get("ZIGAGENT_TEST_LOG")
    if log:
        with Path(log).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(args) + "\n")
    scenario = os.environ.get("ZIGAGENT_TEST_SCENARIO", "success")
    if args == ["--version"]:
        print("codex-cli 0.166.0")
    elif args == ["login", "status"]:
        print("Logged in using ChatGPT" if scenario != "logged_out" else "Not logged in", file=sys.stderr)
        return int(scenario == "logged_out")
    elif args and args[0] == "exec":
        if scenario == "malformed":
            print("not JSON")
        elif scenario == "failed":
            print("synthetic backend failure", file=sys.stderr)
            return 1
        else:
            print(json.dumps({"type": "item.completed", "item": {"id": "fake", "type": "agent_message", "text": "synthetic completion"}}))
            print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1}}))
    else:
        print("unsupported fake invocation", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
