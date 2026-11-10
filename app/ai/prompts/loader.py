"""Load prompts by fixed ID without accepting arbitrary filesystem paths."""
from importlib.resources import files
from string import Formatter

from langchain_core.prompts import ChatPromptTemplate

PROMPTS = {"foundation_probe.v1": "foundation_probe_v1.txt"}


def load_prompt(prompt_id: str, **variables: str) -> ChatPromptTemplate:
    filename = PROMPTS.get(prompt_id)
    if filename is None:
        raise ValueError("未知提示词版本")
    source = files("app.ai.prompts").joinpath(filename).read_text(encoding="utf-8")
    expected = {name for _, name, _, _ in Formatter().parse(source) if name}
    if expected != set(variables):
        raise ValueError("提示词变量不匹配")
    return ChatPromptTemplate.from_messages([
        ("system", source),
        ("human", "{input_text}"),
    ]).partial(**variables)
