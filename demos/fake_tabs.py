import os

from aiorganize.agent import build_agent
from aiorganize.terminal import print_message
from demos.fake_tools import list_tabs, read_tab


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "Set OPENAI_API_KEY or run: make run"
        )

    agent = build_agent(list_tabs, read_tab)
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
