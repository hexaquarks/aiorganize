import json
import os

from langchain.messages import AIMessage, ToolMessage
from langchain_core.messages import BaseMessage

from agent import build_agent


def print_message(message: BaseMessage) -> None:
    if isinstance(message, AIMessage):
        if message.tool_calls:
            for call in message.tool_calls:
                print(f"\nTool request: {call['name']}({json.dumps(call['args'])})", flush=True)
        else:
            print(f"\nFinal answer (proposal only):\n{message.text}", flush=True)
    elif isinstance(message, ToolMessage):
        print(f"\nTool result ({message.name}):\n{message.content}", flush=True)
    else:
        message.pretty_print()


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "Set OPENAI_API_KEY or run: uv run --env-file .env python main.py"
        )

    agent = build_agent()
    prompt = "Inspect ambiguous tabs and propose topic groups for all the tabs."
    print(f"Prompt: {prompt}", flush=True)

    # Stream completed steps so we can watch the model -> tool -> model sequence.
    for update in agent.stream(
        {"messages": [{"role": "user", "content": prompt}]},
        stream_mode="updates",
        config={"recursion_limit": 30},
    ):
        for step in update.values():
            # Middleware also emits counter updates without conversation messages.
            if step is None:
                continue
            for message in step.get("messages", []):
                print_message(message)


if __name__ == "__main__":
    main()
