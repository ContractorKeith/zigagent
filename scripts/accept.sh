#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
# M0 replaces this honest scaffold failure with the executable acceptance gate.
echo 'accept: implementation pending (M0)' >&2
exit 1
