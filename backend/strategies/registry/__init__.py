"""内容策略注册表：方案数量、声明状态、证据维度与文件校验。"""

from __future__ import annotations

from pathlib import Path

from app.infrastructure.storage.json_storage import load_json
from strategies.base import OfficialResponseOptions


# 2026/10/16，修改功能：实验固定比较用户自定义回应方案，但不限定方案
# 名称和内容类型；不回应基线由系统单独补充。
# 2026/10/28，修改功能：增加第四个"自定义"方案槽位（编号 custom）。
RESPONSE_PLAN_COUNT = 4
OFFICIAL_STATEMENT_STATUSES = (
    "clear",
    "incomplete",
    "conflict",
)
OFFICIAL_EVIDENCE_DIMENSIONS = {
    "verified_fact",
    "completed_action",
    "accountability",
    "empathy",
    "unresolved_process",
    "rumor_control",
}
# 2026/08/23 内容策略对照，修改功能：内容场景共用一个已有的动态进场规则。
ENTRY_STRATEGIES = (
    "negative_threshold",
    "global_worsening",
    "combined_policy",
)
# 2026/08/23 内容策略对照，新增功能：保留不发布官方声明的独立实验基线。
NO_RESPONSE_SCENARIO = {
    "strategy_id": "no_response",
    "strategy_name": "不回应",
    "official_statement": "",
    "official_statement_status": "none",
}


# 2026/08/23 内容策略对照，新增功能：严格校验人工维护的官方内容策略输入。
# 2026/08/27 第十二次联调修复，修改功能：校验连续未改善动态进场配置。
# 2026/10/16，修改功能：取消四种固定类型的编号约束，仅校验
# “三个唯一、完整、可执行的回应方案”，使新事件可直接替换方案。
def validate_official_response_options(options, event_id) -> OfficialResponseOptions:
    """校验事件编号、动态进场规则和内容策略字段。"""
    if not isinstance(options, dict):
        raise ValueError("官方内容策略文件必须是 JSON 对象。")
    if options.get("event_id") != event_id:
        raise ValueError("官方内容策略与当前事件的 event_id 不一致。")

    entry_strategy = options.get("entry_strategy")
    if entry_strategy not in ENTRY_STRATEGIES:
        raise ValueError(
            f"entry_strategy 必须是以下之一：{ENTRY_STRATEGIES}"
        )

    stagnation_rounds = options.get("stagnation_rounds", 0)
    if (
        isinstance(stagnation_rounds, bool)
        or not isinstance(stagnation_rounds, int)
        or stagnation_rounds < 0
    ):
        raise ValueError("stagnation_rounds 必须是非负整数。")
    improvement_tolerance = options.get(
        "negative_rate_improvement_tolerance",
        0.05,
    )
    if (
        isinstance(improvement_tolerance, bool)
        or not isinstance(improvement_tolerance, (int, float))
        or not 0 <= improvement_tolerance <= 1
    ):
        raise ValueError(
            "negative_rate_improvement_tolerance 必须是0到1之间的数值。"
        )

    raw_strategies = options.get("content_strategies")
    if (
        not isinstance(raw_strategies, list)
        or len(raw_strategies) != RESPONSE_PLAN_COUNT
    ):
        raise ValueError(
            "content_strategies 必须恰好包含 "
            f"{RESPONSE_PLAN_COUNT} 个回应方案。"
        )

    strategies = []
    strategy_ids = set()
    for index, item in enumerate(raw_strategies, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个内容策略必须是 JSON 对象。")

        strategy_id = str(item.get("strategy_id", "")).strip()
        strategy_name = str(item.get("strategy_name", "")).strip()
        statement = str(item.get("official_statement", "")).strip()
        statement_status = item.get("official_statement_status")
        raw_dimensions = item.get("evidence_dimensions", {})
        if (
            not strategy_id
            or Path(strategy_id).name != strategy_id
            or strategy_id in {".", ".."}
        ):
            raise ValueError(f"第 {index} 个内容策略的 strategy_id 不合法。")
        if strategy_id in strategy_ids:
            raise ValueError(f"发现重复的内容策略编号：{strategy_id}")
        if not strategy_name:
            raise ValueError(f"内容策略 {strategy_id} 缺少 strategy_name。")
        if not statement:
            raise ValueError(f"内容策略 {strategy_id} 的官方声明不能为空。")
        if statement_status not in OFFICIAL_STATEMENT_STATUSES:
            raise ValueError(
                f"内容策略 {strategy_id} 的 official_statement_status 不合法。"
            )
        if not isinstance(raw_dimensions, dict):
            raise ValueError(
                f"内容策略 {strategy_id} 的 evidence_dimensions 必须是对象。"
            )
        unknown_dimensions = set(raw_dimensions) - OFFICIAL_EVIDENCE_DIMENSIONS
        if unknown_dimensions or any(
            not isinstance(value, bool) for value in raw_dimensions.values()
        ):
            raise ValueError(
                f"内容策略 {strategy_id} 的 evidence_dimensions 不合法："
                f"{sorted(unknown_dimensions)}"
            )

        strategy_ids.add(strategy_id)
        strategies.append(
            {
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "official_statement": statement,
                "official_statement_status": statement_status,
                "evidence_dimensions": {
                    key: bool(raw_dimensions.get(key, False))
                    for key in sorted(OFFICIAL_EVIDENCE_DIMENSIONS)
                },
            }
        )

    return {
        "event_id": event_id,
        "entry_strategy": entry_strategy,
        "stagnation_rounds": stagnation_rounds,
        "negative_rate_improvement_tolerance": float(
            improvement_tolerance
        ),
        "content_strategies": strategies,
    }


# 2026/08/23 内容策略对照，新增功能：从外部 JSON 读取当前事件的人工官方声明。
def load_official_response_options(response_file, event_id):
    """读取并返回经过严格校验的官方内容策略。"""
    response_path = Path(response_file)
    if not response_path.is_file():
        raise FileNotFoundError(f"官方内容策略文件不存在：{response_path}")
    return validate_official_response_options(
        load_json(response_path),
        event_id,
    )


__all__ = [
    "ENTRY_STRATEGIES",
    "NO_RESPONSE_SCENARIO",
    "OFFICIAL_EVIDENCE_DIMENSIONS",
    "OFFICIAL_STATEMENT_STATUSES",
    "RESPONSE_PLAN_COUNT",
    "load_official_response_options",
    "validate_official_response_options",
]
