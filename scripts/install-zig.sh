#!/usr/bin/env bash
# Download the pinned official compiler; never change shared shell config.
set -euo pipefail
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)
    platform=x86_64-linux
    checksum=02aa270f183da276e5b5920b1dac44a63f1a49e55050ebde3aecc9eb82f93239 ;;
  Darwin-arm64)
    platform=aarch64-macos
    checksum=3cc2bab367e185cdfb27501c4b30b1b0653c28d9f73df8dc91488e66ece5fa6b ;;
  *) echo 'Supported toolchains: Linux x86_64 and macOS arm64' >&2; exit 1 ;;
esac
install_root=${1:-"$HOME/.local/share/zigagent-toolchains"}
mkdir -p "$install_root"
install_root=$(cd "$install_root" && pwd)
archive="$install_root/zig-$platform-0.15.2.tar.xz"
curl --fail --silent --show-error --location --max-time 1800 \
  "https://ziglang.org/download/0.15.2/zig-$platform-0.15.2.tar.xz" -o "$archive"
python3 - "$archive" "$checksum" <<'PY'
import hashlib
import sys
with open(sys.argv[1], "rb") as stream:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    actual = digest.hexdigest()
if actual != sys.argv[2]:
    raise SystemExit("Zig archive checksum mismatch")
PY
tar -xJf "$archive" -C "$install_root"
printf '%s\n' "$install_root/zig-$platform-0.15.2"
