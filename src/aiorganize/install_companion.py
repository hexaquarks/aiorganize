import argparse
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

from .companion import HOST_NAME


def native_manifest_directory() -> Path:
    """Return Chrome's user-level native host directory on supported platforms."""
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts"
    if sys.platform.startswith("linux"):
        config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return config / "google-chrome/NativeMessagingHosts"
    raise ValueError("Companion registration currently supports macOS and Linux Chrome.")


def install_companion(extension_id: str, project: Path, manifest_directory: Path | None = None) -> Path:
    """Register one extension without copying its API key into the launcher or manifest."""
    if not re.fullmatch(r"[a-p]{32}", extension_id):
        raise ValueError("Use the 32-character extension ID shown in chrome://extensions.")
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("Install uv and run uv sync before registering the companion.")

    project = project.resolve()
    directory = manifest_directory if manifest_directory is not None else native_manifest_directory()
    directory.mkdir(parents=True, exist_ok=True)
    launcher = directory / f"{HOST_NAME}.sh"
    origin = f"chrome-extension://{extension_id}/"
    command = [uv, "run", "--project", str(project)]
    entry_point = ["python", "-m", "aiorganize.companion", "--allowed-origin", origin]
    env_file = project / ".env"
    # Check at launch so creating or updating .env never requires re-registration.
    launcher.write_text(
        "#!/bin/sh\n"
        + "if [ -f " + shlex.quote(str(env_file)) + " ]; then\n"
        + "  exec " + shlex.join(command + ["--env-file", str(env_file)] + entry_point) + ' "$@"\n'
        + "fi\n"
        + "exec " + shlex.join(command + entry_point) + ' "$@"\n'
    )
    launcher.chmod(0o700)
    manifest = directory / f"{HOST_NAME}.json"
    manifest.write_text(json.dumps({
        "name": HOST_NAME,
        "description": "AI Organize local grouping agent",
        "path": str(launcher.resolve()),
        "type": "stdio",
        "allowed_origins": [origin],
    }, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Register the local companion for an unpacked Chrome extension.")
    parser.add_argument("--extension-id", required=True, help="The ID shown in chrome://extensions.")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    try:
        manifest = install_companion(args.extension_id, project)
    except ValueError as error:
        parser.error(str(error))
    print(f"Registered companion: {manifest}")


if __name__ == "__main__":
    main()
