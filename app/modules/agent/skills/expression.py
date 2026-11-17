"""安全表达式求值：只允许引用、数值、括号与 + - * /。"""
from __future__ import annotations

import ast
import operator
from typing import Any

from app.modules.agent.skills.definition import REF_RE, expression_ast

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


class ExpressionError(ValueError):
    pass


def resolve_ref(ref: str, ctx: dict) -> Any:
    m = REF_RE.fullmatch(ref)
    if not m:
        raise ExpressionError("引用格式无效")
    name, attr = m.group(1), m.group(2)
    if name in ctx["steps"]:
        value = ctx["steps"][name]
    elif name in ctx["sources"]:
        value = ctx["sources"][name]
    elif name in ctx["params"]:
        value = ctx["params"][name]
    else:
        raise ExpressionError("引用了不存在的参数/数据源/步骤")
    if attr:
        if not isinstance(value, dict) or attr not in value:
            raise ExpressionError(f"引用 {ref} 没有字段 {attr}")
        return value[attr]
    return value


def evaluate(expr: str, ctx: dict) -> Any:
    try:
        tree, mapping = expression_ast(expr)
    except (SyntaxError, ValueError) as exc:
        raise ExpressionError(str(exc)) from exc
    values = {name: resolve_ref(ref, ctx) for name, ref in mapping.items()}
    return _eval_node(tree.body, values)


def _eval_node(node: ast.AST, values: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ExpressionError("表达式只允许数值常量")
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ExpressionError("未知引用")
        return values[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval_node(node.operand, values))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left = _eval_node(node.left, values)
        right = _eval_node(node.right, values)
        if left is None or right is None:
            return None
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (left, right)):
            raise ExpressionError("表达式只能对数值做运算")
        if isinstance(node.op, ast.Div) and right == 0:
            raise ExpressionError("除数为 0")
        return _OPS[type(node.op)](left, right)
    raise ExpressionError("表达式包含不允许的语法")
