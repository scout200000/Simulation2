"""会话控制服务：逐轮驱动仿真并维护回滚检查点。

控制器只按轮调用现有单轮执行器，在每个实验目录内维护控制文件
（沿用历史文件名 ``web_control.json``）和回滚快照；不重新实现评论生成、
Agent 决策或指标公式。
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from app.comments.opinion_pool import build_initial_comment_pool, resolve_config
from app.application.experiment_runner import (
    MAX_STEPS,
    calculate_strategy_effect_metrics,
    evaluate_response_entry,
    extract_policy_metrics,
    load_round_result,
    prepare_scenario_state,
    run_experiment,
    run_simulation_step,
    summarize_comment_quality,
    summarize_step_performance,
)
from app.infrastructure.llm.llm_service import get_llm_performance_stats
from app.infrastructure.storage.json_storage import load_json, read_jsonl, save_json
from app.infrastructure.database.repositories import (
    copy_state_documents,
    delete_directory_documents,
    delete_file_document,
    delete_state_documents,
    load_event_input,
    load_event_state_history,
    load_social_network,
    save_event_state_history,
)
from app.main.config.settings import (
    COMMENT_POOL_SIZE,
    COMMENT_PROFILE_FILE,
    EVENT_FILE,
    OFFICIAL_RESPONSE_FILE,
)
from app.application.batch_manager import prepare_simulation_batch
from app.domain.events.state import append_event_state_record
from app.application.announcement_drafts import (
    build_announcement_draft_snapshot,
    build_draft_content_strategies,
    normalize_announcement_drafts,
)
from app.application.input_compat import (
    is_statement_ready,
    resolve_entry_timing,
    resolve_event_input,
    resolve_official_response_options,
)
from strategies.registry import NO_RESPONSE_SCENARIO


CONTROL_FILE_NAME = "web_control.json"
CHECKPOINT_DIR_NAME = ".web_checkpoints"
ALL_STRATEGIES_ID = "__all__"
DRAFTS_MODE_ID = "__drafts__"
_LOCK = threading.RLock()


def resolve_announcement_timeline(announcement_timeline_input=None):
    """规范化任意轮次公告时间线。"""
    if announcement_timeline_input is None:
        return []
    if isinstance(announcement_timeline_input, dict) and isinstance(
        announcement_timeline_input.get("events"), list
    ):
        announcement_timeline_input = announcement_timeline_input["events"]
    if not isinstance(announcement_timeline_input, list):
        raise ValueError("announcement_timeline_input 必须是公告事件列表。")

    allowed_statuses = {"clear", "incomplete", "conflict", "none"}
    normalized = []
    seen_rounds = set()
    for index, item in enumerate(announcement_timeline_input, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个公告事件必须是 JSON 对象。")
        round_no = item.get("round")
        statement = str(item.get("official_statement", "")).strip()
        status = item.get("official_statement_status")
        if (
            isinstance(round_no, bool)
            or not isinstance(round_no, int)
            or not 2 <= round_no <= MAX_STEPS
        ):
            raise ValueError(
                f"公告轮次必须是 2 到 {MAX_STEPS} 之间的整数。"
            )
        if round_no in seen_rounds:
            raise ValueError(f"同一轮次不能发布多条公告：{round_no}")
        if not statement:
            raise ValueError(f"第 {round_no} 轮公告内容不能为空。")
        if status not in allowed_statuses or status == "none":
            raise ValueError(
                f"第 {round_no} 轮公告状态必须是 clear、incomplete 或 conflict。"
            )
        seen_rounds.add(round_no)
        normalized.append(
            {
                "round": round_no,
                "official_statement": statement,
                "official_statement_status": status,
            }
        )
    normalized.sort(key=lambda event: event["round"])
    return normalized


def _experiment_dir(experiment_id: str) -> Path:
    from app.main.config.settings import EXPERIMENT_DIR

    if (
        not experiment_id
        or Path(experiment_id).name != experiment_id
        or experiment_id in {".", ".."}
    ):
        raise ValueError("实验编号不合法")
    candidate = (EXPERIMENT_DIR / experiment_id).resolve()
    if EXPERIMENT_DIR.resolve() not in candidate.parents:
        raise ValueError("实验编号不合法")
    return candidate


def _control_file(experiment_dir: Path) -> Path:
    return experiment_dir / CONTROL_FILE_NAME


def _repair_control_paths(experiment_dir: Path, control: dict) -> bool:
    """把迁移后失效的绝对路径改回当前实验目录，避免读取旧路径报错。"""
    changed = False
    for key in ("event_file", "official_response_file"):
        raw = control.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        current = Path(raw)
        if current.exists():
            continue
        candidate = experiment_dir / current.name
        if candidate.exists():
            control[key] = str(candidate.resolve())
            changed = True
    raw_pool = control.get("comment_pool_file")
    candidate_pool = experiment_dir / "comment_pool.json"
    if isinstance(raw_pool, str) and raw_pool.strip():
        if not Path(raw_pool).exists() and candidate_pool != Path(raw_pool):
            control["comment_pool_file"] = str(candidate_pool.resolve())
            changed = True
    for key, relative in (
        ("baseline_state_dir", Path("_shared_baseline") / "state"),
        ("scenario_state_dir", Path("custom") / "state"),
    ):
        raw = control.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        current = Path(raw)
        if current.is_dir():
            continue
        candidate = experiment_dir / relative
        if candidate.is_dir():
            control[key] = str(candidate.resolve())
            changed = True
    return changed


def _load_control(experiment_dir: Path) -> dict:
    control = load_json(_control_file(experiment_dir))
    if not isinstance(control, dict):
        raise ValueError(f"控制文件损坏：{_control_file(experiment_dir)}")
    if _repair_control_paths(experiment_dir, control):
        _save_control(experiment_dir, control)
    return control


def _save_control(experiment_dir: Path, control: dict) -> None:
    save_json(_control_file(experiment_dir), control)


def _sync_event_graph_quietly(experiment_dir: Path, control: dict) -> None:
    """策略运行结束后把事件写入 Neo4j；失败不影响仿真主流程。"""

    if control.get("phase") != "completed":
        return
    if control.get("status") not in {"completed", "partial_failed"}:
        return
    try:
        from app.application.knowledge_graph_sync import sync_event_after_run

        result = sync_event_after_run(experiment_dir, control)
        control["knowledge_graph"] = {
            **result,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_control(experiment_dir, control)
        if result.get("status") in {"added", "stored_locally", "failed"}:
            print(f"[knowledge graph] {result}")
    except Exception as error:  # noqa: BLE001 - 图谱同步不应中断仿真
        print(f"[knowledge graph] 同步失败：{error}")


def _assert_inside_experiment(experiment_dir: Path, path: Path) -> Path:
    resolved = path.resolve()
    root = experiment_dir.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"路径超出实验目录：{resolved}")
    return resolved


def _checkpoint_dir(experiment_dir: Path) -> Path:
    return experiment_dir / CHECKPOINT_DIR_NAME


def _snapshot_state_dir(experiment_dir: Path, state_dir: Path, sequence: int) -> Path:
    state_dir = _assert_inside_experiment(experiment_dir, state_dir)
    if not state_dir.is_dir():
        raise FileNotFoundError(f"待快照状态目录不存在：{state_dir}")
    target = _checkpoint_dir(experiment_dir) / f"{sequence:04d}"
    if target.exists():
        # 失败重试或暂停后继续时可能复用同一序号，重建该步开始前的快照。
        target = _assert_inside_experiment(experiment_dir, target)
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(state_dir, target)
    copy_state_documents(state_dir, target)
    return target


def _prune_checkpoints(experiment_dir: Path, keep_sequence: int) -> None:
    """删除回滚后不再需要的检查点，避免后续同序号快照冲突。"""
    checkpoint_root = _checkpoint_dir(experiment_dir)
    if not checkpoint_root.is_dir():
        return
    for path in checkpoint_root.iterdir():
        if not path.is_dir() or not path.name.isdigit():
            continue
        sequence = int(path.name)
        if sequence <= keep_sequence:
            continue
        path = _assert_inside_experiment(experiment_dir, path)
        delete_state_documents(path)
        shutil.rmtree(path)


def _remove_scenario_dir(experiment_dir: Path, strategy_id: str) -> None:
    scenario_dir = _assert_inside_experiment(
        experiment_dir, experiment_dir / strategy_id
    )
    if scenario_dir.is_dir():
        delete_directory_documents(scenario_dir)
        shutil.rmtree(scenario_dir)


def _remove_experiment_file(experiment_dir: Path, file_path: Path) -> None:
    file_path = _assert_inside_experiment(experiment_dir, file_path)
    if file_path.is_file():
        delete_file_document(file_path)
        file_path.unlink()


def _replace_event_state(
    state_dir: Path,
    event_id: str,
    round_no: int,
    official_statement: str,
    official_statement_status: str,
) -> None:
    """替换指定轮次的事件状态，用于暂停时补发/修改公告。"""
    state_file = state_dir / "event_state_history.json"
    records = load_event_state_history(state_file, required=True)
    if not isinstance(records, list):
        raise ValueError("event_state_history.json 不是状态数组。")
    for record in records:
        if (
            isinstance(record, dict)
            and record.get("event_id") == event_id
            and record.get("step") == round_no
        ):
            record["official_statement"] = official_statement.strip()
            record["official_statement_status"] = official_statement_status
            save_event_state_history(state_file, records)
            return
    raise ValueError(f"状态目录中不存在第 {round_no} 轮事件状态。")


def _selected_strategy(official_options: dict, strategy_id: str) -> dict:
    if strategy_id == NO_RESPONSE_SCENARIO["strategy_id"]:
        return dict(NO_RESPONSE_SCENARIO)
    for item in official_options.get("content_strategies", []):
        if item["strategy_id"] == strategy_id:
            return dict(item)
    raise ValueError(f"不支持的策略编号：{strategy_id}")


def _history_rounds(control: dict) -> list:
    return [
        item["round"]
        for item in control.get("history", [])
        if isinstance(item.get("round"), dict)
    ]


def _history_quality(control: dict) -> list:
    return [
        item["comment_quality"]
        for item in control.get("history", [])
        if isinstance(item.get("comment_quality"), dict)
    ]


def _active_response(strategy: dict) -> dict:
    if strategy.get("strategy_id") == NO_RESPONSE_SCENARIO["strategy_id"]:
        return {
            "official_statement": "",
            "official_statement_status": "none",
        }
    return {
        "official_statement": strategy.get("official_statement", ""),
        "official_statement_status": strategy.get(
            "official_statement_status",
            "none",
        ),
    }


def _timeline_event_at(control: dict, round_no: int):
    for event in control.get("announcement_timeline", []) or []:
        if event.get("round") == round_no:
            return event
    return None


def _timeline_latest_at(control: dict, round_no: int):
    latest = None
    for event in control.get("announcement_timeline", []) or []:
        if event.get("round") <= round_no:
            latest = event
    return latest


def _no_statement():
    return {
        "official_statement": "",
        "official_statement_status": "none",
    }


def _active_for_round(control: dict, strategy: dict, round_no: int) -> dict:
    timeline = control.get("announcement_timeline", []) or []
    if timeline:
        event = _timeline_event_at(control, round_no)
        if event:
            return {
                "official_statement": event.get("official_statement", ""),
                "official_statement_status": event.get(
                    "official_statement_status",
                    "none",
                ),
            }
        latest = _timeline_latest_at(control, round_no)
        if latest:
            return {
                "official_statement": latest.get(
                    "official_statement",
                    "",
                ),
                "official_statement_status": latest.get(
                    "official_statement_status",
                    "none",
                ),
            }
        return _no_statement()

    timing = control.get("entry_timing") or {}
    if timing.get("mode") == "fixed_round":
        if round_no >= timing.get("round", MAX_STEPS + 1):
            return _active_response(strategy)
        return _no_statement()
    return _active_response(strategy)


def _baseline_entry_decision(control: dict, round_result: dict) -> dict:
    policy_metrics = round_result.get("policy_metrics", {})
    entry_decision = evaluate_response_entry(
        control["entry_strategy"],
        policy_metrics,
        response_count=0,
        round_results=_history_rounds(control),
        stagnation_rounds=control.get("stagnation_rounds", 0),
        improvement_tolerance=control.get(
            "negative_rate_improvement_tolerance",
            0.05,
        ),
    )
    return entry_decision


def _begin_scenario(experiment_dir: Path, control: dict, event_input: dict) -> None:
    event_id = event_input["event_id"]
    strategy_id = control["selected_strategy_id"]
    strategy = _selected_strategy(
        load_json(experiment_dir / "official_response_options.json"),
        strategy_id,
    )
    if (
        strategy_id != NO_RESPONSE_SCENARIO["strategy_id"]
        and not is_statement_ready(strategy)
    ):
        control["status"] = "not_run"
        control["phase"] = "completed"
        control["not_run_reason"] = "official_statement_empty"
        return

    _, scenario_state_dir = prepare_scenario_state(
        experiment_dir,
        strategy_id,
        event_id,
        baseline_state_dir=Path(control["baseline_state_dir"]),
    )
    append_event_state_record(
        event_input=event_input,
        official_statement=_active_response(strategy)["official_statement"],
        official_statement_status=_active_response(strategy)[
            "official_statement_status"
        ],
        state_file=scenario_state_dir / "event_state_history.json",
    )
    control["scenario_state_dir"] = str(scenario_state_dir)
    control["strategy"] = strategy
    control["phase"] = "scenario"
    control["current_step"] = control["response_step"]


def _start_direct_scenario(
    experiment_dir: Path,
    control: dict,
    event_input: dict,
) -> None:
    """不回应或固定时机模式：不跑基线，直接从第 1 轮运行所选策略。"""
    event_id = event_input["event_id"]
    strategy_id = control["selected_strategy_id"]
    strategy = _selected_strategy(
        load_json(experiment_dir / "official_response_options.json"),
        strategy_id,
    )
    if (
        strategy_id != NO_RESPONSE_SCENARIO["strategy_id"]
        and not is_statement_ready(strategy)
    ):
        control["status"] = "not_run"
        control["phase"] = "completed"
        control["not_run_reason"] = "official_statement_empty"
        return

    _, scenario_state_dir = prepare_scenario_state(
        experiment_dir,
        strategy_id,
        event_id,
    )
    control["scenario_state_dir"] = str(scenario_state_dir)
    control["strategy"] = strategy
    control["phase"] = "scenario"
    control["current_step"] = 1
    control["baseline_completed_step"] = 0
    if strategy_id == NO_RESPONSE_SCENARIO["strategy_id"]:
        control["response_step"] = None
        control["entry_reason"] = None
        return
    timeline = control.get("announcement_timeline", []) or []
    if timeline:
        control["response_step"] = timeline[0]["round"]
        control["entry_reason"] = "announcement_timeline"
    else:
        timing = control.get("entry_timing") or {}
        control["response_step"] = timing.get("round")
        control["entry_reason"] = "custom_entry_round"


def _finalize_scenario(experiment_dir: Path, control: dict) -> None:
    strategy = control["strategy"]
    strategy_id = strategy["strategy_id"]
    scenario_dir = experiment_dir / strategy_id
    state_dir = Path(control["scenario_state_dir"])
    response_step = control.get("response_step")
    rounds = _history_rounds(control)
    effect_metrics = calculate_strategy_effect_metrics(
        rounds,
        state_dir,
        response_step,
    )
    step_results = [
        item.get("performance")
        for item in control.get("history", [])
        if item.get("phase") == "scenario"
        and isinstance(item.get("performance"), dict)
    ]
    performance = summarize_step_performance(step_results)
    performance["duration_seconds"] = round(
        time.time() - control.get("started_at", time.time()),
        3,
    )
    official_responses = []
    timeline = control.get("announcement_timeline", []) or []
    if timeline:
        for event in timeline:
            official_responses.append(
                {
                    "step": event["round"],
                    "strategy_id": strategy_id,
                    "strategy_name": strategy.get("strategy_name"),
                    "official_statement": event.get(
                        "official_statement",
                        "",
                    ),
                    "official_statement_status": event.get(
                        "official_statement_status",
                        "clear",
                    ),
                }
            )
    elif strategy_id != NO_RESPONSE_SCENARIO["strategy_id"]:
        official_responses.append(
            {
                "step": response_step,
                "strategy_id": strategy_id,
                "strategy_name": strategy.get("strategy_name"),
                **_active_response(strategy),
            }
        )
    result = {
        "strategy": strategy_id,
        "strategy_name": strategy.get("strategy_name"),
        "entry_strategy": control["entry_strategy"],
        "status": "success",
        "entry_triggered": True,
        "entry_reason": control.get("entry_reason"),
        "entry_timing": control.get("entry_timing"),
        "announcement_timeline": control.get(
            "announcement_timeline",
            [],
        ),
        "comparison_eligible": True,
        "official_responses": official_responses,
        "rounds": rounds,
        "final_metrics": rounds[-1].get("policy_metrics", {}),
        "effect_metrics": effect_metrics,
        "comment_quality": summarize_comment_quality(
            _history_quality(control)
        ),
        "shared_baseline_completed_step": control.get(
            "baseline_completed_step"
        ),
        "state_dir": str(state_dir),
        "performance": performance,
    }
    scenario_dir.mkdir(parents=True, exist_ok=True)
    save_json(scenario_dir / "scenario_result.json", result)
    control["scenario_result"] = result
    control["status"] = "completed"
    control["phase"] = "completed"


def _append_history(
    control: dict,
    sequence: int,
    checkpoint_path: Path,
    phase: str,
    step: int,
    round_result: dict,
    step_performance: dict | None,
    comment_quality: dict | None,
) -> None:
    state_dir = (
        control["baseline_state_dir"]
        if phase == "baseline"
        else control["scenario_state_dir"]
    )
    control.setdefault("history", []).append(
        {
            "sequence": sequence,
            "phase": phase,
            "step": step,
            "checkpoint": str(checkpoint_path),
            "checkpoint_state_dir": str(state_dir),
            "round": round_result,
            "performance": step_performance,
            "comment_quality": comment_quality,
        }
    )
    control["last_completed_step"] = step


def _advance_baseline(
    experiment_dir: Path,
    control: dict,
    event_input: dict,
) -> dict:
    state_dir = Path(control["baseline_state_dir"])
    sequence = control.get("sequence", 0) + 1
    step = control["current_step"]
    checkpoint = _snapshot_state_dir(experiment_dir, state_dir, sequence)
    step_result = run_simulation_step(
        state_dir,
        Path(control["event_file"]),
        Path(control["comment_pool_file"]),
    )
    round_result, comment_quality = load_round_result(
        state_dir,
        event_input["event_id"],
        step,
    )
    _append_history(
        control,
        sequence,
        checkpoint,
        "baseline",
        step,
        round_result,
        step_result,
        comment_quality,
    )
    control["sequence"] = sequence
    control["paused"] = True

    if step >= MAX_STEPS:
        control["status"] = "completed_no_entry"
        control["phase"] = "completed"
        return control

    entry_timing = control.get("entry_timing") or {}
    if entry_timing.get("mode") == "fixed_round":
        if entry_timing.get("round") == step + 1:
            entry_decision = {
                "should_enter": True,
                "entry_reason": "custom_entry_round",
                "stagnant_round_count": 0,
            }
        else:
            entry_decision = {
                "should_enter": False,
                "entry_reason": None,
                "stagnant_round_count": 0,
            }
    else:
        entry_decision = _baseline_entry_decision(control, round_result)
    control["stagnant_round_count"] = entry_decision.get(
        "stagnant_round_count",
        0,
    )
    if entry_decision["should_enter"]:
        control["response_step"] = step + 1
        control["entry_reason"] = entry_decision["entry_reason"]
        control["baseline_completed_step"] = step
        control["status"] = "running"
        _begin_scenario(experiment_dir, control, event_input)
        return control

    append_event_state_record(
        event_input=event_input,
        official_statement="",
        official_statement_status="none",
        state_file=state_dir / "event_state_history.json",
    )
    control["current_step"] = step + 1
    control["status"] = "running"
    return control


def _advance_scenario(
    experiment_dir: Path,
    control: dict,
    event_input: dict,
) -> dict:
    state_dir = Path(control["scenario_state_dir"])
    sequence = control.get("sequence", 0) + 1
    step = control["current_step"]
    checkpoint = _snapshot_state_dir(experiment_dir, state_dir, sequence)
    step_result = run_simulation_step(
        state_dir,
        Path(control["event_file"]),
        Path(control["comment_pool_file"]),
    )
    round_result, comment_quality = load_round_result(
        state_dir,
        event_input["event_id"],
        step,
    )
    _append_history(
        control,
        sequence,
        checkpoint,
        "scenario",
        step,
        round_result,
        step_result,
        comment_quality,
    )
    control["sequence"] = sequence
    control["paused"] = True
    if step >= MAX_STEPS:
        _finalize_scenario(experiment_dir, control)
        return control
    active = _active_for_round(
        control,
        control["strategy"],
        step + 1,
    )
    append_event_state_record(
        event_input=event_input,
        official_statement=active["official_statement"],
        official_statement_status=active["official_statement_status"],
        state_file=state_dir / "event_state_history.json",
    )
    control["current_step"] = step + 1
    control["status"] = "running"
    return control


def _restore_checkpoint(experiment_dir: Path, checkpoint_path: Path, state_dir: Path) -> None:
    checkpoint = _assert_inside_experiment(experiment_dir, checkpoint_path)
    state_dir = _assert_inside_experiment(experiment_dir, state_dir)
    if not checkpoint.is_dir():
        raise FileNotFoundError(f"检查点不存在：{checkpoint}")
    if state_dir.is_dir():
        delete_state_documents(state_dir)
        shutil.rmtree(state_dir)
    state_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(checkpoint, state_dir)
    copy_state_documents(checkpoint, state_dir)


def _strategy_display_name(options, strategy_id):
    """把策略编号转换成可读名称。"""
    if strategy_id == "__drafts__":
        return "全部草稿"
    if strategy_id == "__all__":
        return "全部策略"
    if strategy_id == NO_RESPONSE_SCENARIO["strategy_id"]:
        return "不回应"
    for item in (options or {}).get("content_strategies", []) or []:
        if item.get("strategy_id") == strategy_id:
            return str(item.get("strategy_name") or strategy_id)
    return str(strategy_id or "自定义")


def _make_experiment_name(
    event_input,
    official_options,
    selected_strategy_id,
    mode="single",
    timestamp=None,
):
    """生成“事件主题 · 策略 · 创建时间”形式的实验名称。"""
    labels = (event_input or {}).get("event_labels") or {}
    topic = str(labels.get("topic") or "").strip()
    strategy = (
        "全部策略"
        if mode == "all"
        else _strategy_display_name(official_options, selected_strategy_id)
    )
    stamp = time.strftime(
        "%m-%d %H:%M",
        time.localtime(timestamp if timestamp is not None else time.time()),
    )
    return " · ".join(part for part in (topic, strategy, stamp) if part)


def _experiment_name_for_control(control):
    """优先读取已保存名称，旧会话按事件、策略和创建时间即时生成。"""
    name = control.get("experiment_name")
    if isinstance(name, str) and name.strip():
        return name
    event_input = {}
    event_file = control.get("event_file")
    if isinstance(event_file, str) and Path(event_file).is_file():
        try:
            event_input = load_json(Path(event_file)) or {}
        except Exception:
            event_input = {}
    options = {}
    try:
        options = load_json(control.get("official_response_file")) or {}
    except Exception:
        pass
    return _make_experiment_name(
        event_input,
        options,
        control.get("selected_strategy_id"),
        control.get("mode") or "single",
        control.get("created_at"),
    )


def _build_control(
    batch_context: dict,
    event_input: dict,
    official_options: dict,
    selected_strategy_id: str,
    mode: str = "single",
    entry_timing: dict | None = None,
    announcement_timeline: list | None = None,
    drafts: list | None = None,
    opinion_pool: dict | None = None,
) -> dict:
    resolved_timing = entry_timing or {"mode": "dynamic", "round": None}
    return {
        "experiment_id": batch_context["experiment_id"],
        "event_id": event_input["event_id"],
        "selected_strategy_id": selected_strategy_id,
        "mode": mode,
        "strategy_queue": [],
        "drafts": list(drafts or []),
        "entry_timing": resolved_timing,
        "announcement_timeline": announcement_timeline or [],
        # 2026/11/09 初始舆论池双来源：把本会话选定的来源与参数固化到 control。
        "opinion_pool": opinion_pool or {},
        "status": "created",
        "phase": "created",
        "paused": True,
        "entry_strategy": official_options["entry_strategy"],
        "stagnation_rounds": official_options["stagnation_rounds"],
        "negative_rate_improvement_tolerance": official_options[
            "negative_rate_improvement_tolerance"
        ],
        "event_file": str(batch_context["event_file"]),
        "comment_pool_file": str(batch_context["comment_pool_file"]),
        "official_response_file": str(
            batch_context["official_response_file"]
        ),
        "current_step": 1,
        "sequence": 0,
        "history": [],
        "checkpoints": [],
        "created_at": time.time(),
        "experiment_name": _make_experiment_name(
            event_input,
            official_options,
            selected_strategy_id,
            mode,
        ),
    }


def create_web_experiment(
    web_event_input=None,
    official_content_input=None,
    selected_strategy_id="response_plan_1",
    entry_timing_input=None,
    announcement_timeline_input=None,
    announcement_drafts_input=None,
    experiment_id=None,
    opinion_pool_config=None,
):
    """创建可供 web 逐步控制的实验会话。

    ``announcement_drafts_input`` 非空时创建公告草稿批次：每条草稿绑定
    一个回应方案，创建后由 ``run`` 动作依次运行全部草稿。
    """
    event_input = resolve_event_input(
        default_event_file=EVENT_FILE,
        event_input=web_event_input,
    )
    official_options = resolve_official_response_options(
        event_id=event_input["event_id"],
        default_response_file=OFFICIAL_RESPONSE_FILE,
        content_input=official_content_input,
    )

    drafts = None
    if announcement_drafts_input:
        if selected_strategy_id == ALL_STRATEGIES_ID:
            raise ValueError(
                "全部策略模式不能同时提交公告草稿，请只选择一种运行方式。"
            )
        drafts = normalize_announcement_drafts(
            announcement_drafts_input,
            official_options,
        )

    mode = (
        "drafts"
        if drafts
        else "all"
        if selected_strategy_id == ALL_STRATEGIES_ID
        else "single"
    )
    if mode == "single":
        _selected_strategy(official_options, selected_strategy_id)
    elif mode == "drafts":
        selected_strategy_id = DRAFTS_MODE_ID

    entry_timing = resolve_entry_timing(entry_timing_input)
    announcement_timeline = resolve_announcement_timeline(
        announcement_timeline_input
    )
    if mode in {"all", "drafts"} and announcement_timeline:
        raise ValueError("全部策略/全部草稿模式暂不支持公告时间线。")
    batch_context = prepare_simulation_batch(
        event_input,
        experiment_id=experiment_id,
        official_response_options=official_options,
    )
    experiment_dir = Path(batch_context["experiment_dir"])
    if drafts:
        save_json(
            experiment_dir / "announcement_drafts.json",
            build_announcement_draft_snapshot(drafts),
        )
    control = _build_control(
        batch_context,
        event_input,
        official_options,
        selected_strategy_id,
        mode=mode,
        entry_timing=entry_timing,
        announcement_timeline=announcement_timeline,
        drafts=drafts,
        opinion_pool=resolve_config(opinion_pool_config),
    )
    _save_control(experiment_dir, control)
    return get_web_experiment_status(control["experiment_id"])


def start_web_experiment(experiment_id):
    """准备初始评论池并进入对应策略的首轮运行状态。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    if control.get("phase") != "created":
        raise ValueError("实验会话已初始化，不能重复启动。")
    if control.get("mode") == "single":
        selected = _selected_strategy(
            load_json(control["official_response_file"]),
            control["selected_strategy_id"],
        )
        if (
            control["selected_strategy_id"]
            != NO_RESPONSE_SCENARIO["strategy_id"]
            and not is_statement_ready(selected)
        ):
            # 所选方案公告为空时直接标记未运行，避免先花时间生成评论池。
            control["status"] = "not_run"
            control["phase"] = "completed"
            control["paused"] = True
            control["not_run_reason"] = "official_statement_empty"
            _save_control(experiment_dir, control)
            return get_web_experiment_status(experiment_id)
    event_input = load_event_input(control["event_file"])
    comment_pool_file = Path(control["comment_pool_file"])
    if not comment_pool_file.is_file():
        print("正在为新实验会话生成初始评论池……")
        token_start = get_llm_performance_stats()
        comment_pool = build_initial_comment_pool(
            event_input,
            control.get("opinion_pool"),
            profile_file=COMMENT_PROFILE_FILE,
        )
        save_json(comment_pool_file, comment_pool)
        control["initial_token_usage"] = _token_usage_delta(
            token_start,
            get_llm_performance_stats(),
        )
    if control.get("mode") in {"all", "drafts"}:
        control["phase"] = "ready"
        control["status"] = "ready"
        control["paused"] = False
        control["started_at"] = time.time()
        _save_control(experiment_dir, control)
        return get_web_experiment_status(experiment_id)
    timing = control.get("entry_timing") or {}
    timeline = control.get("announcement_timeline", []) or []
    if (
        control.get("selected_strategy_id")
        == NO_RESPONSE_SCENARIO["strategy_id"]
        or timing.get("mode") == "fixed_round"
        or timeline
    ):
        _start_direct_scenario(experiment_dir, control, event_input)
        if control.get("status") == "not_run":
            _save_control(experiment_dir, control)
            return get_web_experiment_status(experiment_id)
        control["status"] = "running"
        control["paused"] = False
        control["started_at"] = time.time()
        _save_control(experiment_dir, control)
        return get_web_experiment_status(experiment_id)
    _, baseline_state_dir = prepare_scenario_state(
        experiment_dir,
        "_shared_baseline",
        event_input["event_id"],
    )
    control["baseline_state_dir"] = str(baseline_state_dir)
    control["phase"] = "baseline"
    control["current_step"] = 1
    control["status"] = "running"
    control["paused"] = False
    control["started_at"] = time.time()
    _save_control(experiment_dir, control)
    return get_web_experiment_status(experiment_id)


