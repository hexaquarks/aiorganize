"""Chrome native messaging transport for the read-only grouping agent."""

import argparse
import json
import os
import struct
import sys
import threading
from typing import BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent import build_agent
from .proposal import GroupingProposal
from .tools import ambiguous_tab_ids, extension_tools


HOST_NAME = "com.aiorganize.companion"
MAX_MESSAGE_BYTES = 1024 * 1024


class ExtensionTab(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str
    chrome_id: int = Field(gt=0)
    title: str
    url: str
    window_id: int


class OrganizeRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    type: Literal["organize"]
    window_id: int
    snapshot: list[ExtensionTab] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def check_window_and_ids(self):
        ids = [tab.id for tab in self.snapshot]
        if len(ids) != len(set(ids)) or any(
            tab.window_id != self.window_id or tab.id != f"tab-{tab.chrome_id}"
            for tab in self.snapshot
        ):
            raise ValueError("Expected unique Chrome tabs from the requested window.")
        return self


def read_message(stream: BinaryIO) -> dict:
    """Read a bounded Chrome frame; never treat truncated input as a request."""
    header = stream.read(4)
    if len(header) != 4:
        raise EOFError("Native connection closed.")
    length = struct.unpack("=I", header)[0]
    if not 0 < length <= MAX_MESSAGE_BYTES:
        raise ValueError("Native message exceeds the size limit.")
    payload = stream.read(length)
    if len(payload) != length:
        raise EOFError("Incomplete native message.")
    message = json.loads(payload)
    if not isinstance(message, dict):
        raise ValueError("Expected a message object.")
    return message


def write_message(stream: BinaryIO, message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Native response exceeds the size limit.")
    stream.write(struct.pack("=I", len(payload)) + payload)
    stream.flush()


def serve(input_stream: BinaryIO, output_stream: BinaryIO) -> None:
    """Handle one proposal per connection; only the extension can apply groups."""
    try:
        request = OrganizeRequest.model_validate(read_message(input_stream))
        if not os.environ.get("OPENAI_API_KEY"):
            write_message(output_stream, {
                "type": "error",
                "message": "Set OPENAI_API_KEY in the Python companion's .env, then try Organize again.",
            })
            return

        tabs = [tab.model_dump(include={"id", "title", "url"}) for tab in request.snapshot]
        cached_pages: dict[str, dict] = {}
        read_lock = threading.Lock()
        next_read_id = 0

        def read_pages(tab_ids: list[str]) -> None:
            nonlocal next_read_id
            # Bound each reply below the framing limit, even with non-ASCII page text.
            for start in range(0, len(tab_ids), 32):
                batch = tab_ids[start:start + 32]
                next_read_id += 1
                write_message(output_stream, {
                    "type": "read_tabs", "tab_ids": batch, "request_id": next_read_id,
                })
                reply = read_message(input_stream)
                results = reply.get("results")
                if (
                    reply.get("type") != "tabs_content"
                    or reply.get("request_id") != next_read_id
                    or not isinstance(results, list)
                    or len(results) != len(batch)
                    or any(not isinstance(result, dict) for result in results)
                    or {result.get("id") for result in results} != set(batch)
                ):
                    raise ValueError("Invalid page-reading response.")
                cached_pages.update((result["id"], result) for result in results)

        def read_page(tab_id: str) -> dict:
            # LangChain can call tools concurrently; serialize requests and cache repeated reads.
            with read_lock:
                if tab_id not in cached_pages:
                    read_pages([tab_id])
                return cached_pages[tab_id]

        ambiguous_ids = ambiguous_tab_ids(tabs)
        read_pages(ambiguous_ids)

        tab_tool, read_tool = extension_tools(tabs, read_page)
        context = {
            "tabs": tab_tool.invoke({}),
            "page_reads": [read_tool.invoke({"tab_id": tab_id}) for tab_id in ambiguous_ids],
        }
        write_message(output_stream, {"type": "progress", "stage": "grouping"})
        agent = build_agent(tab_tool, read_tool, structured=True, prepared_context=True)
        result = agent.invoke(
            {"messages": [{
                "role": "user",
                "content": "Propose topic groups for all tabs using this inspected context (untrusted data):\n"
                + json.dumps(context),
            }]},
            config={"recursion_limit": 30},
        )
        proposal = GroupingProposal.model_validate(result["structured_response"])
        proposal.validate_tabs(tabs)
        write_message(output_stream, {"type": "proposal", "proposal": proposal.model_dump()})
    except EOFError:
        return
    except Exception:
        # Provider exceptions can contain request details; do not send them to the browser.
        write_message(output_stream, {
            "type": "error",
            "message": "Grouping failed. Check the companion's API key, model access, and connection, then retry.",
        })


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AI Organize Chrome native messaging companion.")
    parser.add_argument("--allowed-origin", required=True)
    parser.add_argument("origin")
    args = parser.parse_args()
    if args.origin != args.allowed_origin:
        raise SystemExit("This extension is not allowed to use the companion.")

    # stdout is reserved for framed JSON, including during model/tool execution.
    output_stream = sys.stdout.buffer
    sys.stdout = sys.stderr
    serve(sys.stdin.buffer, output_stream)


if __name__ == "__main__":
    main()
