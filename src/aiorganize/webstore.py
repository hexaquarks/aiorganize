"""Upload tagged releases and submit updates to an existing private store item."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .package_extension import build_zip, chrome_version, git, tagged_files


API_URL = "https://chromewebstore.googleapis.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def request_json(request: Request) -> dict:
    """Keep provider error bodies out of logs because they can contain credentials."""
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as error:
        raise ValueError(
            f"Google API returned HTTP {error.code}. Check authentication and the developer dashboard."
        ) from None
    except (URLError, OSError):
        raise ValueError("Google API could not be reached. Check the connection and retry.") from None
    except (ValueError, UnicodeError):
        raise ValueError("Google API returned an invalid JSON response.") from None
    if not isinstance(result, dict):
        raise ValueError("Google API returned an invalid response.")
    return result


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} in your local environment or .env before using the store API.")
    return value


class WebStoreClient:
    def __init__(self):
        publisher = required_environment("CWS_PUBLISHER_ID")
        item = required_environment("CWS_EXTENSION_ID")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", publisher) or not re.fullmatch(r"[a-p]{32}", item):
            raise ValueError("Use the publisher ID and 32-character extension ID from the developer dashboard.")
        self.name = f"publishers/{publisher}/items/{item}"
        credentials = {
            "client_id": required_environment("CWS_CLIENT_ID"),
            "client_secret": required_environment("CWS_CLIENT_SECRET"),
            "refresh_token": required_environment("CWS_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        }
        response = request_json(Request(
            TOKEN_URL, data=urlencode(credentials).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
        ))
        token = response.get("access_token")
        if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
            raise ValueError("Google did not return an access token. Check the OAuth configuration.")
        self.token = token

    def request(self, action: str, *, data: bytes | None = None, upload: bool = False) -> dict:
        prefix = "upload/v2" if upload else "v2"
        return request_json(Request(
            f"{API_URL}/{prefix}/{self.name}:{action}", data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/zip" if upload else "application/json",
            },
            method="POST" if data is not None else "GET",
        ))

    def status(self) -> dict:
        return self.request("fetchStatus")

    def upload(self, package: bytes, *, wait_seconds: float = 120) -> None:
        response = self.request("upload", data=package, upload=True)
        state = response.get("uploadState")
        deadline = time.monotonic() + wait_seconds
        # The enum is IN_PROGRESS; Google's guide also uses the older UPLOAD_IN_PROGRESS spelling.
        while state in {"IN_PROGRESS", "UPLOAD_IN_PROGRESS"}:
            if time.monotonic() >= deadline:
                raise ValueError("Upload is still processing. Run the status command before retrying.")
            time.sleep(2)
            state = self.status().get("lastAsyncUploadState")
        if state != "SUCCEEDED":
            raise ValueError("The store did not confirm a successful upload. Check the developer dashboard.")

    def publish_private(self) -> dict:
        return self.request("publish", data=json.dumps({
            "publishType": "DEFAULT_PUBLISH", "skipReview": False, "blockOnWarnings": True,
        }).encode())


def store_versions(status: dict) -> list[str]:
    versions = []
    for field in ("publishedItemRevisionStatus", "submittedItemRevisionStatus"):
        revision = status.get(field, {})
        channels = revision.get("distributionChannels", [])
        if revision and not channels:
            raise ValueError("Store version is unavailable. Check the developer dashboard before uploading.")
        for channel in channels:
            version = channel.get("crxVersion")
            if not isinstance(version, str):
                raise ValueError("Store version is unavailable. Check the developer dashboard before uploading.")
            chrome_version(version)
            versions.append(version)
    return versions


def release(client: WebStoreClient, tag: str, *, publish_private: bool, owner_only_confirmed: bool) -> None:
    chrome_version(tag.removeprefix("v"))
    if publish_private and not owner_only_confirmed:
        raise ValueError("Confirm the dashboard's trusted tester list contains only you with --confirm-owner-only.")
    files = tagged_files(tag)
    ancestors = git("tag", "--merged", f"refs/tags/{tag}").decode().splitlines()
    previous = [ancestor[1:] for ancestor in ancestors if ancestor.startswith("v") and ancestor != tag]
    status = client.status()
    if status.get("takenDown") or status.get("warned"):
        raise ValueError("Resolve the item's policy warning or takedown in the dashboard before uploading.")
    if status.get("lastAsyncUploadState") in {"IN_PROGRESS", "UPLOAD_IN_PROGRESS"}:
        raise ValueError("Another upload is processing. Check status before uploading again.")
    submitted = status.get("submittedItemRevisionStatus", {}).get("state")
    if submitted in {"PENDING_REVIEW", "STAGED"}:
        raise ValueError("An existing submission is pending or staged. Resolve it in the dashboard first.")
    if publish_private:
        published = status.get("publishedItemRevisionStatus", {}).get("state")
        if published != "PUBLISHED_TO_TESTERS":
            raise ValueError("First publish this item privately through the dashboard before automating updates.")

    package = build_zip(files, tag, previous + store_versions(status))
    print(f"Uploading {tag}; SHA-256: {hashlib.sha256(package).hexdigest()}", flush=True)
    client.upload(package)
    print("Upload succeeded.", flush=True)
    if publish_private:
        response = client.publish_private()
        state = response.get("state")
        if state not in {"PENDING_REVIEW", "PUBLISHED_TO_TESTERS"}:
            raise ValueError("Unexpected submission state. Inspect the developer dashboard before continuing.")
        print(f"Private update submitted. State: {state}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Read the item's upload and review status.")
    upload = commands.add_parser("release", help="Build and upload an existing tag; submission is optional.")
    upload.add_argument("--tag", required=True)
    upload.add_argument("--publish-private", action="store_true", help="Submit the update using existing private visibility.")
    upload.add_argument("--confirm-owner-only", action="store_true", help="Confirm the dashboard tester list contains only you.")
    args = parser.parse_args()
    try:
        if args.command == "release" and args.publish_private and not args.confirm_owner_only:
            parser.error("--publish-private requires --confirm-owner-only after checking the dashboard tester list.")
        client = WebStoreClient()
        if args.command == "status":
            status = client.status()
            print(json.dumps({
                "published_state": status.get("publishedItemRevisionStatus", {}).get("state"),
                "submitted_state": status.get("submittedItemRevisionStatus", {}).get("state"),
                "upload_state": status.get("lastAsyncUploadState"),
                "versions": store_versions(status),
                "taken_down": status.get("takenDown", False),
                "warned": status.get("warned", False),
            }, indent=2))
        else:
            release(client, args.tag, publish_private=args.publish_private, owner_only_confirmed=args.confirm_owner_only)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
