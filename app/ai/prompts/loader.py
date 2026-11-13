"""Load prompts by fixed ID without accepting arbitrary filesystem paths."""
from importlib.resources import files
from string import Formatter

from langchain_core.prompts import ChatPromptTemplate

PROMPTS = {
    "foundation_probe.v1": "foundation_probe_v1.txt",
    "sport_import_training.v1": "sport_import_training_v1.txt",
    "sport_import_swim.v1": "sport_import_swim_v1.txt",
    "sport_import_dance.v1": "sport_import_dance_v1.txt",
    "agent_chat.v1": "agent_chat_v1.txt",
    "agent_chat.v2": "agent_chat_v2.txt",
    "agent_chat.v3": "agent_chat_v3.txt",
}


def _load_source(prompt_id: str, **variables: str) -> str:
    filename = PROMPTS.get(prompt_id)
    if filename is None:
        raise ValueError("未知提示词版本")
    source = files("app.ai.prompts").joinpath(filename).read_text(encoding="utf-8")
    expected = {name for _, name, _, _ in Formatter().parse(source) if name}
    if expected != set(variables):
        raise ValueError("提示词变量不匹配")
    return source.format(**variables)


def load_prompt(prompt_id: str, **variables: str) -> ChatPromptTemplate:
    source = _load_source(prompt_id, **variables)
    return ChatPromptTemplate.from_messages([
        ("system", source),
        ("human", "{input_text}"),
    ])


def load_system_prompt(prompt_id: str, **variables: str) -> str:
    """Return rendered system text only (for LangGraph nodes)."""
    return _load_source(prompt_id, **variables)
