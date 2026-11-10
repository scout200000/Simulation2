"""Web 控制层与当前回应方案机制之间的兼容层。

历史背景：``app.application.session_facade`` /
``app.application.session_service`` / ``app.main.api_server`` 早期版本直接
引用了当时 ``experiment_runner`` 与 ``simulation.event_context`` 里的若干
辅助函数。上游在 2026/10 把机制改成"一个不回应基线 + 三个可自定义
回应方案"，这些辅助函数随之消失。

本模块只做**输入归一化**，不实现仿真、决策或指标逻辑：

* ``resolve_event_input``：默认事件与 web 输入的字段级合并；
* ``resolve_official_response_options``：默认方案与 web 覆盖的合并；
* ``list_triggerable_strategies``：给前端的可选方案清单；
* ``resolve_entry_timing``：进场时机输入校验；
* ``is_custom_statement_ready`` / ``CUSTOM_CONTENT_STRATEGY_ID``：沿用旧调用点。

前端兼容策略（2026-10-27）
--------------------------
现有前端把 ``custom`` 写死为默认选中项，并按 ``custom`` 做"公告是否填写"的
门控；同时它完全按后端返回的 ``content_strategies`` 生成编辑区和
``official_content_input``。因此这里把**第三个回应方案对外暴露为 ``custom``**：
前端不必修改即可工作，机制侧仍然是三个方案，只是第三个方案的编号叫 ``custom``。

真正的语义对齐（逐轮驱动、checkpoint、公告时间线）仍待后续适配。
"""

from __future__ import annotations

import hashlib

from app.application.experiment_runner import MAX_STEPS
from app.domain.events.context import validate_event_input
from app.infrastructure.database.repositories.events import load_event_input
from app.infrastructure.storage.json_storage import load_json
from strategies.registry import (
    NO_RESPONSE_SCENARIO,
    OFFICIAL_STATEMENT_STATUSES,
    RESPONSE_PLAN_COUNT,
    validate_official_response_options,
)


# 前端把 custom 写死为默认选中项，因此第四个方案沿用该编号。
CUSTOM_CONTENT_STRATEGY_ID = "custom"

# 方案公告留空时用于通过上游校验的占位正文；不会落盘。
PLACEHOLDER_STATEMENT = "（待填写）"

# 允许通过 web 覆盖的方案字段。
_OVERRIDABLE_STRATEGY_FIELDS = {
    "strategy_name",
    "official_statement",
    "official_statement_status",
    "evidence_dimensions",
}

_ENTRY_TIMING_MODES = ("dynamic", "fixed_round")


def _load_default_options(default_response_file):
    """读取默认方案文件，允许 ``custom`` 以空公告占位。

    上游的 ``load_official_response_options`` 要求每个方案都有非空正文，
    因此这里先按原始 JSON 读取，再由 ``_validate_allow_custom_placeholder``
    统一校验（空公告用占位正文替换后再走同一套规则）。
    """

    options = load_json(default_response_file)
    if not isinstance(options, dict):
        raise ValueError("官方内容策略文件必须是 JSON 对象。")
    if not isinstance(options.get("content_strategies"), list):
        raise ValueError("官方内容策略文件缺少 content_strategies 数组。")
    return options


def _expose_custom_plan(strategies):
    """确保对外清单里包含 ``custom`` 方案。

    当前数据文件已经直接包含 ``custom``；若遇到旧的三方案数据，则把最后一个
    ``response_plan_*`` 改名为 ``custom``，保持前端默认选中项可用。
    """

    items = [dict(item) for item in strategies]
    if len(items) != RESPONSE_PLAN_COUNT:
        raise ValueError(
            f"默认回应方案数量应为 {RESPONSE_PLAN_COUNT}，实际为 {len(items)}。"
        )
    if any(item["strategy_id"] == CUSTOM_CONTENT_STRATEGY_ID for item in items):
        return items

    last = items[-1]
    if not str(last.get("strategy_id", "")).startswith("response_plan_"):
        return items
    last["strategy_id"] = CUSTOM_CONTENT_STRATEGY_ID
    return items


