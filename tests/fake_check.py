#!/usr/bin/env python3
"""Synthetic owned descendants, always self-expiring after 20 seconds."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

mode = sys.argv[1]
if mode == 'child':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if sys.argv[2] == 'closed':
        os.close(1)
        os.close(2)
    Path('child-ready').write_text('ready')
    time.sleep(20)
else:
    signal.signal(signal.SIGTERM, lambda sig, frame: Path('check-term').write_text('TERM'))
    child = subprocess.Popen([sys.executable, __file__, 'child', mode])
    Path('check-pids').write_text(json.dumps([os.getpid(), child.pid]))
    end = time.monotonic() + 5
    while not Path('child-ready').exists() and time.monotonic() < end:
        time.sleep(.01)
    print('check started', flush=True)
    Path('check-ready').write_text('ready')
    if mode == 'hang':
        time.sleep(20)
