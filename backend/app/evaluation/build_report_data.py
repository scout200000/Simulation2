"""从真实实验批次生成报告数据：规则评分 + 大模型优劣分析。

评分（规则，可复现）：
    评论情绪分 = (正面 + 0.5 × 中性) / 评论总数 × 100
    官方态度分 = (accept + 0.5 × wait) / 相关决策数 × 100
    单轮综合分 = 0.4 × 评论情绪分 + 0.6 × 官方态度分
    总分       = 公告投放轮次起，各轮综合分的算术平均

优劣（大模型）：
    输入公告原文、规则分数、逐轮明细和高价值评论（按传播有效权重排序），
    输出 summary / strengths / risks，用于报告文字部分。

用法::

    python -m app.evaluation.build_report_data \
        --experiment event_gaoyang_assault_001_20261020_141414_286129 \
        --out ../src/data/report-gaoyang-rule.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infrastructure.database.repositories import load_event_input  # noqa: E402
from app.infrastructure.storage.json_storage import load_json, read_jsonl  # noqa: E402
from app.infrastructure.llm.llm_service import call_deepseek_json  # noqa: E402
from app.main.config.settings import EXPERIMENT_DIR  # noqa: E402
RESPONSE_WEIGHTS = {"comment_emotion": 0.4, "official_attitude": 0.6}
EVENT_LABEL_KEYS = {"topic": "主题", "event_valence": "情绪"}
EVENT_LABEL_VALUES = {
    "社会事件": "社会事件",
    "新闻时事": "新闻时事",
    "娱乐": "娱乐",
    "其他": "其他",
    "negative": "负面",
    "neutral": "中性",
    "positive": "正面",
}
ATTITUDE_VALUES = ("accept", "wait", "question")


def judge(score: float) -> str:
    if score >= 80:
        return "优秀"
    if score >= 65:
        return "良好"
    if score >= 50:
        return "中性"
    if score >= 35:
        return "偏负面"
    if score >= 20:
        return "较差"
    return "很差"


def _emotion_score(comments):
    total = len(comments)
    if not total:
        return {"score": 0.0, "total": 0, "positive": 0, "neutral": 0, "negative": 0}
    positive = sum(1 for item in comments if item.get("emotion") == "positive")
    neutral = sum(1 for item in comments if item.get("emotion") == "neutral")
    negative = sum(1 for item in comments if item.get("emotion") == "negative")
    return {
        "score": round((positive + 0.5 * neutral) / total * 100, 2),
        "total": total,
        "positive": positive,
        "neutral": neutral,
        "negative": negative,
    }


def _attitude_score(decisions):
    values = [
        item.get("decision", {}).get("official_attitude")
        for item in decisions
    ]
    accept = sum(1 for value in values if value == "accept")
    wait = sum(1 for value in values if value == "wait")
    question = sum(1 for value in values if value == "question")
    total = accept + wait + question
    if not total:
        return {"score": 0.0, "total": 0, "accept": 0, "wait": 0, "question": 0}
    return {
        "score": round((accept + 0.5 * wait) / total * 100, 2),
        "total": total,
        "accept": accept,
        "wait": wait,
        "question": question,
    }


def load_scenario(experiment_dir: Path, scenario_id: str) -> dict:
    scenario_dir = experiment_dir / scenario_id
    result = load_json(scenario_dir / "scenario_result.json")
    decisions = [
        row
        for row in read_jsonl(scenario_dir / "state" / "decision_history.jsonl")
        if row.get("status") == "success" and isinstance(row.get("decision"), dict)
    ]
    comment_rows = read_jsonl(
        scenario_dir / "state" / "incremental_comment_history.jsonl"
    )
    metrics = read_jsonl(scenario_dir / "state" / "metrics_history.jsonl")
    propagation = read_jsonl(
        scenario_dir / "state" / "propagation_history.jsonl"
    )
    return {
        "id": scenario_id,
        "result": result,
        "decisions": decisions,
        "comment_rows": comment_rows,
        "metrics": metrics,
        "propagation": propagation,
    }


def score_scenario(scenario: dict) -> dict:
    """按规则计算公告效果分，返回总分、逐轮明细和公告原文。"""

    result = scenario["result"]
    responses = result.get("official_responses") or []
    response_step = int(responses[0]["step"]) if responses else 1
    statement = responses[0].get("official_statement", "") if responses else ""

    comments_by_step: dict[int, list] = {}
    for row in scenario["comment_rows"]:
        step = int(row.get("step") or 0)
        if step >= response_step:
            comments_by_step.setdefault(step, []).extend(row.get("comments") or [])

    decisions_by_step: dict[int, list] = {}
    for row in scenario["decisions"]:
        step = int(row.get("step") or 0)
        if step >= response_step:
            decisions_by_step.setdefault(step, []).append(row)

    rounds = []
    for step in sorted(set(comments_by_step) | set(decisions_by_step)):
        comment = _emotion_score(comments_by_step.get(step, []))
        attitude = _attitude_score(decisions_by_step.get(step, []))
        combined = round(
            RESPONSE_WEIGHTS["comment_emotion"] * comment["score"]
            + RESPONSE_WEIGHTS["official_attitude"] * attitude["score"],
            2,
        )
        rounds.append(
            {
                "step": step,
                "comment_score": comment["score"],
                "attitude_score": attitude["score"],
                "combined_score": combined,
                "comment_count": comment["total"],
                "decision_count": attitude["total"],
            }
        )

    total = round(
        statistics.mean(item["combined_score"] for item in rounds), 2
    ) if rounds else 0.0

    return {
        "response_step": response_step,
        "official_statement": statement,
        "official_statement_status": (
            responses[0].get("official_statement_status") if responses else None
        ),
        "total": total,
        "judgement": judge(total),
        "level": judge(total),
        "weights": RESPONSE_WEIGHTS,
        "rounds": rounds,
    }


def high_value_comments(scenario: dict, limit: int = 6) -> list[dict]:
    """按传播有效权重挑选高价值评论。"""

    texts = {}
    for row in scenario["comment_rows"]:
        for comment in row.get("comments") or []:
            texts[comment.get("comment_id")] = {
                "comment_id": comment.get("comment_id"),
                "step": row.get("step"),
                "emotion": comment.get("emotion"),
                "faction": comment.get("faction"),
                "text": comment.get("text", ""),
            }

    weight_by_comment: dict[str, float] = {}
    count_by_comment: dict[str, int] = {}
    for event in scenario["propagation"]:
        comment_id = event.get("comment_id")
        if not comment_id:
            continue
        weight_by_comment[comment_id] = weight_by_comment.get(comment_id, 0.0) + float(
            event.get("effective_weight") or 0
        )
        count_by_comment[comment_id] = count_by_comment.get(comment_id, 0) + 1

    ranked = sorted(
        weight_by_comment.items(), key=lambda item: item[1], reverse=True
    )
    picked = []
    for comment_id, weight in ranked:
        info = texts.get(comment_id)
        if not info or not info["text"]:
            continue
        if any(item["text"] == info["text"] for item in picked):
            continue
        info["propagation_weight"] = round(weight, 2)
        info["propagation_count"] = count_by_comment.get(comment_id, 0)
        picked.append(info)
        if len(picked) >= limit:
            break
    return picked


def analyse_with_llm(statement: str, score: dict, comments: list[dict]) -> dict:
    """让大模型基于公告、规则分和高价值评论判断优劣。"""

    payload = {
        "公告原文": statement,
        "规则评分": {
            "总分": score["total"],
            "判定": score["judgement"],
            "权重": score["weights"],
            "逐轮": score["rounds"],
        },
        "高价值评论": [
            {
                "轮次": item.get("step"),
                "情绪": item.get("emotion"),
                "派系": item.get("faction"),
                "传播权重": item.get("propagation_weight"),
                "文本": item.get("text"),
            }
            for item in comments
        ],
    }
    prompt = (
        "你是舆情回应分析助手。以下是一次模拟推演中某个官方公告的规则评分结果"
        "和高价值评论（按传播影响力排序）。\n"
        "请只依据给出的材料判断这份公告的优劣，不要编造未出现的事实。\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "返回 JSON：\n"
        '{"summary": "一句话总体评价（40字内）", '
        '"strengths": ["优势1", "优势2"], '
        '"risks": ["风险1", "风险2"]}\n'
        "要求：每条不超过40字；优势与风险各2-3条；必须结合具体评论或分数，"
        "不要空泛表述。"
    )
    result = call_deepseek_json(
        prompt=prompt,
        system_prompt="你只输出合法 JSON，不输出解释文字。",
        temperature=0.2,
        max_tokens=800,
        request_type="report_plan_analysis",
    )
    return {
        "summary": str(result.get("summary", "")).strip()[:120],
        "strengths": [str(x).strip() for x in result.get("strengths", [])][:4],
        "risks": [str(x).strip() for x in result.get("risks", [])][:4],
    }


def analyse_overall(plans: list[dict], baseline: dict) -> dict:
    payload = {
        "基线（不回应）": baseline,
        "方案": [
            {
                "名称": plan["name"],
                "总分": plan["score"]["total"],
                "判定": plan["score"]["judgement"],
                "评论情绪分": plan["score"]["rounds"][0]["comment_score"] if plan["score"]["rounds"] else 0,
                "官方态度分": plan["score"]["rounds"][0]["attitude_score"] if plan["score"]["rounds"] else 0,
                "优势": plan["analysis"]["strengths"],
                "风险": plan["analysis"]["risks"],
            }
            for plan in plans
        ],
    }
    prompt = (
        "你是舆情分析助手。以下是一次推演的规则评分与各方案优劣。\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "返回 JSON：\n"
        '{"overall": "150字以内的总体结论", '
        '"recommendations": ["建议1", "建议2", "建议3"]}\n'
        "要求：结论只基于给定数据；建议面向下一阶段官方回应，具体可执行。"
    )
    result = call_deepseek_json(
        prompt=prompt,
        system_prompt="你只输出合法 JSON，不输出解释文字。",
        temperature=0.2,
        max_tokens=900,
        request_type="report_overall",
    )
    return {
        "overall": str(result.get("overall", "")).strip()[:300],
        "recommendations": [
            str(x).strip() for x in result.get("recommendations", [])
        ][:5],
    }


def fallback_analysis(score: dict) -> dict:
    """规则模式下的公告优劣摘要，避免没有模型密钥时报告空白。"""
    rounds = score.get("rounds") or []

    def average(field):
        values = [
            item.get(field)
            for item in rounds
            if isinstance(item.get(field), (int, float))
        ]
        return round(statistics.mean(values), 2) if values else 0.0

    comment_score = average("comment_score")
    attitude_score = average("attitude_score")
    total = score.get("total", 0)
    strengths = []
    risks = []

    if attitude_score >= 50:
        strengths.append(f"官方态度分 {attitude_score:g}，接受与观望合计占优")
    else:
        risks.append(f"官方态度分 {attitude_score:g}，质疑比例偏高")

    if comment_score >= 50:
        strengths.append(f"评论情绪分 {comment_score:g}，正面与中性表达占优")
    else:
        risks.append(f"评论情绪分 {comment_score:g}，负面表达仍占上风")

    status = score.get("official_statement_status")
    if status in {"incomplete", "conflict"}:
        risks.append(f"公告状态为 {status}，信息完整性可能削弱可信度")
    if not strengths:
        strengths.append(f"规则总分 {total:g}，公告形成了基本回应")
    if not risks:
        risks.append("规则分未覆盖执行细节，仍需结合评论区追问复核")

    return {
        "summary": (
            f"规则总分 {total:g}（{score.get('judgement', '')}）："
            f"评论情绪 {comment_score:g}，官方态度 {attitude_score:g}。"
        ),
        "strengths": strengths[:3],
        "risks": risks[:3],
    }


def build(
    experiment_id: str,
    use_llm: bool = True,
    title: str | None = None,
    event_title: str | None = None,
    event_time: str | None = None,
    event_location: str | None = None,
    experiment_dir: Path | None = None,
    experiment_result: dict | None = None,
    event_input: dict | None = None,
) -> dict:
    experiment_dir = Path(experiment_dir or (EXPERIMENT_DIR / experiment_id))
    result = (
        experiment_result
        if experiment_result is not None
        else load_json(experiment_dir / "experiment_result.json")
    )
    event = (
        event_input
        if event_input is not None
        else load_event_input(
            experiment_dir / "event_input.json",
            required=False,
        )
        or {}
    )
    scenarios = {
        item.get("strategy"): item for item in result.get("strategy_results", [])
    }
    scenario_ids = [key for key in scenarios if key != "no_response"]

    plans = []
    for scenario_id in sorted(scenario_ids):
        scenario = load_scenario(experiment_dir, scenario_id)
        score = score_scenario(scenario)
        comments = high_value_comments(scenario)
        analysis = None
        if use_llm:
            try:
                analysis = analyse_with_llm(
                    score["official_statement"], score, comments
                )
            except Exception as error:  # noqa: BLE001 - 报告不能因为模型失败而中断
                print(f"[report] 公告分析模型调用失败，改用规则摘要：{error}")
        if not analysis:
            analysis = fallback_analysis(score)
        plans.append(
            {
                "id": scenario_id,
                "name": scenarios[scenario_id].get("strategy_name") or scenario_id,
                "score": score,
                "analysis": analysis,
                "comments": comments,
            }
        )

    baseline_effect = (
        (scenarios.get("no_response") or {}).get("effect_metrics") or {}
    )
    if not baseline_effect:
        # 单策略会话没有 no_response 对照，直接用当前方案的生效指标作为基线
        baseline_effect = next(
            (
                item.get("effect_metrics") or {}
                for item in scenarios.values()
                if item.get("effect_metrics")
            ),
            {},
        )
    baseline = {
        "negative_peak_rate": baseline_effect.get("negative_peak_rate"),
        "final_negative_rate": baseline_effect.get("final_negative_rate"),
    }

    best = max(plans, key=lambda item: item["score"]["total"]) if plans else None
    final_rate = (
        ((scenarios.get(best["id"]) or {}).get("effect_metrics") or {}).get(
            "final_negative_rate", 0
        )
        if best
        else 0
    )
    overall = None
    if use_llm and plans:
        try:
            overall = analyse_overall(plans, baseline)
        except Exception as error:  # noqa: BLE001 - 模型失败时给出规则结论
            print(f"[report] 总体分析模型调用失败，改用规则结论：{error}")
    if not overall:
        peak = baseline.get("negative_peak_rate") or 0
        overall = {
            "overall": (
                f"最佳方案「{best['name']}」规则总分 {best['score']['total']}"
                f"（{best['score']['judgement']}）；负面率峰值 {peak:.0%}，"
                f"推演结束时为 {final_rate:.0%}。"
                if best
                else "本次会话还没有可评分的公告方案。"
            ),
            "recommendations": [
                "优先补齐评论区高频追问的事实细节与处置进度",
                "在下一轮公告中明确责任主体、处理时限与受害者救助安排",
                "保持多轮公告口径一致，减少 incomplete / conflict 状态反复出现",
            ],
        }

    # 情绪走势取三个回应方案的均值
    trend_by_step: dict[int, list] = {}
    for scenario_id in scenario_ids:
        metrics = load_scenario(experiment_dir, scenario_id)["metrics"]
        for row in metrics:
            step = int(row.get("step") or 0)
            distribution = (row.get("agent_emotion_distribution") or {}).get(
                "distribution", {}
            )
            if not distribution:
                continue
            trend_by_step.setdefault(step, []).append(
                {
                    "negative": (distribution.get("negative") or {}).get("rate", 0),
                    "neutral": (distribution.get("neutral") or {}).get("rate", 0),
                    "positive": (distribution.get("positive") or {}).get("rate", 0),
                }
            )
    trend = []
    for step in sorted(trend_by_step):
        rows = trend_by_step[step]
        trend.append(
            {
                "round": step,
                "negative": round(statistics.mean(r["negative"] for r in rows), 4),
                "neutral": round(statistics.mean(r["neutral"] for r in rows), 4),
                "positive": round(statistics.mean(r["positive"] for r in rows), 4),
            }
        )

    key_comments = []
    if best:
        for index, item in enumerate(best["comments"][:4], 1):
            key_comments.append(
                {
                    "id": f"comment-{index:02d}",
                    "round": item.get("step"),
                    "emotion": item.get("emotion"),
                    "faction": item.get("faction"),
                    "text": item.get("text"),
                    "insight": (
                        f"该评论在推演中被曝光 {item.get('propagation_count')} 次，"
                        f"累计有效权重 {item.get('propagation_weight')}。"
                    ),
                }
            )

    return {
        "report_id": f"report_{experiment_id}",
        "title": title
        or f"{event.get('event_labels', {}).get('topic', '舆情')}舆情推演报告",
        "subtitle": "规则评分与大模型优劣分析",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "simulation": {
            "batch_id": experiment_id,
            "rounds": len(trend),
            "agent_count": 30,
            "model": "DeepSeek V4 Flash",
        },
        "event": {
            "event_id": event.get("event_id"),
            "title": event_title
            or event.get("event_labels", {}).get("topic")
            or event.get("event_id"),
            "time": event_time or "",
            "location": event_location or "",
            "labels": [
                f"{EVENT_LABEL_KEYS.get(key, key)}：{EVENT_LABEL_VALUES.get(value, value)}"
                for key, value in (event.get("event_labels") or {}).items()
            ],
            "content": event.get("event_content", ""),
        },
        "summary": {
            "risk_level": (
                "中高" if (baseline.get("negative_peak_rate") or 0) >= 0.6
                else "中" if (baseline.get("negative_peak_rate") or 0) >= 0.4
                else "低"
            ),
            "peak_negative_rate": baseline.get("negative_peak_rate") or 0,
            "final_negative_rate": final_rate,
            "best_announcement_id": best["id"] if best else None,
            "best_score": best["score"]["total"] if best else 0,
            "overall": overall["overall"],
        },
        "sentiment_trend": trend,
        "announcements": [
            {
                "id": plan["id"],
                "name": plan["name"],
                "published_at": f"第{plan['score']['response_step']}轮",
                "text": plan["score"]["official_statement"],
                "score": plan["score"],
                "analysis": plan["analysis"],
                "comments": plan["comments"],
            }
            for plan in plans
        ],
        "word_cloud": [],
        "key_comments": key_comments,
        "conclusion": {
            "recommendations": overall["recommendations"],
            "limitations": (
                "总分由规则计算（评论情绪 0.4 + 官方态度 0.6，公告投放轮次起逐轮平均）；"
                "优势与风险由大模型基于公告原文、规则分数和高价值评论生成，仅供内部讨论。"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成规则评分版报告数据")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--title", default=None)
    parser.add_argument("--event-title", default=None)
    parser.add_argument("--event-time", default=None)
    parser.add_argument("--event-location", default=None)
    args = parser.parse_args()

    data = build(
        args.experiment,
        use_llm=not args.no_llm,
        title=args.title,
        event_title=args.event_title,
        event_time=args.event_time,
        event_location=args.event_location,
    )
    out = Path(args.out)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"报告数据已生成：{out}")
    for item in data["announcements"]:
        print(
            f"  {item['name']}: {item['score']['total']} 分（{item['score']['judgement']}）"
            f" | 评论 {item['score']['rounds'][0]['comment_score'] if item['score']['rounds'] else 0}"
            f" / 态度 {item['score']['rounds'][0]['attitude_score'] if item['score']['rounds'] else 0}"
        )


if __name__ == "__main__":
    main()