def _ensure_initial_comment_pool(control, event_input, mode_label):
    """批处理模式首次运行前生成一次初始评论池。"""

    comment_pool_file = Path(control["comment_pool_file"])
    if comment_pool_file.is_file():
        return
    print(f"正在为{mode_label}生成初始评论池……")
    token_start = get_llm_performance_stats()
    comment_pool = build_initial_comment_pool(
        event_input,
        control.get("opinion_pool"),
        profile_file=COMMENT_PROFILE_FILE,
    )
    save_json(comment_pool_file, comment_pool)
    control["initial_token_usage"] = _token_usage_delta(
        token_start,
        get_llm_performance_stats(),
    )


def _run_draft_batch(experiment_dir, control):
    """从同一份共享基线依次运行全部公告草稿场景。"""

    if control.get("phase") not in {"created", "ready", "completed"}:
        raise ValueError(
            f"当前会话状态不允许运行全部草稿：{control.get('phase')}"
        )

    drafts = control.get("drafts") or []
    if not drafts:
        snapshot_file = experiment_dir / "announcement_drafts.json"
        if snapshot_file.is_file():
            drafts = load_json(snapshot_file).get("drafts", [])
    if not isinstance(drafts, list) or not drafts:
        raise ValueError("当前会话没有可运行的公告草稿。")

    event_input = load_event_input(control["event_file"])
    scenarios = build_draft_content_strategies(drafts)
    _ensure_initial_comment_pool(control, event_input, "公告草稿批次")

    control["status"] = "running"
    control["phase"] = "drafts_running"
    control["paused"] = False
    _save_control(experiment_dir, control)

    try:
        result = run_experiment(
            experiment_id=control["experiment_id"],
            experiment_dir=experiment_dir,
            event_file=control["event_file"],
            comment_pool_file=control["comment_pool_file"],
            official_response_file=control["official_response_file"],
            content_strategies=scenarios,
        )
    except Exception:
        control["status"] = "failed"
        control["phase"] = "completed"
        control["paused"] = True
        _save_control(experiment_dir, control)
        _sync_event_graph_quietly(experiment_dir, control)
        raise
    control["status"] = result.get("status", "completed")
    control["phase"] = "completed"
    control["paused"] = False
    control["current_step"] = MAX_STEPS
    control["strategy_count"] = len(result.get("strategy_results", []))
    control["draft_count"] = len(drafts)
    _save_control(experiment_dir, control)
    _sync_event_graph_quietly(experiment_dir, control)
    return get_web_experiment_status(control["experiment_id"])


