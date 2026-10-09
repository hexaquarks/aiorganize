import os

from langchain.messages import AIMessage
from langchain_core.messages import BaseMessage

from agent import build_agent


def print_message(message: BaseMessage) -> None:
    if isinstance(message, AIMessage) and not message.tool_calls:
        print(f"\nFinal answer:\n{message.text}", flush=True)
    else:
        message.pretty_print()


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "Set OPENAI_API_KEY or run: uv run --env-file .env python main.py"
        )

    agent = build_agent()
    prompt = "Please list the tabs."
    print(f"Prompt: {prompt}", flush=True)

    # Stream completed steps so we can watch the model -> tool -> model sequence.
    for update in agent.stream(
        {"messages": [{"role": "user", "content": prompt}]},
        stream_mode="updates",
    ):
        for step in update.values():
            for message in step["messages"]:
                print_message(message)


if __name__ == "__main__":
    main()
