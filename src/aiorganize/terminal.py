import json

from langchain.messages import AIMessage, ToolMessage
from langchain_core.messages import BaseMessage


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
