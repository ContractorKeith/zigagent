#!/usr/bin/env python3
"""Build and validate native release archives; Python is maintainer tooling only."""
import argparse
from contextlib import contextmanager
import gzip
import hashlib
import io
import os
from pathlib import Path
import platform
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("linux-x86_64", "macos-arm64")
FILES = ("zigagent", "README.md", "LICENSE", "CHANGELOG.md")
MAX_MEMBER = 32 * 1024 * 1024


@contextmanager
def atomic_output(path):
    """Replace the output entry, never write through an existing symlink."""
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.zigagent-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            yield stream
            stream.close()
            temporary.chmod(0o644)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def version():
    return re.search(r'pub const version = "([^"]+)";',
                     (ROOT / "src/cli.zig").read_text())[1]


def native_target():
    host = (platform.system(), platform.machine())
    try:
        return {("Linux", "x86_64"): TARGETS[0],
                ("Darwin", "arm64"): TARGETS[1]}[host]
    except KeyError:
        raise ValueError(f"unsupported native host: {host}") from None


def archive_name(target):
    return f"zigagent-{version()}-{target}.tar.gz"


def sha256(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def check_binary(data, target):
    # Reject scripts and binaries for the other platform before executing anything.
    if target == "linux-x86_64":
        valid = (data[:7] == b"\x7fELF\x02\x01\x01" and
                 data[18:20] == b"\x3e\x00")
    else:
        valid = data[:8] == b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01"
    if not valid:
        raise ValueError("wrong executable format/architecture")


def validate(directory, targets):
    """Check exact manifest and member set without trusting archive extraction paths."""
    directory = Path(directory)
    names = {archive_name(target): target for target in targets}
    entries = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not match or match[2] in entries:
            raise ValueError("invalid or duplicate checksum entry")
        entries[match[2]] = match[1]
    if set(entries) != set(names):
        raise ValueError("checksum artifact set mismatch")
    if {p.name for p in directory.glob("*.tar.gz")} != set(names):
        raise ValueError("archive artifact set mismatch")
    for name, target in names.items():
        archive = directory / name
        if archive.is_symlink() or sha256(archive) != entries[name]:
            raise ValueError("archive checksum mismatch or symlink")
        prefix = name.removesuffix(".tar.gz")
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            expected = {f"{prefix}/{f}" for f in FILES}
            if len(members) != len(FILES) or {m.name for m in members} != expected:
                raise ValueError("unexpected archive contents")
            content = {}
            for member in members:
                leaf = member.name.split("/")[-1]
                mode = 0o755 if leaf == "zigagent" else 0o644
                if (not member.isfile() or member.mode != mode or
                        not 0 < member.size <= MAX_MEMBER):
                    raise ValueError("unsafe member type/mode/size")
                content[leaf] = tar.extractfile(member).read()
        check_binary(content["zigagent"], target)
        if target == native_target():
            with tempfile.TemporaryDirectory(prefix="zigagent-artifact-") as scratch:
                binary = Path(scratch) / "zigagent"
                binary.write_bytes(content["zigagent"])
                binary.chmod(0o755)
                result = subprocess.run([str(binary), "--version"], capture_output=True,
                                        timeout=10, check=True)
                if result.stdout != f"zigagent {version()}\n".encode() or result.stderr:
                    raise ValueError("artifact version mismatch")
                result = subprocess.run([str(binary), "--help"], capture_output=True,
                                        timeout=10, check=True)
                if b"Usage:" not in result.stdout or result.stderr:
                    raise ValueError("artifact help failed")


def build(directory):
    target = native_target()
    if subprocess.check_output(["zig", "version"], timeout=10).strip() != b"0.15.2":
        raise ValueError("Zig 0.15.2 required")
    subprocess.run(["bash", "scripts/with-macos-sdk.sh", "zig", "build",
                    "-Doptimize=ReleaseSmall"], cwd=ROOT, check=True, timeout=300)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = archive_name(target)
    prefix = name.removesuffix(".tar.gz")
    # Normalize metadata and gzip time so identical inputs yield identical archives.
    with atomic_output(directory / name) as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as tar:
                for leaf in FILES:
                    path = ROOT / ("zig-out/bin/zigagent" if leaf == "zigagent" else leaf)
                    data = path.read_bytes()
                    member = tarfile.TarInfo(f"{prefix}/{leaf}")
                    member.size = len(data)
                    member.mode = 0o755 if leaf == "zigagent" else 0o644
                    tar.addfile(member, io.BytesIO(data))
    write_manifest(directory, [target])
    validate(directory, [target])
    print(directory / name)


def write_manifest(directory, targets):
    directory = Path(directory)
    lines = [f"{sha256(directory / archive_name(t))}  {archive_name(t)}\n" for t in targets]
    with atomic_output(directory / "SHA256SUMS") as stream:
        stream.write("".join(lines).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate", "manifest"))
    parser.add_argument("--directory", type=Path, default=ROOT / "dist")
    parser.add_argument("--all", action="store_true", help="require both release targets")
    args = parser.parse_args()
    targets = TARGETS if args.all else [native_target()]
    if args.command == "build":
        if args.all:
            parser.error("build is native only; combine archives with manifest --all")
        build(args.directory)
    else:
        if args.command == "manifest":
            write_manifest(args.directory, targets)
        validate(args.directory, targets)
        print("validated: " + ", ".join(targets))


if __name__ == "__main__":
    main()