def run_all_web_experiment(experiment_id):
    """运行全部策略批次，或依次运行全部公告草稿。"""

    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    if control.get("mode") == "drafts":
        return _run_draft_batch(experiment_dir, control)
    if control.get("mode") != "all":
        raise ValueError("run 动作只适用于全部策略或全部草稿依次运行模式。")
    if control.get("phase") not in {"created", "ready", "completed"}:
        raise ValueError(f"当前会话状态不允许运行全部策略：{control.get('phase')}")

    event_input = load_event_input(control["event_file"])
    options = load_json(control["official_response_file"])
    empty_plans = [
        item["strategy_id"]
        for item in options.get("content_strategies", [])
        if not str(item.get("official_statement", "") or "").strip()
    ]
    if empty_plans:
        raise ValueError(
            f"以下回应方案的官方公告为空，无法运行全部策略：{empty_plans}。"
            " 请先填写公告，或改用单方案会话。"
        )
    _ensure_initial_comment_pool(control, event_input, "全部策略模式")

    control["status"] = "running"
    control["phase"] = "all_running"
    control["paused"] = False
    _save_control(experiment_dir, control)

    result = run_experiment(
        experiment_id=control["experiment_id"],
        experiment_dir=experiment_dir,
        event_file=control["event_file"],
        comment_pool_file=control["comment_pool_file"],
        official_response_file=control["official_response_file"],
    )
    control["status"] = result.get("status", "completed")
    control["phase"] = "completed"
    control["paused"] = False
    control["current_step"] = MAX_STEPS
    control["strategy_count"] = len(result.get("strategy_results", []))
    _save_control(experiment_dir, control)
    _sync_event_graph_quietly(experiment_dir, control)
    return get_web_experiment_status(experiment_id)


