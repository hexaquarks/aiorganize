"""Build a reproducible store ZIP from a release tag, or a local preview."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo


PROJECT = Path(__file__).resolve().parents[2]
# An explicit list prevents local configuration and future demo files entering releases.
EXTENSION_FILES = (
    "background.js", "manifest.json", "panel-entry.js", "panel.css", "panel.html",
    "panel.js", "proposal-client.js", "icons/16.png", "icons/32.png", "icons/48.png", "icons/128.png",
)


def chrome_version(version: str) -> tuple[int, ...]:
    """Compare versions as Chrome does: missing components count as zero."""
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){0,3}", version):
        raise ValueError(f"Invalid Chrome version: {version}")
    parts = tuple(int(part) for part in version.split("."))
    if not any(parts) or any(part > 65535 for part in parts):
        raise ValueError(f"Invalid Chrome version: {version}")
    return parts + (0,) * (4 - len(parts))


def build_zip(files: dict[str, bytes], tag: str, previous_versions: list[str]) -> bytes:
    manifest = json.loads(files["manifest.json"])
    version = manifest["version"]
    current = chrome_version(version)
    if tag != f"v{version}":
        raise ValueError(f"Tag must match manifest version exactly: v{version}")
    if any(current <= chrome_version(previous) for previous in previous_versions):
        raise ValueError("The release version must be greater than every previous release version.")

    # Only terminal demos use debugger target IDs and control.html. The store panel uses native tab IDs.
    manifest["permissions"] = [permission for permission in manifest["permissions"] if permission != "debugger"]
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for name in sorted(EXTENSION_FILES):
            data = files[name]
            if name == "manifest.json":
                data = (json.dumps(manifest, indent=2) + "\n").encode()
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    return output.getvalue()


def git(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(PROJECT), *arguments], check=True, capture_output=True,
    ).stdout


def tagged_files(tag: str) -> dict[str, bytes]:
    """Read committed bytes without using, changing, or cleaning the working tree."""
    ref = f"refs/tags/{tag}"
    archive_bytes = git("archive", "--format=tar", ref, "extension")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        for name in EXTENSION_FILES:
            member = archive.getmember(f"extension/{name}")
            if not member.isfile():
                raise ValueError(f"Release assets must be regular files: {name}")
            with archive.extractfile(member) as source:
                files[name] = source.read()
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tag", help="Existing release tag, exactly v<manifest version>.")
    mode.add_argument("--preview", action="store_true", help="Package working files for local review only.")
    parser.add_argument("--previous-version", help="Latest store version, if it has no ancestor release tag.")
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "dist")
    args = parser.parse_args()

    try:
        if args.preview:
            files = {}
            for name in EXTENSION_FILES:
                path = PROJECT / "extension" / name
                if any(part.is_symlink() for part in (path, *path.parents)):
                    raise ValueError(f"Release assets must not use symlinks: {name}")
                files[name] = path.read_bytes()
            tag = "v" + json.loads(files["manifest.json"])["version"]
            ancestors = git("tag", "--merged", "HEAD").decode().splitlines()
        else:
            tag = args.tag
            chrome_version(tag.removeprefix("v"))
            files = tagged_files(tag)
            ancestors = git("tag", "--merged", f"refs/tags/{tag}").decode().splitlines()
            ancestors = [ancestor for ancestor in ancestors if ancestor != tag]

        previous = [ancestor[1:] for ancestor in ancestors if ancestor.startswith("v")]
        if args.previous_version:
            previous.append(args.previous_version)
        data = build_zip(files, tag, previous)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        suffix = "-preview" if args.preview else ""
        destination = args.output_dir / f"aiorganize-{tag}{suffix}.zip"
        destination.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        destination.with_suffix(".zip.sha256").write_text(f"{digest}  {destination.name}\n")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.error(str(error))
    print(f"Built {destination}\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
