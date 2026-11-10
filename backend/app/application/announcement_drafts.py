"""公告草稿批次的纯数据规范化。

前端把右侧「公告草稿」列表提交为 ``announcement_drafts_input``：每条草稿
绑定一个回应方案、一段公告正文和公告状态。本模块只做校验和场景构造，
不读写状态目录、不调用 LLM，也不参与实验编排。

语义约定：
- 每条草稿是一个独立回应场景，从同一份共享基线分叉；
- 草稿继承其绑定方案（``strategy_id``）的证据维度；
- 场景编号固定为 ``draft_1``、``draft_2``……，避免与内置方案目录冲突；
- 草稿正文为空或状态为 ``none`` 时不可运行。
"""

from __future__ import annotations

from strategies.registry import OFFICIAL_STATEMENT_STATUSES


MAX_ANNOUNCEMENT_DRAFTS = 20
DRAFT_STRATEGY_PREFIX = "draft_"


def _normalized_statement(value):
    """返回去掉首尾空白的公告正文。"""

    return str(value or "").strip()


def _index_content_strategies(official_options):
    """按 ``strategy_id`` 索引当前事件的回应方案。"""

    strategies = official_options.get("content_strategies", [])
    if not isinstance(strategies, list):
        raise ValueError("官方内容策略缺少 content_strategies 数组。")
    return {
        str(item.get("strategy_id")): item
        for item in strategies
        if isinstance(item, dict) and item.get("strategy_id")
    }


def normalize_announcement_drafts(raw_drafts, official_options):
    """校验前端提交的公告草稿，并补全其绑定方案的证据维度。

    参数：
        raw_drafts：``announcement_drafts_input`` 的原始值。
        official_options：当前事件的官方回应方案。

    返回：
        规范化后的草稿列表，每项包含 draft_id、strategy_id、方案名、
        公告正文、公告状态和证据维度。
    """

    if not isinstance(raw_drafts, list) or not raw_drafts:
        raise ValueError("公告草稿必须是非空数组。")
    if len(raw_drafts) > MAX_ANNOUNCEMENT_DRAFTS:
        raise ValueError(
            f"公告草稿最多支持 {MAX_ANNOUNCEMENT_DRAFTS} 条，"
            f"当前为 {len(raw_drafts)} 条。"
        )

    strategies_by_id = _index_content_strategies(official_options)
    if not strategies_by_id:
        raise ValueError("当前事件没有可用的回应方案。")

    normalized = []
    seen_draft_ids = set()
    for index, item in enumerate(raw_drafts, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条公告草稿必须是 JSON 对象。")

        strategy_id = str(item.get("strategy_id") or "").strip()
        if strategy_id not in strategies_by_id:
            raise ValueError(
                f"第 {index} 条公告草稿绑定了未知的回应方案：{strategy_id}"
            )

        statement = _normalized_statement(item.get("official_statement"))
        if not statement:
            raise ValueError(f"第 {index} 条公告草稿的公告正文不能为空。")

        status = item.get("official_statement_status")
        if status not in OFFICIAL_STATEMENT_STATUSES:
            raise ValueError(
                f"第 {index} 条公告草稿的状态必须是以下之一："
                f"{OFFICIAL_STATEMENT_STATUSES}"
            )

        draft_id = str(item.get("draft_id") or f"draft-{index}").strip()
        if not draft_id or draft_id in seen_draft_ids:
            raise ValueError(f"第 {index} 条公告草稿的 draft_id 缺失或重复。")
        seen_draft_ids.add(draft_id)

        base = strategies_by_id[strategy_id]
        normalized.append(
            {
                "draft_id": draft_id,
                "strategy_id": strategy_id,
                "strategy_name": str(
                    base.get("strategy_name") or strategy_id
                ),
                "official_statement": statement,
                "official_statement_status": status,
                "evidence_dimensions": dict(
                    base.get("evidence_dimensions") or {}
                ),
            }
        )

    return normalized


def build_draft_content_strategies(drafts):
    """把规范化草稿转换成 ``run_experiment`` 可执行的场景列表。"""

    scenarios = []
    for index, draft in enumerate(drafts, start=1):
        base_name = str(draft.get("strategy_name") or "").strip()
        strategy_name = f"{base_name} · 草稿{index}" if base_name else f"草稿{index}"
        scenarios.append(
            {
                "strategy_id": f"{DRAFT_STRATEGY_PREFIX}{index}",
                "strategy_name": strategy_name,
                "official_statement": draft["official_statement"],
                "official_statement_status": draft[
                    "official_statement_status"
                ],
                "evidence_dimensions": dict(
                    draft.get("evidence_dimensions") or {}
                ),
            }
        )
    return scenarios


def build_announcement_draft_snapshot(drafts):
    """生成写入批次目录的审计快照。"""

    return {
        "version": 1,
        "draft_count": len(drafts),
        "drafts": [
            {
                "draft_id": draft["draft_id"],
                "strategy_id": draft["strategy_id"],
                "strategy_name": draft["strategy_name"],
                "official_statement": draft["official_statement"],
                "official_statement_status": draft[
                    "official_statement_status"
                ],
                "evidence_dimensions": dict(
                    draft.get("evidence_dimensions") or {}
                ),
            }
            for draft in drafts
        ],
    }


__all__ = [
    "DRAFT_STRATEGY_PREFIX",
    "MAX_ANNOUNCEMENT_DRAFTS",
    "build_announcement_draft_snapshot",
    "build_draft_content_strategies",
    "normalize_announcement_drafts",
]
