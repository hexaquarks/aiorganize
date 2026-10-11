import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from src import package_extension
from src.package_extension import EXTENSION_FILES, PROJECT, build_zip, chrome_version, tagged_files


class PackageExtensionTest(unittest.TestCase):
    def setUp(self):
        self.files = {name: (PROJECT / "extension" / name).read_bytes() for name in EXTENSION_FILES}
        manifest = json.loads(self.files["manifest.json"])
        manifest["version"] = "0.1.0"
        self.files["manifest.json"] = json.dumps(manifest).encode()

    def test_archive_is_reproducible_and_contains_only_runtime_files(self):
        self.files[".env"] = b"OPENAI_API_KEY=do-not-package"
        self.files["tests/fixture.py"] = b"do-not-package"
        first = build_zip(self.files, "v0.1.0", [])
        self.assertEqual(first, build_zip(dict(reversed(list(self.files.items()))), "v0.1.0", []))
        self.assertNotIn(b"do-not-package", first)
        with ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(archive.namelist(), sorted(EXTENSION_FILES))
            manifest = json.loads(archive.read("manifest.json"))
            self.assertNotIn("debugger", manifest["permissions"])
            self.assertNotIn("nativeMessaging", manifest["permissions"])
            self.assertNotIn("scripting", manifest["permissions"])
            self.assertEqual(manifest["host_permissions"], ["https://api.openai.com/*"])
            self.assertNotIn("page-reader.js", archive.namelist())
            self.assertNotIn(b"companion", archive.read("panel-entry.js"))
            self.assertEqual(manifest["version"], "0.1.0")
            for icon in manifest["icons"].values():
                self.assertTrue(archive.read(icon).startswith(b"\x89PNG\r\n\x1a\n"))

    def test_version_order_and_tag_alignment(self):
        for tag, previous in (("v0.2.0", []), ("v0.1.0", ["0.1"]), ("v0.1.0", ["0.2.0"])):
            with self.subTest(tag=tag, previous=previous), self.assertRaises(ValueError):
                build_zip(self.files, tag, previous)
        build_zip(self.files, "v0.1.0", ["0.0.9"])
        self.assertGreater(chrome_version("1.10"), chrome_version("1.9.999"))
        self.assertEqual(chrome_version("1"), chrome_version("1.0.0.0"))

    def test_invalid_chrome_versions(self):
        for version in ("0", "0.0.0.0", "01.2", "1.01", "1.65536", "1.2.3.4.5", "1.0-beta", "v1", "../1"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                chrome_version(version)

    def test_missing_required_asset_fails(self):
        del self.files["panel.js"]
        with self.assertRaises(KeyError):
            build_zip(self.files, "v0.1.0", [])

    def test_release_reads_tagged_bytes_and_ignores_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in self.files.items():
                path = root / "extension" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Test", "GIT_COMMITTER_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_EMAIL": "test@example.invalid",
            }

            def run_git(*args):
                subprocess.run(["git", "-C", directory, *args], check=True, capture_output=True, env=env)

            run_git("init")
            run_git("add", "extension")
            run_git("-c", "commit.gpgsign=false", "commit", "-m", "Test")
            run_git("tag", "v0.1.0")
            (root / "extension/panel.js").write_text("dirty change")
            with patch.object(package_extension, "PROJECT", root):
                self.assertEqual(tagged_files("v0.1.0"), self.files)
                with patch("sys.argv", ["package_extension", "--tag", "v0.1.0"]):
                    package_extension.main()
            archive = root / "dist/aiorganize-v0.1.0.zip"
            self.assertEqual(archive.read_bytes(), build_zip(self.files, "v0.1.0", []))

            # Exercise the real tag-history check, not just an explicitly supplied baseline.
            manifest = json.loads(self.files["manifest.json"])
            for version in ("0.0.9", "0.2.0"):
                manifest["version"] = version
                (root / "extension/manifest.json").write_text(json.dumps(manifest))
                run_git("add", "extension")
                run_git("-c", "commit.gpgsign=false", "commit", "-m", "Update version")
                run_git("tag", f"v{version}")
                with patch.object(package_extension, "PROJECT", root):
                    with patch("sys.argv", ["package_extension", "--tag", f"v{version}"]):
                        if version == "0.0.9":
                            with patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit) as error:
                                package_extension.main()
                            self.assertEqual(error.exception.code, 2)
                        else:
                            package_extension.main()

            with patch.object(package_extension, "PROJECT", root):
                with patch("sys.argv", ["package_extension", "--tag", "v0.1.0"]):
                    package_extension.main()
            self.assertEqual(archive.read_bytes(), build_zip(self.files, "v0.1.0", []))

    def test_release_rejects_symlink_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "extension").mkdir()
            (root / "secret").write_text("do-not-package")
            (root / "extension/background.js").symlink_to(root / "secret")
            with patch.object(package_extension, "PROJECT", root):
                with patch("sys.argv", ["package_extension", "--preview"]):
                    with patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit) as error:
                        package_extension.main()
                    self.assertEqual(error.exception.code, 2)
            self.assertFalse((root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