def resolve_event_input(default_event_file, event_input=None):
    """合并默认事件 JSON 与 web 事件输入，并返回校验后的事件。

    未提供 ``event_input`` 时直接使用默认事件文件。web 输入按字典覆盖默认
    字段；``event_labels`` 做浅层合并，可以只传需要修改的标签。
    """

    defaults = validate_event_input(load_event_input(default_event_file))
    if event_input is None:
        return defaults
    if not isinstance(event_input, dict):
        raise ValueError("事件输入必须是 JSON 对象。")

    provided_event_id = str(event_input.get("event_id", "") or "").strip()
    if provided_event_id and provided_event_id != defaults.get("event_id"):
        if not str(event_input.get("event_content", "") or "").strip():
            raise ValueError("提供新的 event_id 时必须同时提供 event_content。")

    merged = dict(defaults)
    for key, value in event_input.items():
        if key == "event_labels":
            labels = dict(defaults.get("event_labels", {}) or {})
            if isinstance(value, dict):
                labels.update(value)
            merged[key] = labels
        else:
            merged[key] = value

    # 2026/11/04 新事件识别：前端只提交正文时，若正文与默认事件不同，
    # 不能继续沿用默认 event_id，否则知识图谱会把新事件当成旧事件而跳过。
    # 用正文哈希生成稳定 event_id：同一正文重复运行复用同一事件，改正文即新事件。
    content = str(merged.get("event_content") or "").strip()
    default_content = str(defaults.get("event_content") or "").strip()
    if not provided_event_id and content and content != default_content:
        digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:10]
        merged["event_id"] = f"event_custom_{digest}"
    return validate_event_input(merged)


def resolve_official_response_options(
    event_id,
    default_response_file,
    content_input=None,
):
    """合并默认回应方案与 web 覆盖，并复用上游的严格校验。

    对外暴露四个回应方案：``response_plan_1``、``response_plan_2``、
    ``response_plan_3`` 和 ``custom``。``content_input`` 以 ``strategy_id`` 为键，
    只允许覆盖方案名称、公告正文、公告状态和证据维度；未提供覆盖时直接返回
    默认方案。

    **公告填写规则**：任何方案留空都视为"未填写"，以空正文 + ``none`` 占位，
    该方案不参与运行，也不会被静默回填默认正文。默认公告只通过
    ``/api/input/defaults`` 提供给前端预填，用户清空后不再自动补回。
    """

    options = _load_default_options(default_response_file)
    strategies = _expose_custom_plan(options["content_strategies"])
    defaults_by_id = {item["strategy_id"]: dict(item) for item in strategies}
    merged = dict(options)
    merged["content_strategies"] = strategies
    if not content_input:
        _validate_allow_custom_placeholder(merged, defaults_by_id, event_id)
        return merged
    if not isinstance(content_input, dict):
        raise ValueError("official_content_input 必须是 JSON 对象。")

    by_id = {item["strategy_id"]: item for item in strategies}
    unknown = sorted(key for key in content_input if key not in by_id)
    if unknown:
        raise ValueError(
            f"未知的回应方案编号：{unknown}；当前可用：{sorted(by_id)}。"
        )

    for strategy_id, override in content_input.items():
        if not isinstance(override, dict):
            raise ValueError(f"回应方案 {strategy_id} 的覆盖内容必须是 JSON 对象。")
        unsupported = sorted(set(override) - _OVERRIDABLE_STRATEGY_FIELDS)
        if unsupported:
            raise ValueError(
                f"回应方案 {strategy_id} 包含不可覆盖的字段：{unsupported}。"
            )

        target = by_id[strategy_id]
        if "strategy_name" in override:
            name = str(override["strategy_name"] or "").strip()
            if name:
                target["strategy_name"] = name

        if "official_statement" in override:
            statement = str(override["official_statement"] or "").strip()
            if statement:
                target["official_statement"] = statement
                status = override.get(
                    "official_statement_status",
                    target["official_statement_status"],
                )
                if status in OFFICIAL_STATEMENT_STATUSES:
                    target["official_statement_status"] = status
            else:
                # 明确留空即视为"未填写"：以空正文 + none 占位，该方案不参与运行。
                # 不回填默认正文，避免"没有内容也会输出"。
                target["official_statement"] = ""
                target["official_statement_status"] = "none"

        if "evidence_dimensions" in override:
            dimensions = dict(target.get("evidence_dimensions") or {})
            if not isinstance(override["evidence_dimensions"], dict):
                raise ValueError(
                    f"回应方案 {strategy_id} 的 evidence_dimensions 必须是对象。"
                )
            dimensions.update(
                {
                    key: bool(value)
                    for key, value in override["evidence_dimensions"].items()
                }
            )
            target["evidence_dimensions"] = dimensions

    merged = dict(options)
    merged["content_strategies"] = strategies
    _validate_allow_custom_placeholder(merged, defaults_by_id, event_id)
    return merged


