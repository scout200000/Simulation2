"""推演会话路由：创建、查询与逐轮控制。"""

from __future__ import annotations

from http import HTTPStatus

from app.api.schemas import SessionActionRequest, SessionCreateRequest
from app.application import session_facade


def list_sessions():
    """列出已有会话摘要。"""

    return {"sessions": session_facade.list_web_experiments()}, HTTPStatus.OK


def create_session(body: SessionCreateRequest | None = None):
    """创建会话，返回会话初始状态。"""

    body = body or {}
    payload = session_facade.create_web_experiment(
        web_event_input=body.get("web_event_input"),
        official_content_input=body.get("official_content_input"),
        entry_timing_input=body.get("entry_timing_input"),
        announcement_timeline_input=body.get("announcement_timeline_input"),
        announcement_drafts_input=body.get("announcement_drafts_input"),
        selected_strategy_id=body.get(
            "selected_strategy_id",
            "response_plan_1",
        ),
        # 2026/11/09 初始舆论池双来源：允许本次会话覆盖生成 / 采集的默认配置。
        opinion_pool_config=body.get("opinion_pool_config"),
    )
    return payload, HTTPStatus.CREATED


def delete_session(experiment_id: str):
    """删除实验批次及其报告产物。"""

    return session_facade.delete_web_experiment(experiment_id), HTTPStatus.OK


def get_session(experiment_id: str):
    """读取会话快照与状态。"""

    return session_facade.get_web_experiment_status(experiment_id), HTTPStatus.OK


def run_session_action(
    experiment_id: str,
    action: str,
    body: SessionActionRequest | None = None,
):
    """执行会话动作：启动、单步、连续运行、暂停、回滚、重启、公告。"""

    body = body or {}
    if action == "start":
        payload = session_facade.start_web_experiment(experiment_id)
    elif action == "step":
        payload = session_facade.step_web_experiment(experiment_id)
    elif action == "continue":
        payload = session_facade.continue_web_experiment(experiment_id)
    elif action == "pause":
        payload = session_facade.pause_web_experiment(experiment_id)
    elif action == "resume":
        payload = session_facade.resume_web_experiment(experiment_id)
    elif action == "rollback":
        payload = session_facade.rollback_web_experiment(
            experiment_id,
            steps=body.get("steps", 1),
        )
    elif action == "restart":
        payload = session_facade.restart_web_experiment(experiment_id)
    elif action == "run":
        payload = session_facade.run_all_web_experiment(experiment_id)
    elif action == "announcement":
        payload = session_facade.add_web_announcement(
            experiment_id,
            round_no=body.get("round"),
            official_statement=body.get("official_statement", ""),
            official_statement_status=body.get(
                "official_statement_status",
                "clear",
            ),
        )
    else:
        raise ValueError(f"不支持的动作：{action}")
    return payload, HTTPStatus.OK


__all__ = [
    "create_session",
    "delete_session",
    "get_session",
    "list_sessions",
    "run_session_action",
]