def step_web_experiment(experiment_id):
    """继续并执行一个时间步，执行后自动暂停在下一个轮次边界。"""
    with _LOCK:
        experiment_dir = _experiment_dir(experiment_id)
        control = _load_control(experiment_dir)
        if control.get("paused"):
            return get_web_experiment_status(experiment_id)
        if control.get("phase") not in {"baseline", "scenario"}:
            raise ValueError(
                f"当前会话状态不允许推进：{control.get('phase')}"
            )
        event_input = load_event_input(control["event_file"])
        if control["phase"] == "baseline":
            _advance_baseline(experiment_dir, control, event_input)
        else:
            _advance_scenario(experiment_dir, control, event_input)
        _save_control(experiment_dir, control)
        _sync_event_graph_quietly(experiment_dir, control)
        return get_web_experiment_status(experiment_id)


def continue_web_experiment(experiment_id):
    """清空暂停标记并执行一个时间步。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    control["paused"] = False
    _save_control(experiment_dir, control)
    return step_web_experiment(experiment_id)


def pause_web_experiment(experiment_id):
    """暂停当前会话；下一次推进前不会自动执行新轮次。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    control["paused"] = True
    _save_control(experiment_dir, control)
    return get_web_experiment_status(experiment_id)


def resume_web_experiment(experiment_id):
    """仅清除暂停标记，不自动执行新轮次。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    control["paused"] = False
    _save_control(experiment_dir, control)
    return get_web_experiment_status(experiment_id)


def rollback_web_experiment(experiment_id, steps=1):
    """回滚到最近完成步之前的检查点。"""
    with _LOCK:
        experiment_dir = _experiment_dir(experiment_id)
        control = _load_control(experiment_dir)
        history = control.get("history", [])
        if not history:
            return get_web_experiment_status(experiment_id)
        steps = max(1, int(steps))
        if steps > len(history):
            steps = len(history)
        target_index = len(history) - steps
        target_item = history[target_index]
        checkpoint = Path(target_item["checkpoint"])
        if control.get("phase") == "scenario" and target_item["phase"] == "baseline":
            _remove_scenario_dir(
                experiment_dir,
                control["selected_strategy_id"],
            )
        _restore_checkpoint(
            experiment_dir,
            checkpoint,
            Path(target_item["checkpoint_state_dir"]),
        )
        control["history"] = history[:target_index]
        control["sequence"] = target_index
        _prune_checkpoints(experiment_dir, target_index)
        control["phase"] = target_item["phase"]
        control["current_step"] = target_item["step"]
        control["paused"] = True
        if target_item["phase"] == "baseline":
            control["baseline_state_dir"] = str(
                Path(target_item["checkpoint_state_dir"])
            )
        else:
            control["scenario_state_dir"] = str(
                Path(target_item["checkpoint_state_dir"])
            )
        if target_item["phase"] == "baseline":
            control.pop("response_step", None)
            control.pop("scenario_state_dir", None)
            control.pop("strategy", None)
        control["status"] = "running"
        _remove_experiment_file(
            experiment_dir,
            experiment_dir
            / control["selected_strategy_id"]
            / "scenario_result.json",
        )
        _remove_experiment_file(
            experiment_dir,
            experiment_dir / "experiment_result.json",
        )
        _save_control(experiment_dir, control)
        return get_web_experiment_status(experiment_id)


def restart_web_experiment(experiment_id):
    """基于同一输入创建一个不可覆盖的新实验批次。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    event_input = load_event_input(control["event_file"])
    official_options = load_json(control["official_response_file"])
    new_batch = prepare_simulation_batch(
        event_input,
        official_response_options=official_options,
    )
    old_pool = Path(control["comment_pool_file"])
    if old_pool.is_file():
        shutil.copy2(old_pool, new_batch["comment_pool_file"])
    new_dir = Path(new_batch["experiment_dir"])
    drafts = control.get("drafts") or []
    if drafts:
        save_json(
            new_dir / "announcement_drafts.json",
            build_announcement_draft_snapshot(drafts),
        )
    new_control = _build_control(
        new_batch,
        event_input,
        official_options,
        control["selected_strategy_id"],
        mode=control.get("mode", "single"),
        entry_timing=control.get("entry_timing"),
        announcement_timeline=control.get("announcement_timeline", []),
        drafts=drafts,
    )
    _save_control(new_dir, new_control)
    return get_web_experiment_status(new_batch["experiment_id"])


