#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(zig version)" != 0.15.2 ]]; then
  echo 'accept: Zig 0.15.2 is required' >&2
  exit 1
fi
export ZIG_GLOBAL_CACHE_DIR="${ZIG_GLOBAL_CACHE_DIR:-$PWD/.zig-cache/global}"
zig fmt --check build.zig src
zig build test --summary all
zig build --summary all
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
printf 'accept: M0 passed (execution remains unimplemented)\n'
