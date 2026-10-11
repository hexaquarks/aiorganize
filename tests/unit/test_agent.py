import unittest
from unittest.mock import patch

from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain.messages import AIMessage
from langchain.tools import tool
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from src.agent import build_agent
from demos.fake_tools import read_tab


class RepeatingToolModel(FakeMessagesListChatModel):
    """Always request a tool so the limit is tested without calling OpenAI."""

    def bind_tools(self, tools, **kwargs):
        return self


class AgentLimitTest(unittest.TestCase):
    def test_repeated_tool_calls_stop_after_ten_executions(self):
        calls = []

        @tool("list_tabs")
        def counted_tool() -> list:
            """List test tabs."""
            calls.append(1)
            return []

        model = RepeatingToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "list_tabs", "args": {}, "id": f"repeat-{index}"}],
                )
                for index in range(11)
            ]
        )
        with patch("src.agent.ChatOpenAI", return_value=model):
            agent = build_agent(counted_tool, read_tab)
            with self.assertRaises(ToolCallLimitExceededError):
                agent.invoke(
                    {"messages": [{"role": "user", "content": "List tabs"}]},
                    config={"recursion_limit": 40},
                )
        self.assertEqual(len(calls), 10)


if __name__ == "__main__":
    unittest.main()