def _active_state_dir(control: dict) -> Path:
    value = control.get("scenario_state_dir") or control.get(
        "baseline_state_dir"
    )
    return Path(value) if value else None


def _comment_distribution(comments):
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for comment in comments:
        emotion = comment.get("emotion")
        if emotion in counts:
            counts[emotion] += 1
    classified = sum(counts.values())
    return {
        "comment_count": len(comments),
        "classified_count": classified,
        "distribution": {
            label: {
                "count": count,
                "rate": round(count / classified, 4) if classified else None,
            }
            for label, count in counts.items()
        },
    }


def _load_agent_snapshot(state_dir: Path | None, event_id: str, step):
    if state_dir is None or step is None:
        return []
    records = {}
    comment_history = {}
    seen_comments = {}
    for row in read_jsonl(state_dir / "agent_state_history.jsonl"):
        if row.get("event_id") != event_id:
            continue
        agent_id = row.get("agent_id")
        if not agent_id:
            continue
        state = row.get("state", {}) or {}
        last_comment = state.get("last_comment") or {}
        if isinstance(last_comment, dict) and last_comment.get("text"):
            comment_id = last_comment.get("comment_id")
            seen = seen_comments.setdefault(agent_id, set())
            key = comment_id or last_comment.get("text")
            if key not in seen:
                seen.add(key)
                comment_history.setdefault(agent_id, []).append(
                    {
                        "step": last_comment.get("introduced_step")
                        or row.get("step"),
                        "comment_id": comment_id,
                        "text": last_comment.get("text", ""),
                        "emotion": last_comment.get("emotion"),
                        "faction": last_comment.get("faction"),
                        "orientation": last_comment.get("orientation"),
                        "stance": last_comment.get("stance"),
                        "action": state.get("last_action"),
                    }
                )
        if row.get("step") == step:
            records[agent_id] = row

    agents = []
    for agent_id in sorted(records):
        row = records[agent_id]
        state = row.get("state", {}) or {}
        last_comment = state.get("last_comment") or {}
        comments = comment_history.get(agent_id, [])
        comments.sort(key=lambda item: item.get("step") or 0)
        agents.append(
            {
                "agent_id": agent_id,
                "current_emotion": state.get("current_emotion"),
                "official_attitude": state.get("official_attitude"),
                "will_comment": state.get("will_comment"),
                "last_action": state.get("last_action"),
                "last_comment_faction": state.get("last_comment_faction"),
                "last_comment": last_comment.get("text", ""),
                "comment_emotion": last_comment.get("emotion"),
                "comment_orientation": last_comment.get("orientation"),
                "comments": comments,
                "comment_count": len(comments),
            }
        )
    return agents


