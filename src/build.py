"""Build a store ZIP from a release tag, or a local preview."""

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from packaging.version import Version


PROJECT = Path(__file__).resolve().parents[1]
# Chrome's manifest specification limits versions to four components, each at most 65535.
# https://developer.chrome.com/docs/extensions/reference/manifest/version
MAX_CHROME_VERSION_COMPONENTS = 4
MAX_CHROME_VERSION_COMPONENT = 65535

# An explicit list prevents local configuration and development utilities entering releases.
EXTENSION_FILES = (
    "runtime/background.js",
    "manifest.json",
    "runtime/panel.css",
    "panel.html",
    "runtime/panel.js",
    "icons/brand.png",
    "LICENSE",
)
COMPILED_EXTENSION = PROJECT / "dist" / "extension"


def build_frontend(project: Path = PROJECT, *, install: bool = False, development: bool = False) -> dict[str, bytes]:
    npm = shutil.which("npm")

    if npm is None:
        raise ValueError("npm not found.")

    if install:
        subprocess.run([npm, "ci"], cwd=project, check=True)

    command = [npm, "run", "build"]

    if development:
        command.extend(["--", "--mode", "development"])

    subprocess.run(command, cwd=project, check=True)

    directory = project / "dist" / ("development" if development else "extension")
    return {name: (directory / name).read_bytes() for name in EXTENSION_FILES}


def chrome_version(version: str) -> Version:
    """Use the package for comparison, with Chrome's narrower manifest constraints."""
    parsed = Version(version)
    components = parsed.release
    numeric_version = ".".join(str(component) for component in components)

    # Chrome rejects prerelease suffixes and leading zeros that Python versions allow.
    if version != numeric_version:
        raise ValueError(f"Invalid Chrome version: {version}")

    exceeds_limits = (
        len(components) > MAX_CHROME_VERSION_COMPONENTS
        or max(components) > MAX_CHROME_VERSION_COMPONENT
    )
    if exceeds_limits or not any(components):
        raise ValueError(f"Invalid Chrome version: {version}")

    return parsed


def build_zip(files: dict[str, bytes], tag: str, previous_versions: list[str]) -> bytes:
    manifest = json.loads(files["manifest.json"])
    version = manifest["version"]
    current = chrome_version(version)

    if tag != f"v{version}":
        raise ValueError(f"Tag must match manifest version exactly: v{version}")

    if any(current <= chrome_version(previous) for previous in previous_versions):
        raise ValueError("The release version must be greater than every previous release version.")

    output = io.BytesIO()

    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(EXTENSION_FILES):
            archive.writestr(name, files[name])

    return output.getvalue()


def git(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(PROJECT), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def tagged_files(tag: str) -> dict[str, bytes]:
    """Build an isolated tagged checkout, preserving the current working tree."""
    archive_bytes = git("archive", "--format=tar", f"refs/tags/{tag}")

    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        members = {member.name: member for member in archive.getmembers()}

        if any(member.issym() or member.islnk() for member in members.values()):
            raise ValueError("Release assets must be regular files.")

        if "package.json" not in members:
            raise ValueError("Release tags must contain the current frontend build configuration.")

        with tempfile.TemporaryDirectory(prefix="aiorganize-release-") as directory:
            archive.extractall(directory, filter="data")
            return build_frontend(Path(directory), install=True)


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
            source_dir = PROJECT / "extension"

            if any(path.is_symlink() for path in source_dir.rglob("*")):
                raise ValueError("Release assets must not use symlinks.")

            files = build_frontend(PROJECT)
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
