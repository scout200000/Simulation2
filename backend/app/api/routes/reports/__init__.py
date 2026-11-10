"""会话报告路由：读取报告状态、触发生成与下载 PDF。"""

from __future__ import annotations

from http import HTTPStatus

from app.api.responses import FileResponse
from app.application import session_facade
from app.evaluation.report_service import build_report_pdf


def get_session_report(experiment_id: str):
    """读取报告状态：missing / generating / ready / failed。"""

    return (
        session_facade.get_session_report(experiment_id),
        HTTPStatus.OK,
    )


def generate_session_report(experiment_id: str):
    """触发后台报告生成，立即返回当前状态供前端轮询。"""

    return (
        session_facade.generate_session_report(experiment_id),
        HTTPStatus.ACCEPTED,
    )


def download_session_report_pdf(experiment_id: str):
    """把已生成的报告渲染为 PDF 并作为附件下载。"""

    return (
        FileResponse(
            content=build_report_pdf(experiment_id),
            media_type="application/pdf",
            filename=f"{experiment_id}-report.pdf",
        ),
        HTTPStatus.OK,
    )


__all__ = [
    "download_session_report_pdf",
    "generate_session_report",
    "get_session_report",
]