def add_web_announcement(
    experiment_id,
    round_no,
    official_statement,
    official_statement_status="clear",
):
    """在暂停状态下向指定轮次追加或替换一条公告。"""
    with _LOCK:
        experiment_dir = _experiment_dir(experiment_id)
        control = _load_control(experiment_dir)
        if not control.get("paused"):
            raise ValueError("只能在暂停状态下添加公告。")
        if control.get("phase") not in {"baseline", "scenario"}:
            raise ValueError("当前会话阶段不允许添加公告。")

        event = resolve_announcement_timeline(
            [
                {
                    "round": round_no,
                    "official_statement": official_statement,
                    "official_statement_status": official_statement_status,
                }
            ]
        )[0]
        current_step = int(control.get("current_step", 1))
        if event["round"] < current_step:
            raise ValueError("不能修改已经运行完成的轮次。")
        if control.get("selected_strategy_id") == NO_RESPONSE_SCENARIO[
            "strategy_id"
        ]:
            raise ValueError("不回应策略不能添加公告。")

        timeline = list(control.get("announcement_timeline", []) or [])
        timeline = [
            item
            for item in timeline
            if item.get("round") != event["round"]
        ]
        timeline.append(event)
        timeline.sort(key=lambda item: item["round"])
        control["announcement_timeline"] = timeline

        if control.get("phase") == "scenario":
            if event["round"] == current_step:
                _replace_event_state(
                    Path(control["scenario_state_dir"]),
                    control["event_id"],
                    current_step,
                    event["official_statement"],
                    event["official_statement_status"],
                )
        else:
            if event["round"] == current_step:
                event_input = load_event_input(control["event_file"])
                strategy_id = control["selected_strategy_id"]
                strategy = _selected_strategy(
                    load_json(experiment_dir / "official_response_options.json"),
                    strategy_id,
                )
                _, scenario_state_dir = prepare_scenario_state(
                    experiment_dir,
                    strategy_id,
                    event_input["event_id"],
                    baseline_state_dir=Path(control["baseline_state_dir"]),
                )
                _replace_event_state(
                    scenario_state_dir,
                    event_input["event_id"],
                    current_step,
                    event["official_statement"],
                    event["official_statement_status"],
                )
                control["scenario_state_dir"] = str(scenario_state_dir)
                control["strategy"] = strategy
                control["phase"] = "scenario"
                control["response_step"] = current_step
                control["entry_reason"] = "manual_announcement"
                control["status"] = "running"
            else:
                control["entry_timing"] = {
                    "mode": "fixed_round",
                    "round": event["round"],
                }

        _save_control(experiment_dir, control)
        return get_web_experiment_status(experiment_id)


