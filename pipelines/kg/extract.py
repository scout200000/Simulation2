# -*- coding: utf-8 -*-
"""从 var/experiments 里已有的实验事件中抽取事件图谱要素。

两条路径：
1. heuristic：规则抽取，完全离线，作为没有大模型 Key 时的基线；
2. llm：把同一份材料交给大模型，按 ontology.SYSTEM_PROMPT 的 JSON 协议抽取。

两条路径输出同一份结构，后面的建图、导入、可视化完全复用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipelines.kg.llm import LLMConfig, chat_json
from pipelines.kg.ontology import SYSTEM_PROMPT, build_user_prompt, validate_extraction

# ---------------------------------------------------------------------------
# 事件材料发现
# ---------------------------------------------------------------------------


@dataclass
class Bundle:
    """一个事件的输入材料集合。"""

    event_id: str
    directory: Path
    event_input: dict[str, Any]
    public_context: dict[str, Any] | None = None
    official: dict[str, Any] | None = None
    comments: dict[str, Any] | None = None
    initial_opinion: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    metrics: list[dict[str, Any]] = field(default_factory=list)
    run_dir: Path | None = None
    origin: str = "historical_replay"

    @property
    def content(self) -> str:
        return str(self.event_input.get("event_content", "")).strip()

    @property
    def labels(self) -> dict[str, Any]:
        return self.event_input.get("event_labels") or {}


_BUNDLE_FILES = {
    "public_context": "public_context_timeline.json",
    "official": "official_response_timeline.json",
    "comments": "comment_pool.json",
    "initial_opinion": "initial_opinion.json",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_metrics(directory: Path) -> list[dict[str, Any]]:
    candidates = [
        directory / "historical_replay" / "state" / "metrics_history.jsonl",
        directory / "state" / "metrics_history.jsonl",
        directory / "_shared_baseline" / "state" / "metrics_history.jsonl",
    ]
    for path in candidates:
        if not path.exists():
            continue
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if rows:
            return rows
    return []


def _bundle_score(directory: Path) -> float:
    """同一事件可能有多次实验，优先选材料最全、步数最多的那一次。"""
    score = 0.0
    for key, filename in _BUNDLE_FILES.items():
        if (directory / filename).exists():
            score += 2 if key != "initial_opinion" else 1
    score += len(_read_metrics(directory)) * 0.1
    return score


def discover_bundles(experiments_dir: Path) -> list[Bundle]:
    """扫描实验目录，每个 event_id 选一份最完整的材料。"""
    chosen: dict[str, tuple[float, Path]] = {}
    for directory in sorted(experiments_dir.iterdir()):
        event_file = directory / "event_input.json"
        if not directory.is_dir() or not event_file.exists():
            continue
        try:
            payload = _read_json(event_file)
        except json.JSONDecodeError:
            continue
        event_id = str(payload.get("event_id") or directory.name)
        score = _bundle_score(directory)
        previous = chosen.get(event_id)
        # 分数更高者优先；同分时目录名更大（更晚）者优先
        if previous is None or (score, directory.name) > (previous[0], previous[1].name):
            chosen[event_id] = (score, directory)

    bundles: list[Bundle] = []
    for event_id, (_, directory) in sorted(chosen.items()):
        bundle = Bundle(
            event_id=event_id,
            directory=directory,
            event_input=_read_json(directory / "event_input.json"),
        )
        for key, filename in _BUNDLE_FILES.items():
            path = directory / filename
            if path.exists():
                try:
                    setattr(bundle, key, _read_json(path))
                except json.JSONDecodeError:
                    pass
        bundle.metrics = _read_metrics(directory)
        bundles.append(bundle)
    return bundles


# 条件化历史复现的真实事件源，字段要求与 app/historical_replay/event_repository.py 一致
_REQUIRED_EVENT_FILES = (
    "event_manifest.json",
    "event_input.json",
    "official_response_timeline.json",
    "public_context_timeline.json",
    "initial_opinion.json",
)


def discover_historical_events(events_dir: Path) -> list[Bundle]:
    """列出历史复现事件库中的真实事件（不含实验产出、不含条件化方案批次）。

    结构要求：event_manifest.json 与各输入文件的 event_id 必须与目录名一致，
    缺任一必需文件即跳过，避免把方案实验目录当成历史事件。
    """
    bundles: list[Bundle] = []
    if not events_dir.is_dir():
        return bundles
    for directory in sorted(events_dir.iterdir()):
        if not directory.is_dir():
            continue
        if any(not (directory / name).is_file() for name in _REQUIRED_EVENT_FILES):
            continue
        try:
            manifest = _read_json(directory / "event_manifest.json")
            payload = _read_json(directory / "event_input.json")
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("event_id") != directory.name or payload.get("event_id") != directory.name:
            continue
        bundle = Bundle(
            event_id=directory.name,
            directory=directory,
            event_input=payload,
            manifest=manifest,
            origin="historical_replay",
        )
        for key, filename in _BUNDLE_FILES.items():
            path = directory / filename
            if path.exists():
                try:
                    setattr(bundle, key, _read_json(path))
                except json.JSONDecodeError:
                    pass
        bundles.append(bundle)
    return bundles


def attach_historical_metrics(bundles: list[Bundle], experiments_dir: Path) -> None:
    """把该事件最近一次 historical_replay 批次的逐轮指标挂到事件上。

    只认根部 historical_replay_result.json 且 mode=historical_replay 的批次，
    回应方案/条件分支实验不参与，避免把策略实验结果当成历史事实。
    """
    if not experiments_dir.is_dir():
        return
    for bundle in bundles:
        for run in sorted(experiments_dir.glob(f"{bundle.event_id}_*"), reverse=True):
            result_file = run / "historical_replay_result.json"
            if not result_file.is_file():
                continue
            try:
                if _read_json(result_file).get("mode") != "historical_replay":
                    continue
            except (OSError, json.JSONDecodeError):
                continue
            metrics = _read_metrics(run)
            if metrics:
                bundle.metrics = metrics
                bundle.run_dir = run
                # 事件讨论角度来自该真实事件的复现批次，仅用于补充议题节点
                pool = run / "comment_pool.json"
                if pool.is_file():
                    try:
                        bundle.comments = _read_json(pool)
                    except json.JSONDecodeError:
                        pass
                break


def bundle_provenance(bundle: Bundle) -> dict[str, Any]:
    """事件级出处信息：真实事件库、当次历史复现批次、第一轮人工参照。"""
    manifest = bundle.manifest or {}
    opinion = (bundle.initial_opinion or {}).get("observed_distribution") or {}

    def rate(key: str) -> float | None:
        item = opinion.get(key) or {}
        value = item.get("estimate")
        if value is None and item.get("lower") is not None and item.get("upper") is not None:
            try:
                value = (float(item["lower"]) + float(item["upper"])) / 2
            except (TypeError, ValueError):
                value = None
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return None

    return {
        "origin": bundle.origin,
        "manifest_title": str(manifest.get("title") or ""),
        "run_id": bundle.run_dir.name if bundle.run_dir else "",
        "initial_opinion_mode": str((bundle.initial_opinion or {}).get("mode") or ""),
        "init_negative_rate": rate("negative"),
        "init_neutral_rate": rate("neutral"),
        "init_positive_rate": rate("positive"),
        "real_trend_source": str(manifest.get("real_trend_source_original_name") or ""),
    }


def build_llm_payload(bundle: Bundle) -> dict[str, Any]:
    """给大模型的材料：只保留与抽取有关的字段，控制 token 量。"""
    phases = []
    timeline = []
    if bundle.public_context:
        for step in bundle.public_context.get("steps", []):
            phases.append(
                {
                    "step": step.get("step"),
                    "period": step.get("period"),
                    "phase": step.get("phase"),
                }
            )
            timeline.append(
                {
                    "step": step.get("step"),
                    "period": step.get("period"),
                    "phase": step.get("phase"),
                    "verified_updates": step.get("verified_updates") or [],
                    "public_discourse": step.get("public_discourse") or [],
                    "positive_evidence": step.get("positive_evidence") or [],
                }
            )
    elif bundle.official:
        phases = list(bundle.official.get("step_periods") or [])

    angles = []
    if bundle.comments:
        angles = [
            {
                "angle_id": angle.get("angle_id"),
                "angle_name": angle.get("angle_name"),
                "focus": angle.get("focus"),
            }
            for angle in (bundle.comments.get("angle_plan") or {}).get("angles", [])
        ]

    return {
        "event_id": bundle.event_id,
        "event_content": bundle.content,
        "event_labels": bundle.labels,
        "phases": phases,
        "timeline": timeline,
        "official_updates": (bundle.official or {}).get("official_updates", []),
        "comment_angles": angles,
    }


# ---------------------------------------------------------------------------
# 规则抽取（离线基线）
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"[。；;！!？?\n]+")
_CLAUSE_SPLIT = re.compile(r"[，,：:]")
_DATE_PREFIX = re.compile(
    r"^\s*(?:\d{4}年)?\d{1,2}月\d{1,2}日(?:\d{1,2}时(?:许)?)?"
    r"(?:上午|中午|下午|傍晚|晚上|凌晨|凌晨时分)?[，,]?\s*"
)

# 事件类型关键词，仅用于离线模式生成可读的事件名
_EVENT_TYPE_RULES = (
    ("失联", "失联"),
    ("殴打", "殴打他人"),
    ("冲入", "车辆冲入"),
    ("碰撞", "车辆碰撞"),
    ("坠", "坠楼"),
    ("火灾", "火灾"),
)

_LOCATION_SUFFIXES = (
    "省", "市", "县", "镇", "街道", "路口", "广场", "商场",
    "学校", "中学", "小区", "公园", "路段", "区域", "树林",
)
_LOCATION_DISCUSSION = (
    "担忧", "质疑", "讨论", "关注", "追问", "说法", "细节", "透明度",
    "结论", "信息", "进展", "观点", "评论", "情绪",
)
_LOCATION_ACTION = (
    "车辆", "视频", "通告", "驾驶", "撞击", "失控", "报道", "通报", "事件",
    "接报", "发现", "前往", "参与", "开展", "公布",
)

_ACTOR_RULES: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
    (("驾驶人", "驾驶人员", "司机", "车主"), "驾驶人", "person", "涉事方"),
    (("过路群众", "热心市民", "路人"), "过路群众", "group", "救助者"),
    (("两名女子", "一名女子", "涉事女子", "女子"), "涉事女子", "person", "涉事方"),
    (("胡某宇", "胡鑫宇"), "胡某宇", "person", "当事人"),
    (("家属", "父母"), "家属", "group", "关联方"),
    (("社会力量", "志愿者"), "社会力量", "group", "参与者"),
    (("联合工作专班", "工作专班", "公安机关", "警方", "民警", "大队"), "公安机关", "organization", "处置方"),
    (("网民", "网友", "公众"), "网民", "group", "讨论者"),
    (("媒体", "记者"), "媒体", "organization", "传播者"),
)

_CAUSE_NOUNS = ("原因", "死因", "诱因", "病因", "起因", "因此", "因为")
_UNCERTAIN_MARKERS = ("尚未", "尚无", "未获", "未公布", "不明确", "待查", "传言")
_CONSEQUENCE_MARKERS = ("造成", "导致", "受伤", "死亡", "自缢", "无大碍", "未造成")
_CONSEQUENCE_NOISE = ("尚无", "尚未", "追问", "讨论", "质疑", "关注", "说法", "传言", "可能", "或许")

_GENERIC_TOPICS = (
    ("事故原因", ("事故原因",)),
    ("人员伤亡", ("伤亡",)),
    ("责任认定", ("责任认定",)),
    ("驾驶人身份", ("驾驶人身份", "驾驶人员身份")),
    ("公共场所安全", ("治安管理", "公共场所")),
    ("监控与证据", ("监控",)),
    ("网络传言", ("传言", "谣言")),
)


def _clauses(text: str) -> list[str]:
    result: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for clause in _CLAUSE_SPLIT.split(sentence):
            clause = clause.strip(" \t，,。；;：:")
            if clause:
                result.append(clause)
    return result


def _clean_location(clause: str) -> str:
    clause = re.sub(r"^(事发地点|地点)?(位于|在)", "", clause).strip()
    clause = re.sub(r"^(我大队|大队)?辖区", "", clause).strip()
    clause = re.sub(r"(发生|引发|导致)[^，,。]*$", "", clause).strip()
    clause = re.sub(r"的[^，,。]*$", "", clause).strip()
    return clause


def _plausible_location(name: str) -> bool:
    """过滤“一位网约车司机接单后误入人流密集路段”这类句子级伪地点。"""

    text = str(name or "").strip()
    if not text or len(text) > 20:
        return False
    if any(word in text for word in ("司机", "接单", "误入", "人群", "乘客", "发生", "导致", "随后")):
        return False
    return True


def _find_locations(text: str, limit: int = 3) -> list[str]:
    found: list[str] = []
    for raw in _clauses(text):
        if any(word in raw for word in _LOCATION_DISCUSSION):
            continue
        clause = _clean_location(raw)
        if not 3 <= len(clause) <= 30:
            continue
        if any(word in clause for word in _LOCATION_ACTION):
            continue
        district = re.match(r"^[\u4e00-\u9fa5]{2,8}(?:区|县)", clause)
        if not district and not any(suffix in clause for suffix in _LOCATION_SUFFIXES):
            continue
        if clause not in found:
            found.append(clause)
        if len(found) >= limit:
            break
    return found


def _find_actors(text: str) -> list[dict[str, str]]:
    actors: list[dict[str, str]] = []
    seen: set[str] = set()
    for keywords, name, actor_type, role in _ACTOR_RULES:
        if name in seen:
            continue
        if any(keyword in text for keyword in keywords):
            seen.add(name)
            actors.append({"name": name, "type": actor_type, "role": role})
    return actors


def _find_causes(text: str) -> list[str]:
    causes: list[str] = []
    for clause in _clauses(text):
        if any(marker in clause for marker in _UNCERTAIN_MARKERS):
            continue
        has_marker = "由于" in clause or "突发疾病" in clause or "操作不当" in clause
        if not has_marker:
            for match in re.finditer("因", clause):
                previous = clause[match.start() - 1] if match.start() else ""
                if previous in "原死诱病起":
                    continue
                if clause[match.start() : match.start() + 2] in ("因此", "因为"):
                    continue
                has_marker = True
                break
        if not has_marker:
            continue
        cause = re.sub(
            r"^(经查|经调查|初步调查|据通报|通告称|通报称|警方通报|我大队)[，,]?", "", clause
        ).strip()
        if 4 <= len(cause) <= 120 and cause not in causes:
            causes.append(cause)
    return causes[:2]


def _find_consequences(text: str) -> list[str]:
    results: list[str] = []
    for clause in _clauses(text):
        if any(noise in clause for noise in _CONSEQUENCE_NOISE):
            continue
        if any(marker in clause for marker in _CONSEQUENCE_MARKERS):
            if 4 <= len(clause) <= 120 and clause not in results:
                results.append(clause)
    return results[:2]


def _shorten(text: str, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for mark in ("。", "；", "，", "、"):
        index = cut.rfind(mark)
        if index >= limit * 0.5:
            return cut[: index + 1]
    return cut + "…"


def _event_name(bundle: Bundle) -> str:
    """事件名优先用 event_manifest.json 的正式标题，缺失时退化为地点+类型。"""
    title = str((bundle.manifest or {}).get("title") or "").strip()
    if title:
        return re.sub(r"（[^）]*）\s*$", "", title).strip()
    locations = _find_locations(bundle.content, limit=1)
    place = locations[0] if locations else (_event_region(bundle) or "")
    event_type = "事件"
    for keyword, label in _EVENT_TYPE_RULES:
        if keyword in bundle.content:
            event_type = label + "事件"
            break
    if not place:
        name = _shorten(_DATE_PREFIX.sub("", bundle.content), 22).rstrip("，。；")
        return f"{name}{event_type}"
    if place.endswith(("事件", "事故")):
        return _shorten(place, 24)
    return _shorten(f"{place}{event_type}", 24)


def _event_time(bundle: Bundle) -> str:
    # 兼容“2026年10月31日”与“10月31号”两种写法；后者常见于用户自定义事件。
    match = re.search(
        r"(?:\d{4}年)?\d{1,2}月\d{1,2}[日号](?:上午|中午|下午|傍晚|晚上|凌晨)?",
        bundle.content,
    )
    return match.group(0) if match else ""


def _event_region(bundle: Bundle) -> str:
    text = bundle.content
    province = re.search(r"([\u4e00-\u9fa5]{2,4}(?:省|自治区))", text)
    city = re.search(r"(?:[\u4e00-\u9fa5]{2,4}(?:省|自治区))?([\u4e00-\u9fa5]{2,6}市)", text)
    if province or city:
        return (province.group(1) if province else "") + (city.group(1) if city else "")
    location = (_find_locations(text, limit=1) or [""])[0]
    match = re.match(
        r"^([\u4e00-\u9fa5]{2,8}?)(?:一|的|附近|路口|广场|商场|学校|中学|小区|公园|路段|区域|县|区|市)",
        location,
    )
    return match.group(1) if match else ""


def _topic_candidates(bundle: Bundle) -> list[dict[str, str]]:
    topics: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, focus: str = "") -> None:
        name = name.strip(" ：:，,。")
        if not name or len(name) > 24:
            return
        for existing in seen:
            if name in existing or existing in name:
                return
        seen.add(name)
        topics.append({"name": name, "focus": focus[:160]})

    angles = (bundle.comments or {}).get("angle_plan", {}).get("angles", [])
    for angle in angles:
        add(str(angle.get("angle_name") or ""), str(angle.get("focus") or ""))

    discussion = re.search(r"公众讨论主要集中在(.+?)(?:。|$)", bundle.content)
    if discussion:
        for part in re.split(r"[、，]|以及|和", discussion.group(1)):
            add(part)

    for name, keywords in _GENERIC_TOPICS:
        if any(keyword in bundle.content for keyword in keywords):
            add(name)
    return topics[:10]


def _source_ref(ref: Any) -> str:
    text = str(ref or "").strip()
    text = re.sub(r"^人工采集表[：:]", "", text)
    text = re.split(r"[；;]", text)[0].strip()
    return text[:160]


def _iter_phases(bundle: Bundle) -> list[dict[str, Any]]:
    if bundle.public_context and bundle.public_context.get("steps"):
        return [
            {
                "step": step.get("step"),
                "period": step.get("period"),
                "phase": step.get("phase") or f"阶段{step.get('step')}",
            }
            for step in bundle.public_context["steps"]
        ]
    if bundle.official and bundle.official.get("step_periods"):
        return [
            {
                "step": item.get("step"),
                "period": item.get("period"),
                "phase": item.get("phase") or f"阶段{item.get('step')}",
            }
            for item in bundle.official["step_periods"]
        ]
    return [{"step": 1, "period": "", "phase": "事件发酵期"}]


def _norm(text: str) -> str:
    text = re.sub(r"^(通告称|通报称|据通报|警方通报)", "", text.strip())
    return re.sub(r"[\s，。；;：:、“”\"'（）()！!？?]", "", text)


def heuristic_extract(bundle: Bundle) -> dict[str, Any]:
    """规则抽取：把 timeline / 通报 / 评论角度转成统一的抽取结构。"""
    phases = _iter_phases(bundle)
    phase_by_step = {item["step"]: item["phase"] for item in phases}
    period_by_step = {item["step"]: item.get("period", "") for item in phases}
    sub_events: list[dict[str, Any]] = []

    def add_sub_event(
        summary: str,
        *,
        step: int | None,
        kind: str,
        status: str,
        sources: list[str],
        time_text: str = "",
        phase: str = "",
        location: str = "",
        actors: list[str] | None = None,
        causes: list[str] | None = None,
        consequences: list[str] | None = None,
    ) -> str:
        sid = f"se_{len(sub_events) + 1}"
        summary = _shorten(summary, 120)
        normalized = _norm(summary)
        for existing in sub_events:
            if existing["step"] != step:
                continue
            other = _norm(existing["summary"])
            shorter, longer = (normalized, other) if len(normalized) <= len(other) else (other, normalized)
            if len(shorter) >= 8 and shorter in longer:
                existing["sources"] = list(dict.fromkeys(existing["sources"] + sources))
                return existing["id"]
        resolved_location = location or (_find_locations(summary) or [""])[0]
        if not _plausible_location(resolved_location):
            resolved_location = ""
        sub_events.append(
            {
                "id": sid,
                "summary": summary,
                "step": step,
                "time_text": time_text,
                "phase": phase,
                "kind": kind,
                "status": status,
                "actors": actors if actors is not None else [a["name"] for a in _find_actors(summary)],
                "location": resolved_location,
                "causes": causes if causes is not None else _find_causes(summary),
                "consequences": consequences if consequences is not None else _find_consequences(summary),
                "sources": sources,
            }
        )
        return sid

    # 1) 分阶段时间线：已核实信息、公众讨论、正面证据
    for step in (bundle.public_context or {}).get("steps", []):
        number = step.get("step")
        for item in step.get("verified_updates") or []:
            add_sub_event(
                item.get("content", ""),
                step=number,
                kind="verified",
                status="unconfirmed" if any(m in item.get("content", "") for m in _UNCERTAIN_MARKERS) else "confirmed",
                sources=[_source_ref(ref) for ref in item.get("source_refs") or []],
                time_text=step.get("period", ""),
                phase=phase_by_step.get(number, ""),
            )
        for item in step.get("public_discourse") or []:
            add_sub_event(
                item.get("content", ""),
                step=number,
                kind="discourse",
                status="unconfirmed",
                sources=[_source_ref(ref) for ref in item.get("source_refs") or []],
                time_text=step.get("period", ""),
                phase=phase_by_step.get(number, ""),
            )
        for item in step.get("positive_evidence") or []:
            add_sub_event(
                item.get("content", ""),
                step=number,
                kind="positive",
                status="confirmed",
                sources=[_source_ref(ref) for ref in item.get("source_refs") or []],
                time_text=step.get("period", ""),
                phase=phase_by_step.get(number, ""),
            )

    # 2) 官方通报：既作为进展节点，也作为 Claim 节点
    claims: list[dict[str, Any]] = []
    for index, update in enumerate((bundle.official or {}).get("official_updates", []), start=1):
        step = update.get("step")
        statement = str(update.get("official_statement") or "").strip()
        if not statement:
            continue
        status = "confirmed" if update.get("official_statement_status") == "clear" else "partial"
        sources = [_source_ref(update.get("source_url"))] if update.get("source_url") else []
        sid = add_sub_event(
            _shorten(statement, 110),
            step=step,
            kind="official",
            status=status,
            sources=sources,
            time_text=period_by_step.get(step, ""),
            phase=phase_by_step.get(step, ""),
        )
        publisher = "公安机关"
        if "联合工作专班" in statement:
            publisher = "联合工作专班"
        claims.append(
            {
                "id": f"claim_{index}",
                "text": statement,
                "publisher": publisher,
                "published_at": str(update.get("published_at") or ""),
                "status": status,
                "about_sub_events": [sid],
                "sources": sources,
            }
        )

    # 3) 没有时间线的事件：从正文拆出概述性进展
    if not sub_events:
        for sentence in _SENTENCE_SPLIT.split(bundle.content):
            sentence = sentence.strip()
            if len(sentence) < 8:
                continue
            add_sub_event(
                sentence,
                step=1,
                kind="discourse" if "讨论" in sentence else "verified",
                status="unconfirmed",
                sources=["event_input.json"],
                phase=phases[0]["phase"],
            )
            if len(sub_events) >= 3:
                break

    # 按阶段排序，保证 NEXT 链与报告时间线一致（同阶段保持原顺序）
    sub_events.sort(key=lambda item: (item["step"] is None, item["step"] or 0))

    locations: list[str] = []
    hint = str((bundle.manifest or {}).get("location_hint") or "").strip()
    for name in [hint, _event_region(bundle), *_find_locations(bundle.content, limit=2)]:
        if name and _plausible_location(name) and name not in locations:
            locations.append(name)
    for sub in sub_events:
        if sub["location"] and sub["location"] not in locations:
            locations.append(sub["location"])

    actors: list[dict[str, str]] = []
    seen_actors: set[str] = set()
    for sub in sub_events:
        for actor in _find_actors(sub["summary"]):
            if actor["name"] in seen_actors:
                continue
            seen_actors.add(actor["name"])
            actors.append(actor)

    event_locations = [name for name in _find_locations(bundle.content, limit=2) if _plausible_location(name)]
    if hint:
        event_locations = [hint, *event_locations]
    data = {
        "event": {
            "name": _event_name(bundle),
            "summary": _shorten(bundle.content, 110),
            "topic": str(bundle.labels.get("topic") or "社会事件"),
            "valence": str(bundle.labels.get("event_valence") or "neutral"),
            "time_text": _event_time(bundle),
            "region": _event_region(bundle),
            "location": event_locations[0] if event_locations else (locations[0] if locations else ""),
        },
        "phases": phases,
        "sub_events": sub_events,
        "actors": actors,
        "locations": locations,
        "topics": _topic_candidates(bundle),
        "claims": claims,
        "extraction_mode": "heuristic",
    }
    return validate_extraction(data, bundle.event_id)[0]


def llm_extract(bundle: Bundle, cfg: LLMConfig, cache_dir: Path, refresh: bool = False) -> dict[str, Any]:
    """调用大模型抽取，结果落缓存后校验。"""
    payload = build_llm_payload(bundle)
    user_prompt = build_user_prompt(payload)
    data, meta = chat_json(
        SYSTEM_PROMPT,
        user_prompt,
        cfg,
        cache_path=cache_dir / f"{bundle.event_id}.json",
        refresh=refresh,
    )
    data["extraction_mode"] = "llm"
    normalized, _ = validate_extraction(data, bundle.event_id)
    if not normalized["phases"]:
        seen: set[str] = set()
        for sub in normalized["sub_events"]:
            name = sub.get("phase") or ""
            if name and name not in seen:
                seen.add(name)
                normalized["phases"].append(
                    {"step": sub.get("step"), "period": sub.get("time_text", ""), "phase": name}
                )
    normalized["llm_meta"] = meta
    return normalized


def build_snapshots(bundle: Bundle) -> list[dict[str, Any]]:
    """把实验产出的逐轮舆情指标转成阶段快照。"""
    if not bundle.metrics:
        return []
    phase_by_step = {item["step"]: item["phase"] for item in _iter_phases(bundle)}
    phases = _iter_phases(bundle)
    # 没有时间线的事件只有一个阶段，所有指标都归到该阶段
    single_phase = phases[0]["phase"] if len({item["phase"] for item in phases}) == 1 else ""
    snapshots: list[dict[str, Any]] = []
    for row in bundle.metrics:
        try:
            step = int(row.get("step"))
        except (TypeError, ValueError):
            step = None
        distribution = (row.get("official_attitude_distribution") or {}).get("distribution") or {}
        snapshots.append(
            {
                "step": step,
                "phase": phase_by_step.get(step, single_phase),
                "trend": (row.get("global_trend") or {}).get("trend_direction") or "",
                "negative_rate": (row.get("agent_negative_emotion") or {}).get("negative_rate"),
                "question_rate": (distribution.get("question") or {}).get("rate"),
                "accept_rate": (distribution.get("accept") or {}).get("rate"),
            }
        )
    return snapshots


def extract_all(
    bundles: list[Bundle],
    mode: str = "heuristic",
    cache_dir: Path | None = None,
    refresh: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """批量抽取，返回 (结果列表, 警告列表)。"""
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    cfg = None
    if mode == "llm":
        from pipelines.kg.llm import config_from_env

        cfg = config_from_env()
        if cfg is None:
            warnings.append("未检测到 KG_LLM_API_KEY / DEEPSEEK_API_KEY，本次回退为规则抽取。")
            mode = "heuristic"

    for bundle in bundles:
        if bundle.origin == "legacy_corpus":
            # 历史语料没有时间线/通报/趋势，用确定性规则而不是通用启发式，
            # 避免把“城市/市场”这类词误抽成地点、把标题写成一整句话。
            from pipelines.kg.legacy_corpus import curated_extract

            result = curated_extract(bundle)
        elif mode == "llm" and cfg is not None:
            try:
                result = llm_extract(bundle, cfg, cache_dir or Path("out/cache"), refresh)
            except Exception as exc:  # 单个事件失败不影响整体
                warnings.append(f"{bundle.event_id}: 大模型抽取失败（{exc}），已回退规则抽取。")
                result = heuristic_extract(bundle)
        else:
            result = heuristic_extract(bundle)
        warnings.extend(result.get("warnings", []))
        result.setdefault("source_bundle", str(bundle.directory))
        result["provenance"] = bundle_provenance(bundle)
        results.append(result)
    return results, warnings
