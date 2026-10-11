import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DevelopmentStartupTest(unittest.TestCase):
    def test_source_extension_starts_from_outside_the_repository(self):
        with tempfile.TemporaryDirectory(prefix="aiorganize-dev-test-") as directory:
            result = subprocess.run(
                [sys.executable, "-m", "src.dev", "--check", "--profile", str(Path(directory) / "chrome")],
                cwd=directory, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Development startup check passed", result.stdout)
