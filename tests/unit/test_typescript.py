import subprocess
import tempfile
import unittest
from pathlib import Path

from src.build import PROJECT


class TypeScriptContractTest(unittest.TestCase):
    def test_typescript_contracts(self):
        for source in sorted((PROJECT / "tests/unit").glob("*.test.ts")):
            with self.subTest(source=source.name):
                self.run_contract_tests(source)

    def run_contract_tests(self, source):
        with tempfile.TemporaryDirectory(prefix="aiorganize-vector-tests-") as directory:
            bundle = Path(directory) / "contract.test.mjs"
            compile_result = subprocess.run(
                [
                    "node",
                    "tests/unit/build_contract_test.mjs",
                    directory,
                    str(source),
                ],
                cwd=PROJECT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)

            result = subprocess.run(
                ["node", "--test", str(bundle)],
                cwd=PROJECT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
