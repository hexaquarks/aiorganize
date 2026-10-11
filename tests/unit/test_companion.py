import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from src.companion import OrganizeRequest, read_message, serve, write_message
from src.install_companion import install_companion
from src.tools import extension_tools


def request_frame(**changes):
    request = {
        "type": "organize", "window_id": 1,
        "snapshot": [{"id": "tab-1", "chrome_id": 1, "window_id": 1, "title": "ChatGPT", "url": "https://test/"}],
    }
    request.update(changes)
    stream = io.BytesIO()
    write_message(stream, request)
    stream.seek(0)
    return stream


class CompanionTest(unittest.TestCase):
    def test_native_frames_handle_unicode_and_reject_invalid_input(self):
        stream = io.BytesIO()
        write_message(stream, {"title": "旅行"})
        stream.seek(0)
        self.assertEqual(read_message(stream), {"title": "旅行"})
        for data in (b"", b"\x00", struct.pack("=I", 20) + b"{}"):
            with self.assertRaises(EOFError):
                read_message(io.BytesIO(data))
        for data in (struct.pack("=I", 2**20 + 1), struct.pack("=I", 2) + b"[]"):
            with self.assertRaises(ValueError):
                read_message(io.BytesIO(data))

    def test_request_restricts_ids_and_window(self):
        self.assertEqual(len(OrganizeRequest.model_validate(read_message(request_frame())).snapshot), 1)
        for changes in ({"window_id": 2}, {"snapshot": []}):
            with self.assertRaises(ValidationError):
                OrganizeRequest.model_validate(read_message(request_frame(**changes)))
        request = read_message(request_frame())
        request["snapshot"] *= 2
        with self.assertRaises(ValidationError):
            OrganizeRequest.model_validate(request)

    def test_missing_key_and_provider_failure_return_safe_errors(self):
        output = io.BytesIO()
        with patch.dict(os.environ, {}, clear=True):
            serve(request_frame(), output)
        output.seek(0)
        self.assertIn("OPENAI_API_KEY", read_message(output)["message"])
        output = io.BytesIO()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch(
            "src.companion.build_agent", side_effect=RuntimeError("sensitive provider detail")
        ):
            request = read_message(request_frame())
            request["snapshot"][0]["title"] = "Python tutorial"
            source = io.BytesIO()
            write_message(source, request)
            source.seek(0)
            serve(source, output)
        output.seek(0)
        self.assertEqual(read_message(output)["type"], "progress")
        response = read_message(output)
        self.assertEqual(response["type"], "error")
        self.assertNotIn("sensitive", response["message"])

    def test_native_entry_point_rejects_other_extensions_before_reading(self):
        result = subprocess.run([
            sys.executable, "-m", "src.companion", "--allowed-origin",
            "chrome-extension://allowed/", "chrome-extension://other/",
        ], input=b"", capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"not allowed", result.stderr)

    def test_extension_tools_restrict_reads_and_limit_content(self):
        calls = []

        def read_page(tab_id):
            calls.append(tab_id)
            return {"content": "x" * 5000}

        tabs = [{"id": "tab-1", "title": "ChatGPT", "url": "https://test/"}]
        tab_tool, read_tool = extension_tools(tabs, read_page)
        self.assertEqual(tab_tool.invoke({}), tabs)
        self.assertIn("error", read_tool.invoke({"tab_id": "tab-2"}))
        self.assertEqual(calls, [])
        self.assertEqual(len(read_tool.invoke({"tab_id": "tab-1"})["content"]), 4000)

    def test_page_reads_are_bounded_and_repeated_tool_reads_are_cached(self):
        tabs = [{
            "id": f"tab-{index}", "chrome_id": index, "window_id": 1,
            "title": "ChatGPT" if index < 34 else "Python tutorial", "url": "https://test/",
        } for index in range(1, 35)]
        source = request_frame(snapshot=tabs)
        source.seek(0, io.SEEK_END)
        for request_id, batch in enumerate((tabs[:32], tabs[32:33], tabs[33:]), start=1):
            write_message(source, {
                "type": "tabs_content", "request_id": request_id,
                "results": [{"id": tab["id"], "content": "Page text"} for tab in batch],
            })
        source.seek(0)
        output = io.BytesIO()

        def build_test_agent(tab_tool, read_tool, **kwargs):
            def invoke(*args, **kwargs):
                first = read_tool.invoke({"tab_id": "tab-34"})
                self.assertEqual(first, read_tool.invoke({"tab_id": "tab-34"}))
                return {"structured_response": {"groups": [{
                    "name": "Dev", "tab_ids": [tab["id"] for tab in tabs],
                }]}}

            return SimpleNamespace(invoke=invoke)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch(
            "src.companion.build_agent", side_effect=build_test_agent,
        ):
            serve(source, output)

        output.seek(0)
        messages = []
        while output.tell() < len(output.getvalue()):
            messages.append(read_message(output))
        batches = [message["tab_ids"] for message in messages if message["type"] == "read_tabs"]
        self.assertEqual([len(batch) for batch in batches], [32, 1, 1])
        self.assertEqual(messages[-1]["type"], "proposal")

    def test_registration_restricts_extension_and_keeps_key_out_of_files(self):
        with tempfile.TemporaryDirectory(prefix="companion spaces ") as temp:
            project = Path(temp) / "project"
            project.mkdir()
            (project / ".env").write_text("OPENAI_API_KEY=secret-fixture\n")
            manifest = install_companion("a" * 32, project, Path(temp) / "hosts")
            config = json.loads(manifest.read_text())
            self.assertEqual(config["allowed_origins"], ["chrome-extension://" + "a" * 32 + "/"])
            launcher = Path(config["path"])
            self.assertIn("--env-file", launcher.read_text())
            self.assertNotIn("secret-fixture", launcher.read_text() + manifest.read_text())
            self.assertEqual(launcher.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(ValueError):
                install_companion("invalid", project, Path(temp) / "hosts")
