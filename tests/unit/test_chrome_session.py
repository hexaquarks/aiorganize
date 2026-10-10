import unittest
from pathlib import Path
from unittest.mock import patch

from demos.chrome_session import ensure_debug_chrome


class ChromeSessionTest(unittest.TestCase):
    @patch("demos.chrome_session.os.kill")
    @patch("demos.chrome_session._debug_endpoint_responds", return_value=True)
    @patch("demos.chrome_session._port_owner_pids", return_value={123})
    @patch("demos.chrome_session._port_is_open", return_value=True)
    @patch("demos.chrome_session._profile_chrome_pids", return_value={123})
    def test_healthy_project_session_is_reused(self, profile_pids, port_open, owner_pids, endpoint, kill):
        self.assertIn("Reusing", ensure_debug_chrome())
        kill.assert_not_called()

    @patch("demos.chrome_session.os.kill")
    @patch("demos.chrome_session._port_owner_pids", return_value={456})
    @patch("demos.chrome_session._port_is_open", return_value=True)
    @patch("demos.chrome_session._profile_chrome_pids", return_value={123})
    def test_another_process_on_the_port_is_untouched(self, profile_pids, port_open, owner_pids, kill):
        with self.assertRaisesRegex(RuntimeError, "another process"):
            ensure_debug_chrome()
        kill.assert_not_called()

    @patch("demos.chrome_session.subprocess.run")
    @patch("demos.chrome_session.time.sleep")
    @patch("demos.chrome_session.os.kill")
    @patch("demos.chrome_session._chrome_app", return_value=Path("/Applications/Google Chrome.app"))
    @patch("demos.chrome_session._debug_endpoint_responds", side_effect=[False, True])
    @patch("demos.chrome_session._port_owner_pids", return_value={123})
    @patch("demos.chrome_session._port_is_open", side_effect=[True, False])
    @patch("demos.chrome_session._profile_chrome_pids", side_effect=[{123}, set()])
    def test_stale_project_session_is_closed_before_launch(
        self, profile_pids, port_open, owner_pids, endpoint, chrome_app, kill, sleep, run
    ):
        self.assertIn("Started", ensure_debug_chrome())
        kill.assert_called_once()
        run.assert_called_once()
