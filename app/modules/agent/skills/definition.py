"""声明式技能定义：结构、校验与安全边界。

只允许声明式配置：参数类型限定 date/int/bool/enum，数据源与字段走白名单，
输出值只支持受控引用与 + - * / 四则运算；不接受 SQL、代码或任意字符串。
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.modules.agent.tools.queries import BODY_METRIC_WHITELIST, SPORT_KEYS

SCHEMA_VERSION = 1
PARAM_TYPES = ("date", "int", "bool", "enum")
SOURCE_TYPES = ("body_metric", "swim_records", "fitness_records", "dance_records",
                "workout_summary", "state_records", "cycle_records", "profile_info")
STEP_OPS = ("first", "last", "count", "sum", "avg", "min", "max", "group_count")
STATE_TYPES = ("appetite", "myalgia", "inflammation", "mood")

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
REF_RE = re.compile(r"\$([a-z][a-z0-9_]*)(?:\.([a-z][a-z0-9_]*))?")

TOP_KEYS = {"schema_version", "params", "sources", "steps", "outputs", "summary"}
PARAM_KEYS = {"key", "type", "required", "default", "min", "max", "values", "label"}
SOURCE_KEYS = {"key", "type", "metric", "sport", "state_type", "range", "limit"}
STEP_KEYS = {"key", "op", "source", "field"}
OUTPUT_KEYS = {"key", "label", "value", "unit"}

MAX_PARAMS = 6
MAX_SOURCES = 4
MAX_STEPS = 8
MAX_OUTPUTS = 12
MAX_SUMMARY = 200
MAX_STRING = 120

PROMPT_MAX_CHARS = 4000
PROMPT_KEYS = {"schema_version", "prompt"}


@dataclass(frozen=True)
class PromptDefinition:
    schema_version: int
    prompt: str
    raw: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class SkillParam:
    key: str
    type: str
    required: bool
    default: Any
    min: int | float | None
    max: int | float | None
    values: tuple[str, ...]
    label: str


@dataclass(frozen=True)
class SkillSource:
    key: str
    type: str
    metric: str | None
    sport: str | None
    state_type: str | None
    range_start: Any
    range_end: Any
    limit: Any


@dataclass(frozen=True)
class SkillStep:
    key: str
    op: str
    source: str
    field: str | None


@dataclass(frozen=True)
class SkillOutput:
    key: str
    label: str
    value: str
    unit: str | None


@dataclass(frozen=True)
class DeclarativeDefinition:
    schema_version: int
    params: tuple[SkillParam, ...]
    sources: tuple[SkillSource, ...]
    steps: tuple[SkillStep, ...]
    outputs: tuple[SkillOutput, ...]
    summary: str
    raw: dict = field(default_factory=dict, compare=False)


class DefinitionInvalid(ValueError):
    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("技能定义无效")


def _err(errors: list[dict], field_name: str, reason: str) -> None:
    errors.append({"field": field_name, "reason": reason})


def _is_str(value: Any, limit: int = MAX_STRING) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit


def _check_keys(obj: Any, allowed: set[str], path: str, errors: list[dict]) -> None:
    if not isinstance(obj, dict):
        _err(errors, path, "必须是对象")
        return
    extra = set(obj) - allowed
    if extra:
        _err(errors, path, "不允许的字段：" + "、".join(sorted(extra)))


def _check_ref(value: Any, known: set[str], path: str, errors: list[dict]) -> None:
    if not isinstance(value, str):
        _err(errors, path, "必须是引用或 null")
        return
    m = REF_RE.fullmatch(value)
    if not m:
        _err(errors, path, "引用格式无效（应形如 $step.field）")
        return
    if m.group(1) not in known:
        _err(errors, path, "引用了不存在的参数/数据源/步骤：" + m.group(1))


def parse_definition(raw: dict) -> DeclarativeDefinition:
    errors: list[dict] = []
    warnings: list[str] = []
    if not isinstance(raw, dict):
        raise DefinitionInvalid([{"field": "definition", "reason": "必须是 JSON 对象"}])

    _check_keys(raw, TOP_KEYS, "definition", errors)
    if raw.get("schema_version") != SCHEMA_VERSION:
        _err(errors, "schema_version", "仅支持 schema_version=1")
    summary = raw.get("summary")
    if not _is_str(summary, MAX_SUMMARY):
        _err(errors, "summary", "必须是 1~200 字字符串")

    params_raw = raw.get("params")
    if not isinstance(params_raw, list) or not 1 <= len(params_raw) <= MAX_PARAMS:
        _err(errors, "params", f"参数数量必须为 1~{MAX_PARAMS} 个")
        params_raw = []
    params: list[SkillParam] = []
    param_keys: set[str] = set()
    for i, item in enumerate(params_raw):
        path = f"params[{i}]"
        _check_keys(item, PARAM_KEYS, path, errors)
        if not isinstance(item, dict):
            continue
        key = item.get("key", "")
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            _err(errors, path + ".key", "参数键需为小写字母开头的 1~32 位字母数字下划线")
            continue
        if key in param_keys:
            _err(errors, path + ".key", "参数键重复")
            continue
        param_keys.add(key)
        ptype = item.get("type")
        if ptype not in PARAM_TYPES:
            _err(errors, path + ".type", "类型仅支持 date / int / bool / enum")
            continue
        required = item.get("required", True)
        if not isinstance(required, bool):
            _err(errors, path + ".required", "必须为布尔值")
        label = item.get("label", key)
        if not _is_str(label, 40):
            _err(errors, path + ".label", "标签需为 1~40 字字符串")
        values = item.get("values") or ()
        if ptype == "enum":
            if not isinstance(values, list) or not 1 <= len(values) <= 20 or not all(_is_str(v, 24) for v in values):
                _err(errors, path + ".values", "枚举值需为 1~20 个非空字符串")
                values = ()
        elif "values" in item:
            _err(errors, path + ".values", "仅 enum 类型可以声明 values")
            values = ()
        default = item.get("default")
        if not required and default is None and ptype != "bool":
            warnings.append(f"{path} 非必填但未设置 default，缺省时按空值处理")
        if ptype == "int":
            for bound in ("min", "max"):
                if item.get(bound) is not None and not isinstance(item.get(bound), int):
                    _err(errors, f"{path}.{bound}", "必须为整数")
            if isinstance(item.get("min"), int) and isinstance(item.get("max"), int) and item["min"] > item["max"]:
                _err(errors, path, "min 不能大于 max")
        elif "min" in item or "max" in item:
            _err(errors, path, "仅 int 类型可以声明 min / max")
        params.append(SkillParam(key, ptype, required, default, item.get("min"), item.get("max"),
                                 tuple(values), label))

    sources_raw = raw.get("sources")
    if not isinstance(sources_raw, list) or not 1 <= len(sources_raw) <= MAX_SOURCES:
        _err(errors, "sources", f"数据源数量必须为 1~{MAX_SOURCES} 个")
        sources_raw = []
    sources: list[SkillSource] = []
    source_keys: set[str] = set()
    for i, item in enumerate(sources_raw):
        path = f"sources[{i}]"
        _check_keys(item, SOURCE_KEYS, path, errors)
        if not isinstance(item, dict):
            continue
        key = item.get("key", "")
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            _err(errors, path + ".key", "数据源键需为小写字母开头")
            continue
        if key in source_keys:
            _err(errors, path + ".key", "数据源键重复")
            continue
        source_keys.add(key)
        stype = item.get("type")
        if stype not in SOURCE_TYPES:
            _err(errors, path + ".type", "不支持的数据源类型")
            continue
        metric = item.get("metric")
        sport = item.get("sport")
        state_type = item.get("state_type")
        if stype == "body_metric":
            if metric not in BODY_METRIC_WHITELIST:
                _err(errors, path + ".metric", "身材指标不在白名单")
        elif "metric" in item:
            _err(errors, path + ".metric", "该数据源不支持 metric")
        if stype == "workout_summary":
            if sport is not None and sport not in (*SPORT_KEYS, "all"):
                _err(errors, path + ".sport", "运动类型不合法")
        elif "sport" in item:
            _err(errors, path + ".sport", "该数据源不支持 sport")
        if stype == "state_records":
            if state_type is not None and state_type not in (*STATE_TYPES, "all"):
                _err(errors, path + ".state_type", "状态类型不合法")
        elif "state_type" in item:
            _err(errors, path + ".state_type", "该数据源不支持 state_type")

        range_value = item.get("range", [None, None])
        if not isinstance(range_value, list) or len(range_value) != 2:
            _err(errors, path + ".range", "range 必须是 [开始, 结束] 两元素数组")
            range_value = [None, None]
        for j, end in enumerate(range_value):
            rpath = f"{path}.range[{j}]"
            if end is None:
                continue
            if isinstance(end, str) and end.startswith("$"):
                m = REF_RE.fullmatch(end)
                if not m or m.group(1) not in param_keys:
                    _err(errors, rpath, "区间端点只能引用日期参数")
                else:
                    p = next((p for p in params if p.key == m.group(1)), None)
                    if p is None or p.type != "date":
                        _err(errors, rpath, "区间端点必须引用 date 参数")
            elif isinstance(end, str):
                try:
                    date.fromisoformat(end)
                except ValueError:
                    _err(errors, rpath, "日期字面量需为 YYYY-MM-DD")
            else:
                _err(errors, rpath, "区间端点只能是 null、日期参数引用或 YYYY-MM-DD")

        limit = item.get("limit")
        if limit is not None:
            if isinstance(limit, str) and limit.startswith("$"):
                m = REF_RE.fullmatch(limit)
                if not m or m.group(1) not in param_keys:
                    _err(errors, path + ".limit", "limit 只能引用 int 参数")
                else:
                    p = next((p for p in params if p.key == m.group(1)), None)
                    if p is None or p.type != "int":
                        _err(errors, path + ".limit", "limit 必须引用 int 参数")
            elif not isinstance(limit, int) or not 1 <= limit <= 500:
                _err(errors, path + ".limit", "limit 必须是 1~500 的整数")
        if stype in ("cycle_records", "profile_info") and limit is not None:
            _err(errors, path + ".limit", "该数据源不支持 limit")
        sources.append(SkillSource(key, stype, metric, sport, state_type,
                                   range_value[0], range_value[1], limit))

    steps_raw = raw.get("steps", [])
    if not isinstance(steps_raw, list) or len(steps_raw) > MAX_STEPS:
        _err(errors, "steps", f"步骤最多 {MAX_STEPS} 个")
        steps_raw = []
    steps: list[SkillStep] = []
    step_keys: set[str] = set()
    known_step_refs: set[str] = set(param_keys | source_keys)
    for i, item in enumerate(steps_raw):
        path = f"steps[{i}]"
        _check_keys(item, STEP_KEYS, path, errors)
        if not isinstance(item, dict):
            continue
        key = item.get("key", "")
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            _err(errors, path + ".key", "步骤键需为小写字母开头")
            continue
        if key in step_keys:
            _err(errors, path + ".key", "步骤键重复")
            continue
        step_keys.add(key)
        op = item.get("op")
        if op not in STEP_OPS:
            _err(errors, path + ".op", "不支持的算子")
            continue
        src = item.get("source")
        if src not in source_keys:
            _err(errors, path + ".source", "引用了不存在的数据源")
        field_name = item.get("field")
        if op in ("sum", "avg", "min", "max", "group_count"):
            if not _is_str(field_name, 48):
                _err(errors, path + ".field", "该算子必须声明 field")
        elif field_name is not None:
            _err(errors, path + ".field", "该算子不支持 field")
        # 步骤参数校验在已知步骤集合补齐后进行（见下方引用扫描）
        steps.append(SkillStep(key, op, src, field_name))
    known_step_refs |= step_keys

    outputs_raw = raw.get("outputs")
    if not isinstance(outputs_raw, list) or not 1 <= len(outputs_raw) <= MAX_OUTPUTS:
        _err(errors, "outputs", f"输出数量必须为 1~{MAX_OUTPUTS} 个")
        outputs_raw = []
    outputs: list[SkillOutput] = []
    output_keys: set[str] = set()
    for i, item in enumerate(outputs_raw):
        path = f"outputs[{i}]"
        _check_keys(item, OUTPUT_KEYS, path, errors)
        if not isinstance(item, dict):
            continue
        key = item.get("key", "")
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            _err(errors, path + ".key", "输出键需为小写字母开头")
            continue
        if key in output_keys:
            _err(errors, path + ".key", "输出键重复")
            continue
        output_keys.add(key)
        label = item.get("label")
        if not _is_str(label, 40):
            _err(errors, path + ".label", "标签需为 1~40 字字符串")
        value = item.get("value")
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            _err(errors, path + ".value", "值表达式需为 1~200 字符")
        else:
            validate_expression(value, known_step_refs, path + ".value", errors)
        unit = item.get("unit")
        if unit is not None and not _is_str(unit, 12):
            _err(errors, path + ".unit", "单位需为 1~12 字字符串")
        outputs.append(SkillOutput(key, label or key, value or "", unit))

    # 引用扫描：步骤/输出里的 $ref 必须在已知集合内；表达式内部另行校验
    for i, step in enumerate(steps):
        for attr in ("field",):
            value = getattr(step, attr)
            if isinstance(value, str) and value.startswith("$"):
                _check_ref(value, known_step_refs, f"steps[{i}].{attr}", errors)

    if isinstance(summary, str) and output_keys:
        for token in re.findall(r"\{([a-z][a-z0-9_]*)\}", summary):
            if token not in output_keys:
                _err(errors, "summary", f"占位符 {{{token}}} 没有对应输出")

    if errors:
        raise DefinitionInvalid(errors)
    return DeclarativeDefinition(SCHEMA_VERSION, tuple(params), tuple(sources), tuple(steps),
                                 tuple(outputs), summary, raw)


def expression_refs(expr: str) -> list[str]:
    return [m.group(0) for m in REF_RE.finditer(expr)]


def validate_expression(expr: str, known: set[str], path: str, errors: list[dict]) -> None:
    """表达式白名单：引用 + 数值 + 括号 + 四则运算，禁止函数调用/属性访问/字符串。"""
    refs = expression_refs(expr)
    stripped = expr
    for ref in sorted(set(refs), key=len, reverse=True):
        stripped = stripped.replace(ref, "0")
    if not re.fullmatch(r"[0-9eE+\-*/().\s]*", stripped):
        _err(errors, path, "表达式只允许数值、引用、括号与 + - * /")
        return
    for ref in refs:
        m = REF_RE.fullmatch(ref)
        if not m or m.group(1) not in known:
            _err(errors, path, "引用了不存在的参数/数据源/步骤：" + ref)


def expression_ast(expr: str) -> tuple[ast.Expression, dict[str, str]]:
    """把 $ref 替换为安全变量名，返回 AST 与变量映射。调用前必须已通过 validate_expression。"""
    mapping: dict[str, str] = {}
    rewritten = expr
    for idx, ref in enumerate(sorted(set(expression_refs(expr)), key=len, reverse=True)):
        name = f"ref_{idx}"
        mapping[name] = ref
        rewritten = rewritten.replace(ref, name)
    tree = ast.parse(rewritten, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            raise ValueError("表达式不允许函数调用")
        if isinstance(node, ast.Attribute):
            raise ValueError("表达式不允许属性访问")
        if isinstance(node, ast.Subscript):
            raise ValueError("表达式不允许下标访问")
    return tree, mapping


def summarize_definition(defn: DeclarativeDefinition) -> dict:
    return {
        "params": len(defn.params),
        "sources": len(defn.sources),
        "steps": len(defn.steps),
        "outputs": len(defn.outputs),
        "source_types": sorted({s.type for s in defn.sources}),
    }


def parse_prompt_definition(raw: dict) -> PromptDefinition:
    """提示词技能定义：只承载一段提示词，不含取数逻辑。"""
    errors: list[dict] = []
    if not isinstance(raw, dict):
        raise DefinitionInvalid([{"field": "definition", "reason": "必须是 JSON 对象"}])

    _check_keys(raw, PROMPT_KEYS, "definition", errors)
    version = raw.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION:
        _err(errors, "schema_version", "仅支持 schema_version=1")
    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        _err(errors, "prompt", "提示词不能为空")
    elif len(prompt.strip()) > PROMPT_MAX_CHARS:
        _err(errors, "prompt", f"提示词最多 {PROMPT_MAX_CHARS} 字")

    if errors:
        raise DefinitionInvalid(errors)
    return PromptDefinition(SCHEMA_VERSION, prompt.strip(), raw)


def parse_any_definition(kind: str, raw: dict):
    """按技能实现类型分派校验：code 无定义、declarative 走 DSL、prompt 走提示词。"""
    if kind == "prompt":
        return parse_prompt_definition(raw)
    if kind == "declarative":
        return parse_definition(raw)
    raise DefinitionInvalid([{"field": "kind", "reason": "该技能类型不接受定义"}])


def prompt_text(kind: str, raw: dict) -> str | None:
    if kind != "prompt" or not isinstance(raw, dict):
        return None
    value = raw.get("prompt")
    return value.strip() if isinstance(value, str) and value.strip() else None