def _validate_allow_custom_placeholder(options, defaults_by_id, event_id):
    """按上游规则校验，但允许方案以空公告占位。

    上游要求每个回应方案都有非空正文。为了让"未填写"的方案可以不参与运行，
    这里在校验副本里用占位正文替换空值，再走同一套规则：事件编号、进场规则、
    证据维度、方案数量仍然严格执行。
    """

    validation = dict(options)
    validation["content_strategies"] = []
    for item in options["content_strategies"]:
        entry = dict(item)
        if not str(entry.get("official_statement", "") or "").strip():
            fallback = defaults_by_id.get(entry["strategy_id"], {})
            statement = str(
                fallback.get("official_statement", "") or ""
            ).strip()
            entry["official_statement"] = statement or PLACEHOLDER_STATEMENT
            status = fallback.get("official_statement_status")
            entry["official_statement_status"] = (
                status if status in OFFICIAL_STATEMENT_STATUSES else "incomplete"
            )
        validation["content_strategies"].append(entry)
    validate_official_response_options(validation, event_id)


def is_statement_ready(strategy):
    """判断某个回应方案是否已经填写可运行的公告。"""

    if not isinstance(strategy, dict):
        return False
    statement = str(strategy.get("official_statement", "") or "").strip()
    status = strategy.get("official_statement_status")
    return bool(statement) and status not in (None, "", "none")


def is_custom_statement_ready(strategy):
    """兼容旧调用：custom 方案的就绪判断与通用规则一致。"""

    return is_statement_ready(strategy)


def list_triggerable_strategies(official_options):
    """返回前端可选择的方案清单（含不回应基线）。"""

    items = [
        {
            "strategy_id": NO_RESPONSE_SCENARIO["strategy_id"],
            "strategy_name": NO_RESPONSE_SCENARIO["strategy_name"],
            "custom": False,
            "ready": True,
        }
    ]
    for strategy in official_options.get("content_strategies", []):
        items.append(
            {
                "strategy_id": strategy["strategy_id"],
                "strategy_name": strategy["strategy_name"],
                "custom": (
                    strategy["strategy_id"] == CUSTOM_CONTENT_STRATEGY_ID
                ),
                "ready": is_statement_ready(strategy),
            }
        )
    if len(items) != RESPONSE_PLAN_COUNT + 1:
        raise ValueError(
            "方案清单数量异常：期望 1 个不回应基线 + "
            f"{RESPONSE_PLAN_COUNT} 个回应方案。"
        )
    return items


def resolve_entry_timing(entry_timing_input=None):
    """校验进场时机输入。

    当前机制只区分"动态判定进场"和"固定轮次进场"两种模式。固定轮次必须落在
    1..MAX_STEPS 之间，否则会与逐轮运行上限冲突。
    """

    if not entry_timing_input:
        return {"mode": "dynamic", "round": None}
    if not isinstance(entry_timing_input, dict):
        raise ValueError("entry_timing_input 必须是 JSON 对象。")

    mode = str(entry_timing_input.get("mode") or "dynamic").strip()
    if mode not in _ENTRY_TIMING_MODES:
        raise ValueError(f"进场时机模式必须是以下之一：{_ENTRY_TIMING_MODES}")
    if mode == "dynamic":
        return {"mode": "dynamic", "round": None}

    round_no = entry_timing_input.get("round")
    if (
        isinstance(round_no, bool)
        or not isinstance(round_no, int)
        or not 1 <= round_no <= MAX_STEPS
    ):
        raise ValueError(
            f"fixed_round 模式的 round 必须是 1 到 {MAX_STEPS} 之间的整数。"
        )
    return {"mode": "fixed_round", "round": round_no}


__all__ = [
    "CUSTOM_CONTENT_STRATEGY_ID",
    "is_custom_statement_ready",
    "list_triggerable_strategies",
    "resolve_entry_timing",
    "resolve_event_input",
    "resolve_official_response_options",
]
