import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import dev


class DevelopmentStartupTest(unittest.TestCase):
    def test_default_launch_opens_usual_chrome_without_automation(self):
        with patch("src.dev.sys.platform", "darwin"), patch("src.dev.sys.argv", ["src.dev"]), \
                patch("src.dev.Path.is_file", return_value=True), \
                patch("src.dev.subprocess.Popen") as chrome, patch("src.dev.subprocess.run") as finder, \
                patch("src.dev.run_dev") as isolated:
            dev.main()

        self.assertEqual(chrome.call_args.args[0], [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            f"--user-data-dir={Path.home() / 'Library/Application Support/Google/Chrome'}",
            "chrome://extensions/",
        ])
        self.assertEqual(finder.call_args.args[0], ["open", str(dev.EXTENSION_PATH)])
        isolated.assert_not_called()

    def test_source_extension_starts_from_outside_the_repository(self):
        with tempfile.TemporaryDirectory(prefix="aiorganize-dev-test-") as directory:
            result = subprocess.run(
                [sys.executable, "-m", "src.dev", "--check", "--profile", str(Path(directory) / "chrome")],
                cwd=directory, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Development startup check passed", result.stdout)
