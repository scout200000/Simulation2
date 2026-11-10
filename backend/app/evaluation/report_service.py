"""会话报告服务：把一次 Web 推演的产物转换成报告 JSON。

设计约定：
- 数据由后端生成并落盘到 ``REPORT_DIR/<experiment_id>.json``；
- 前端只按 ``/api/sessions/{id}/report`` 读取并渲染，不内置任何示例报告；
- 模型分析可选：没有 ``DEEPSEEK_API_KEY`` 时自动退化为规则摘要；
- 生成走后台线程，接口返回 generating / ready / failed 状态供前端轮询。
"""

from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime
from pathlib import Path

from app.evaluation.build_report_data import build
from app.infrastructure.database.repositories import load_event_input
from app.infrastructure.storage.json_storage import load_json
from app.main.config.settings import (
    DEEPSEEK_MODEL,
    EXPERIMENT_DIR,
    REPORT_DIR,
    get_deepseek_api_key,
)
from app.application.session_service import _experiment_dir

REPORT_SCHEMA_VERSION = 1

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _report_file(experiment_id: str) -> Path:
    return REPORT_DIR / f"{experiment_id}.json"


def _scenario_dirs(experiment_dir: Path) -> list[Path]:
    """返回包含 scenario_result.json 的场景目录（跳过基线与检查点）。"""

    directories = []
    for item in sorted(experiment_dir.iterdir()):
        if not item.is_dir():
            continue
        if item.name.startswith("_") or item.name.startswith("."):
            continue
        if (item / "scenario_result.json").is_file():
            directories.append(item)
    return directories


def _strategy_name(experiment_dir: Path, scenario_id: str) -> str:
    control_file = experiment_dir / "web_control.json"
    if control_file.is_file():
        control = load_json(control_file)
        strategy = control.get("strategy") or {}
        if (
            strategy.get("strategy_id") == scenario_id
            and strategy.get("strategy_name")
        ):
            return str(strategy["strategy_name"])
    result = load_json(experiment_dir / scenario_id / "scenario_result.json")
    return str(result.get("strategy_name") or scenario_id)


def _synthetic_result(experiment_dir: Path) -> dict:
    """把 Web 会话的场景目录适配成 build() 需要的 experiment_result 结构。"""

    strategy_results = []
    for directory in _scenario_dirs(experiment_dir):
        result = load_json(directory / "scenario_result.json")
        scenario_id = str(result.get("strategy") or directory.name)
        strategy_results.append(
            {
                "strategy": scenario_id,
                "strategy_name": _strategy_name(experiment_dir, directory.name),
                "effect_metrics": result.get("effect_metrics") or {},
                "rounds": result.get("rounds") or [],
            }
        )
    return {"strategy_results": strategy_results}


def _load_event(experiment_dir: Path) -> dict:
    for name in ("event_input.json", "event.json"):
        path = experiment_dir / name
        data = load_event_input(path, required=False)
        if data is not None:
            return data
    return {"event_content": "", "event_labels": {}}


def _agent_count(experiment_dir: Path, fallback: int = 30) -> int:
    for directory in _scenario_dirs(experiment_dir):
        result = load_json(directory / "scenario_result.json")
        metrics = result.get("final_metrics") or {}
        denominator = metrics.get("negative_denominator")
        if isinstance(denominator, int) and denominator > 0:
            return denominator
    return fallback


