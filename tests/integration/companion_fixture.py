"""Native host fixture with the real agent graph and a deterministic local model."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from langchain.messages import AIMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.outputs import ChatGeneration, ChatResult

from aiorganize.companion import main


class PanelFixtureModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        listed = next((message for message in results if message.name == "list_tabs"), None)
        prepared = next((message.content.split("(untrusted data):\n", 1)[1]
                         for message in messages if isinstance(message.content, str)
                         and "(untrusted data):\n" in message.content), None)
        if listed is None and prepared is None:
            name, args = "list_tabs", {}
        else:
            context = json.loads(prepared) if prepared is not None else {"tabs": json.loads(listed.content)}
            tabs = context["tabs"]
            reads = context.get("page_reads", []) + [
                json.loads(message.content) for message in results if message.name == "read_tab"
            ]
            trace = Path(os.environ["AIORGANIZE_TEST_TRACE"])
            trace.write_text(json.dumps(reads))
            counter = trace.with_suffix(".calls")
            count = int(counter.read_text()) if counter.exists() else 0
            counter.write_text(str(count + 1))
            read_ids = {read["id"] for read in reads}
            ambiguous = next((tab for tab in tabs if tab["title"] in {"ChatGPT", "New Tab", ""}
                              and tab["id"] not in read_ids), None)
            if ambiguous:
                name, args = "read_tab", {"tab_id": ambiguous["id"]}
            else:
                name = "GroupingProposal"
                args = {"groups": [
                    {"name": "Dev", "tab_ids": [tab["id"] for tab in tabs[:2]]},
                    {"name": "Other", "tab_ids": [tab["id"] for tab in tabs[2:]]},
                ]}
        response = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{len(results)}"}])
        return ChatResult(generations=[ChatGeneration(message=response)])


if __name__ == "__main__":
    # No provider request or real credential is used by this fixture.
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch(
        "aiorganize.agent.ChatOpenAI", return_value=PanelFixtureModel(responses=[])
    ):
        main()
