import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import dev


class DevelopmentStartupTest(unittest.TestCase):
    def test_windows_finds_system_or_user_installation(self):
        for location in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = Path.home() / "test-install"
            executable = root / "Google/Chrome/Application/chrome.exe"
            with (
                self.subTest(location=location),
                patch("src.dev.sys.platform", "win32"),
                patch.dict(dev.os.environ, {location: str(root)}, clear=True),
                patch("src.dev.Path.is_file", autospec=True, side_effect=lambda path: path == executable),
                patch("src.dev.shutil.which", return_value="explorer.exe"),
                patch("src.dev.subprocess.Popen") as process,
            ):
                dev.open_regular_chrome()

            local_app_data = root if location == "LOCALAPPDATA" else Path.home() / "AppData/Local"
            self.assertEqual(
                process.call_args_list[0].args[0],
                [
                    str(executable),
                    f"--user-data-dir={local_app_data / 'Google/Chrome/User Data'}",
                    "chrome://extensions/",
                ],
            )
            self.assertEqual(process.call_args_list[1].args[0], ["explorer.exe", str(dev.EXTENSION_PATH)])

    def test_linux_uses_path_and_profile_environment(self):
        cases = [
            ({}, Path.home() / ".config/google-chrome"),
            ({"XDG_CONFIG_HOME": "/config"}, Path("/config/google-chrome")),
            ({"XDG_CONFIG_HOME": "/config", "CHROME_CONFIG_HOME": "/chrome"}, Path("/chrome/google-chrome")),
            ({"CHROME_CONFIG_HOME": "/chrome", "CHROME_USER_DATA_DIR": "/profile"}, Path("/profile")),
        ]
        commands = {"google-chrome-stable": "/usr/bin/google-chrome-stable", "xdg-open": "/usr/bin/xdg-open"}
        for environment, profile in cases:
            with (
                self.subTest(environment=environment),
                patch("src.dev.sys.platform", "linux"),
                patch.dict(dev.os.environ, environment, clear=True),
                patch("src.dev.shutil.which", side_effect=commands.get),
                patch("src.dev.Path.is_file", return_value=True),
                patch("src.dev.subprocess.Popen") as process,
            ):
                dev.open_regular_chrome()

            self.assertEqual(
                process.call_args_list[0].args[0],
                [
                    "/usr/bin/google-chrome-stable",
                    f"--user-data-dir={profile}",
                    "chrome://extensions/",
                ],
            )
            self.assertEqual(process.call_args_list[1].args[0], ["/usr/bin/xdg-open", str(dev.EXTENSION_PATH)])

    def test_missing_chrome_does_not_launch_a_process(self):
        for platform in ("darwin", "win32", "linux"):
            with (
                self.subTest(platform=platform),
                patch("src.dev.sys.platform", platform),
                patch("src.dev.shutil.which", return_value=None),
                patch("src.dev.Path.is_file", return_value=False),
                patch("src.dev.subprocess.Popen") as process,
            ):
                with self.assertRaisesRegex(RuntimeError, "Chrome not found"):
                    dev.open_regular_chrome()
            process.assert_not_called()

    def test_missing_folder_opener_prints_path_after_launching_chrome(self):
        with (
            patch("src.dev.sys.platform", "darwin"),
            patch("src.dev.Path.is_file", return_value=True),
            patch("src.dev.shutil.which", return_value=None),
            patch("src.dev.subprocess.Popen") as process,
            patch("sys.stdout", new=io.StringIO()) as output,
        ):
            dev.open_regular_chrome()
        process.assert_called_once()
        self.assertIn(str(dev.EXTENSION_PATH), output.getvalue())

    def test_default_launch_opens_usual_chrome_without_automation(self):
        with (
            patch("src.dev.sys.platform", "darwin"),
            patch("src.dev.sys.argv", ["src.dev"]),
            patch("src.dev.Path.is_file", return_value=True),
            patch("src.dev.subprocess.Popen") as process,
            patch("src.dev.shutil.which", return_value="/usr/bin/open"),
            patch("src.dev.run_dev") as isolated,
            patch("src.dev.build_frontend"),
        ):
            dev.main()

        self.assertEqual(
            process.call_args_list[0].args[0],
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                f"--user-data-dir={Path.home() / 'Library/Application Support/Google/Chrome'}",
                "chrome://extensions/",
            ],
        )
        self.assertEqual(process.call_args_list[1].args[0], ["/usr/bin/open", str(dev.EXTENSION_PATH)])
        isolated.assert_not_called()

    def test_source_extension_starts_from_outside_the_repository(self):
        with tempfile.TemporaryDirectory(prefix="aiorganize-dev-test-") as directory:
            result = subprocess.run(
                [sys.executable, "-m", "src.dev", "--check", "--profile", str(Path(directory) / "chrome")],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