def _build_report(experiment_id: str) -> dict:
    experiment_dir = _experiment_dir(experiment_id)
    if not experiment_dir.is_dir():
        raise FileNotFoundError(f"会话不存在：{experiment_id}")

    result = _synthetic_result(experiment_dir)
    if not result["strategy_results"]:
        raise ValueError("该会话还没有可用的推演结果，无法生成报告")

    use_llm = bool(get_deepseek_api_key())
    report = build(
        experiment_id,
        use_llm=use_llm,
        experiment_dir=experiment_dir,
        experiment_result=result,
        event_input=_load_event(experiment_dir),
    )
    report["report_id"] = f"report_{experiment_id}"
    report["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    report["schema_version"] = REPORT_SCHEMA_VERSION
    report["simulation"]["agent_count"] = _agent_count(experiment_dir)
    report["simulation"]["model"] = (
        DEEPSEEK_MODEL if use_llm else f"{DEEPSEEK_MODEL}（规则模式）"
    )
    report["generation"] = {
        "mode": "llm" if use_llm else "rule",
        "generated_at": _now(),
        "source_experiment": experiment_id,
    }
    if not use_llm:
        report["subtitle"] = "规则评分与规则摘要（未启用模型分析）"
        report["conclusion"]["limitations"] = (
            "总分由规则计算（评论情绪 0.4 + 官方态度 0.6，公告投放轮次起逐轮平均）；"
            "当前未配置模型密钥，优势、风险与建议由规则生成，仅供内部讨论。"
        )
    return report


def _run_generation(experiment_id: str) -> None:
    try:
        report = _build_report(experiment_id)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        target = _report_file(experiment_id)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        with _LOCK:
            _JOBS[experiment_id] = {"status": "ready", "finished_at": _now()}
    except Exception as error:  # noqa: BLE001 - 状态通过接口返回给前端
        traceback.print_exc()
        with _LOCK:
            _JOBS[experiment_id] = {
                "status": "failed",
                "error": str(error),
                "finished_at": _now(),
            }


def get_report_status(experiment_id: str) -> dict:
    experiment_dir = _experiment_dir(experiment_id)
    if not experiment_dir.is_dir():
        raise FileNotFoundError(f"会话不存在：{experiment_id}")

    with _LOCK:
        job = dict(_JOBS.get(experiment_id) or {})

    target = _report_file(experiment_id)
    report = load_json(target) if target.is_file() else None

    if job.get("status") == "generating":
        return {
            "experiment_id": experiment_id,
            "status": "generating",
            "report": report,
            "error": None,
        }
    if report is not None:
        return {
            "experiment_id": experiment_id,
            "status": "ready",
            "report": report,
            "error": None,
        }
    if job.get("status") == "failed":
        return {
            "experiment_id": experiment_id,
            "status": "failed",
            "report": None,
            "error": job.get("error") or "报告生成失败",
        }
    return {
        "experiment_id": experiment_id,
        "status": "missing",
        "report": None,
        "error": None,
    }


def start_report_generation(experiment_id: str) -> dict:
    experiment_dir = _experiment_dir(experiment_id)
    if not experiment_dir.is_dir():
        raise FileNotFoundError(f"会话不存在：{experiment_id}")

    with _LOCK:
        current = _JOBS.get(experiment_id) or {}
        if current.get("status") == "generating":
            return get_report_status(experiment_id)
        _JOBS[experiment_id] = {"status": "generating", "started_at": _now()}

    thread = threading.Thread(
        target=_run_generation,
        args=(experiment_id,),
        name=f"report-{experiment_id}",
        daemon=True,
    )
    thread.start()
    return get_report_status(experiment_id)


def build_report_pdf(experiment_id: str) -> bytes:
    """把已生成的报告 JSON 渲染为 PDF 字节。

    只读取已落盘的报告；若尚未生成，由前端先调用生成接口。
    """

    experiment_dir = _experiment_dir(experiment_id)
    if not experiment_dir.is_dir():
        raise FileNotFoundError(f"会话不存在：{experiment_id}")

    report_file = _report_file(experiment_id)
    if not report_file.is_file():
        raise FileNotFoundError(
            "该会话还没有可下载的报告，请先在网页端生成报告。"
        )

    try:
        from app.evaluation.report_pdf import build_report_pdf as render_pdf
    except ImportError as error:  # pragma: no cover - 依赖缺失时给出明确提示
        raise RuntimeError(
            "PDF 组件未安装（缺少 reportlab），请先安装 requirements.txt。"
        ) from error

    return render_pdf(load_json(report_file))


__all__ = [
    "build_report_pdf",
    "get_report_status",
    "start_report_generation",
]
