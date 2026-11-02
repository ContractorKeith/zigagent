#!/usr/bin/env bash
# Select an installed SDK for pinned Zig, including its build runner.
set -euo pipefail
if [[ $# -eq 0 ]]; then
  echo 'usage: scripts/with-macos-sdk.sh COMMAND [ARG ...]' >&2
  exit 2
fi
if [[ -z "${ZIGAGENT_MACOS_SDK:-}" || "${ZIGAGENT_SDK_WRAPPED:-}" == 1 ]]; then
  exec "$@"
fi
if [[ "$(uname -s)" != Darwin || "$ZIGAGENT_MACOS_SDK" != /* || ! -f "$ZIGAGENT_MACOS_SDK/usr/lib/libSystem.tbd" ]]; then
  echo 'ZIGAGENT_MACOS_SDK must name an installed absolute macOS SDK directory' >&2
  exit 2
fi
sdk_shim_dir=$(mktemp -d)
trap 'rm -r "$sdk_shim_dir"' EXIT
cat > "$sdk_shim_dir/xcrun" <<'SH'
#!/bin/sh
if [ "$#" -eq 3 ] && [ "$1" = --sdk ] && [ "$2" = macosx ] && [ "$3" = --show-sdk-path ]; then
  printf '%s\n' "$ZIGAGENT_MACOS_SDK"
  exit 0
fi
exec /usr/bin/xcrun "$@"
SH
chmod +x "$sdk_shim_dir/xcrun"
PATH="$sdk_shim_dir:$PATH" ZIGAGENT_SDK_WRAPPED=1 "$@"