def _load_network_view(state_dir: Path | None) -> dict:
    """读取固定社交网络快照，供前端绘制真实关注关系。"""

    empty = {
        "nodes": [],
        "edges": [],
        "visibility": {},
        "decay_factor": None,
        "neighbors_per_agent": None,
        "network_version": None,
        "influence_weight_range": None,
    }
    if state_dir is None:
        return empty
    path = state_dir / "social_network_snapshot.json"
    data = load_social_network(path, required=False) or {}
    if not data:
        return empty

    nodes = [
        {
            "agent_id": node.get("agent_id"),
            "influence_weight": node.get("influence_weight"),
            "normalized_influence_weight": node.get(
                "normalized_influence_weight"
            ),
        }
        for node in (data.get("nodes") or [])
        if isinstance(node, dict) and node.get("agent_id")
    ]
    weight_by_agent = {
        node["agent_id"]: node for node in nodes
    }
    edges = []
    for edge in data.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source_agent_id")
        target = edge.get("target_agent_id")
        if not source or not target:
            continue
        source_node = weight_by_agent.get(source, {})
        edges.append(
            {
                "source": source,
                "target": target,
                # 传播权重跟随来源 Agent：来源影响力越大，这条关注关系越重。
                "weight": source_node.get("influence_weight"),
                "normalized_weight": source_node.get(
                    "normalized_influence_weight"
                ),
            }
        )
    return {
        "nodes": nodes,
        "edges": edges,
        "visibility": data.get("visibility") or {},
        "decay_factor": data.get("propagation_decay_factor"),
        "neighbors_per_agent": data.get("neighbors_per_agent"),
        "influence_weight_range": data.get("influence_weight_range"),
        "network_version": data.get("network_version"),
    }


def _load_propagation_events(
    state_dir: Path | None,
    event_id,
    limit: int = 300,
) -> list:
    """读取邻居曝光事件，按轮次截取最近 ``limit`` 条。"""

    if state_dir is None:
        return []
    path = state_dir / "propagation_history.jsonl"
    if not path.is_file():
        return []

    rows = [
        row
        for row in read_jsonl(path)
        if isinstance(row, dict) and row.get("event_id") == event_id
    ]
    rows.sort(key=lambda item: (item.get("step") or 0))
    return [
        {
            "propagation_event_id": row.get("propagation_event_id"),
            "step": row.get("step"),
            "event_type": row.get("event_type"),
            "comment_id": row.get("comment_id"),
            "source_agent_id": row.get("source_agent_id"),
            "target_agent_id": row.get("target_agent_id"),
            "propagation_depth": row.get("propagation_depth"),
            "influence_weight": row.get("influence_weight"),
            "effective_weight": row.get("effective_weight"),
            "decay_factor": row.get("decay_factor"),
            "was_selected": row.get("was_selected"),
        }
        for row in rows[-limit:]
    ]


def _build_round_snapshot(experiment_dir: Path, control: dict) -> dict:
    """读取已完成轮次指标与当前评论池，返回 web 实时展示快照。"""
    event_id = control.get("event_id")
    initial_comments = []
    comment_pool_file = Path(control["comment_pool_file"])
    if comment_pool_file.is_file():
        pool = load_json(comment_pool_file) or {}
        initial_comments = pool.get("comments", []) or []

    state_dir = _active_state_dir(control)
    metrics_history = []
    comment_rows = []
    if state_dir is not None and state_dir.is_dir():
        for row in read_jsonl(state_dir / "metrics_history.jsonl"):
            if isinstance(row, dict) and row.get("event_id") == event_id:
                metrics_history.append(row)
        for row in read_jsonl(
            state_dir / "incremental_comment_history.jsonl"
        ):
            if isinstance(row, dict) and row.get("event_id") == event_id:
                comment_rows.append(row)

    metrics_history.sort(key=lambda item: item.get("step", 0))
    comment_rows.sort(key=lambda item: item.get("step", 0))
    simplified_metrics = []
    for row in metrics_history:
        try:
            policy = extract_policy_metrics(row)
        except Exception:
            policy = {}
        simplified_metrics.append(
            {
                "step": row.get("step"),
                "policy_metrics": policy,
                "global_trend": row.get("global_trend", {}).get(
                    "trend_direction"
                ),
                "global_trend_reason": row.get("global_trend", {}).get(
                    "reason",
                    "",
                ),
                "agent_emotion_distribution": row.get(
                    "agent_emotion_distribution",
                    {},
                ),
                "official_attitude_distribution": row.get(
                    "official_attitude_distribution",
                    {},
                ),
                "propagation_metrics": row.get("propagation_metrics", {}),
            }
        )

    incremental_by_step = {
        row.get("step"): row for row in comment_rows
    }
    comment_history = []
    all_steps = sorted(
        {
            item.get("step")
            for item in simplified_metrics
            if item.get("step") is not None
        }
        | {row.get("step") for row in comment_rows if row.get("step") is not None}
    )
    if all_steps and all_steps[0] == 1:
        distribution = _comment_distribution(initial_comments)
        comment_history.append(
            {
                "step": 1,
                "source": "initial_pool",
                **distribution,
                "quality_status": "normal",
            }
        )
    for step in all_steps:
        if step == 1:
            continue
        record = incremental_by_step.get(step)
        comments = record.get("comments", []) if isinstance(record, dict) else []
        comment_history.append(
            {
                "step": step,
                "source": "incremental",
                **_comment_distribution(comments),
                "quality_status": (
                    record.get("quality_status", "normal")
                    if isinstance(record, dict)
                    else "unknown"
                ),
                "fallback_count": (
                    record.get("fallback_count", 0)
                    if isinstance(record, dict)
                    else 0
                ),
                "llm_comment_count": (
                    record.get("llm_comment_count", 0)
                    if isinstance(record, dict)
                    else 0
                ),
            }
        )

    latest_step = max(all_steps) if all_steps else None
    latest_comments = []
    if latest_step == 1:
        latest_comments = initial_comments
    elif latest_step in incremental_by_step:
        latest_comments = (
            incremental_by_step[latest_step].get("comments", []) or []
        )
    comments_by_step = {}
    for step in all_steps:
        if step == 1:
            step_comments = initial_comments
        else:
            record = incremental_by_step.get(step)
            step_comments = (
                record.get("comments", [])
                if isinstance(record, dict)
                else []
            )
        comments_by_step[str(step)] = [
            {
                "comment_id": item.get("comment_id"),
                "text": item.get("text", ""),
                "emotion": item.get("emotion"),
                "faction": item.get("faction"),
                "orientation": item.get("orientation"),
                "stance": item.get("stance"),
            }
            for item in step_comments
        ][:80]
    visible_comments = comments_by_step.get(str(latest_step), []) if latest_step else []
    network_view = _load_network_view(state_dir)
    propagation_events = _load_propagation_events(state_dir, event_id)
    propagation_summary = {}
    if metrics_history:
        propagation_summary = (
            metrics_history[-1].get("propagation_metrics", {}) or {}
        )
    return {
        "latest_step": latest_step,
        "initial_comment_count": len(initial_comments),
        "comment_pool": _comment_distribution(initial_comments),
        "agents": _load_agent_snapshot(state_dir, event_id, latest_step),
        "metrics_history": simplified_metrics,
        "comment_history": comment_history,
        "comments_by_step": comments_by_step,
        "latest_comments": visible_comments,
        "network": network_view,
        "propagation": {
            "summary": propagation_summary,
            "events": propagation_events,
        },
    }


