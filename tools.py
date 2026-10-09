from langchain.tools import tool


@tool
def list_tabs() -> list[dict[str, int | str]]:
    """List three fake browser tabs with their IDs, titles, and URLs."""
    return [
        {"id": 1, "title": "Python Tutorial", "url": "https://docs.python.org/3/tutorial/"},
        {"id": 2, "title": "LangChain Docs", "url": "https://docs.langchain.com/"},
        {"id": 3, "title": "Wikipedia", "url": "https://en.wikipedia.org/"},
    ]
