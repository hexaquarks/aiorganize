from langchain.tools import tool


@tool
def list_tabs() -> list[dict[str, int | str]]:
    """List three fake browser tabs with their IDs, titles, and URLs."""
    return [
        {"id": 1, "title": "Python Tutorial", "url": "https://docs.python.org/3/tutorial/"},
        {"id": 2, "title": "LangChain Docs", "url": "https://docs.langchain.com/"},
        {"id": 3, "title": "ChatGPT", "url": "https://chatgpt.com/"},
    ]


@tool
def read_tab(tab_id: int) -> dict[str, int | str]:
    """Read the text of a fake tab by its ID to understand its topic."""
    content = {
        1: "Learn Python functions, loops, and classes.",
        2: "Build Python agents using LangChain tools and chat models.",
        3: "A conversation about making fresh pasta and tomato sauce.",
    }
    if tab_id not in content:
        return {"id": tab_id, "error": "Tab not found."}
    return {"id": tab_id, "content": content[tab_id]}