TOKEN_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
)


def _empty_token_usage():
    """返回一份空的 token 统计。"""
    return {
        **{name: 0 for name in TOKEN_USAGE_KEYS},
        "request_count": 0,
    }


def _token_usage_from_llm_stats(stats):
    """把 llm_requests 统计中的 token 字段提取成会话级汇总。"""
    usage = _empty_token_usage()
    if not isinstance(stats, dict):
        return usage
    for name in TOKEN_USAGE_KEYS:
        value = stats.get(name, 0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            usage[name] += int(value)
    value = stats.get("logical_request_count", 0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        usage["request_count"] += int(value)
    return usage


def _performance_token_usage(performance):
    """从 performance 结构中读取 token 汇总。"""
    if not isinstance(performance, dict):
        return _empty_token_usage()
    return _token_usage_from_llm_stats(performance.get("llm_requests"))


def _history_token_usage(control):
    """汇总 web_control.history 中每一轮已记录的 token 用量。"""
    total = _empty_token_usage()
    history = control.get("history", []) if isinstance(control, dict) else []
    if not isinstance(history, list):
        return total
    for item in history:
        if not isinstance(item, dict):
            continue
        usage = _performance_token_usage(item.get("performance"))
        for name in total:
            total[name] += usage[name]
    return total


def _token_usage_delta(before, after):
    """计算一次操作前后进程级 LLM 统计的 token 差值。"""
    usage = _empty_token_usage()
    if not isinstance(before, dict) or not isinstance(after, dict):
        return usage
    for name in TOKEN_USAGE_KEYS:
        value = after.get(name, 0) - before.get(name, 0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            usage[name] = max(int(value), 0)
    value = after.get("logical_request_count", 0) - before.get(
        "logical_request_count", 0
    )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        usage["logical_request_count"] = max(int(value), 0)
    return usage


def _build_token_usage(control, scenario_result, experiment_result):
    """按会话状态选择最完整的 token 统计来源。"""
    scenario_usage = _performance_token_usage(
        (scenario_result or {}).get("performance")
        if isinstance(scenario_result, dict)
        else None
    )
    experiment_usage = _performance_token_usage(
        (experiment_result or {}).get("performance")
        if isinstance(experiment_result, dict)
        else None
    )
    history_usage = _history_token_usage(control)

    if experiment_usage["total_tokens"] or experiment_usage["request_count"]:
        chosen = experiment_usage
    elif scenario_usage["total_tokens"]:
        chosen = scenario_usage
    elif history_usage["total_tokens"]:
        chosen = history_usage
    elif scenario_usage["request_count"]:
        chosen = scenario_usage
    else:
        chosen = history_usage

    initial = control.get("initial_token_usage") if isinstance(control, dict) else {}
    initial_usage = _token_usage_from_llm_stats(initial)
    for name in chosen:
        chosen[name] += initial_usage.get(name, 0)
    return chosen


def get_web_experiment_status(experiment_id):
    """返回 web 展示所需的会话状态。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    scenario_result = None
    experiment_result = None
    if control.get("mode") in {"all", "drafts"}:
        result_file = experiment_dir / "experiment_result.json"
        if result_file.is_file():
            experiment_result = load_json(result_file)
    else:
        result_file = (
            experiment_dir
            / control.get("selected_strategy_id", "")
            / "scenario_result.json"
        )
        if result_file.is_file():
            scenario_result = load_json(result_file)
    snapshot = _build_round_snapshot(experiment_dir, control)
    drafts = control.get("drafts") or []
    return {
        "experiment_id": control["experiment_id"],
        "experiment_name": _experiment_name_for_control(control),
        "event_id": control.get("event_id"),
        "selected_strategy_id": control.get("selected_strategy_id"),
        "mode": control.get("mode"),
        "strategy_count": control.get("strategy_count"),
        "drafts": drafts,
        "draft_count": len(drafts),
        "status": control.get("status"),
        "phase": control.get("phase"),
        "paused": control.get("paused"),
        "current_step": control.get("current_step"),
        "response_step": control.get("response_step"),
        "entry_reason": control.get("entry_reason"),
        "entry_timing": control.get("entry_timing"),
        "announcement_timeline": control.get(
            "announcement_timeline",
            [],
        ),
        "not_run_reason": control.get("not_run_reason"),
        "knowledge_graph": control.get("knowledge_graph"),
        "completed_step_count": len(control.get("history", [])),
        "created_at": control.get("created_at"),
        "started_at": control.get("started_at"),
        "updated_at": control.get("updated_at"),
        "max_steps": MAX_STEPS,
        "scenario_result_ready": scenario_result is not None,
        "scenario_result": scenario_result,
        "experiment_result_ready": experiment_result is not None,
        "experiment_result": experiment_result,
        "snapshot": snapshot,
        "token_usage": _build_token_usage(
            control,
            scenario_result,
            experiment_result,
        ),
    }


def delete_web_experiment(experiment_id):
    """删除实验批次目录及已生成的报告。"""
    experiment_dir = _experiment_dir(experiment_id)
    if not experiment_dir.is_dir():
        raise FileNotFoundError(f"实验批次不存在：{experiment_id}")
    control = _load_control(experiment_dir)
    if (
        control.get("status") in {"running", "all_running"}
        and not control.get("paused")
    ):
        raise ValueError("运行中的实验批次不能删除，请先暂停。")
    shutil.rmtree(experiment_dir)
    try:
        from app.main.config.settings import REPORT_DIR

        report_file = REPORT_DIR / f"{experiment_id}.json"
        if report_file.is_file():
            report_file.unlink()
    except Exception:
        pass
    return {"experiment_id": experiment_id, "deleted": True}


def list_web_experiments():
    """列出带 web 控制文件的实验会话。"""
    from app.main.config.settings import EXPERIMENT_DIR

    sessions = []
    if not EXPERIMENT_DIR.is_dir():
        return sessions
    for experiment_dir in sorted(EXPERIMENT_DIR.iterdir()):
        if not experiment_dir.is_dir():
            continue
        if not _control_file(experiment_dir).is_file():
            continue
        try:
            sessions.append(get_web_experiment_status(experiment_dir.name))
        except Exception:
            continue

    def sort_key(item):
        created = item.get("created_at")
        if not isinstance(created, (int, float)) or isinstance(created, bool):
            created = 0
        return (created, str(item.get("experiment_id") or ""))

    sessions.sort(key=sort_key, reverse=True)
    return sessions


if __name__ == "__main__":
    print("Web control API module loaded.")
