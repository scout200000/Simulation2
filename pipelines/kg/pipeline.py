# -*- coding: utf-8 -*-
"""事件知识图谱流水线：抽取 → 建图 → 生成 Cypher / 报告 / 可视化 →（可选）写入 Neo4j。

用法示例：
    py pipelines/kg/pipeline.py                          # 规则抽取 + 建图 + 出图
    py pipelines/kg/pipeline.py --llm                    # 大模型抽取（需要 API Key）
    py pipelines/kg/pipeline.py --llm --event event_gaoyang_assault_001
    py pipelines/kg/pipeline.py --load --uri bolt://localhost:7687 -u neo4j -p password
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # 支持 py pipelines/kg/pipeline.py 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines.kg.extract import (
    attach_historical_metrics,
    build_snapshots,
    discover_historical_events,
    extract_all,
)
from pipelines.kg.graph import write_graph_artifacts
from pipelines.kg.llm import config_from_env
from pipelines.kg.snapshot_merge import extraction_from_snapshot, load_snapshot, snapshot_event_ids
from pipelines.kg.viz import write_html

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVENTS = ROOT / "data" / "historical_replay" / "events"
DEFAULT_EXPERIMENTS = ROOT / "var" / "experiments"
DEFAULT_OUT = ROOT / "pipelines" / "kg" / "out"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基于条件化历史复现的真实事件搭建 Neo4j 事件知识图谱")
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS, help="历史事件库根目录")
    parser.add_argument(
        "--experiments",
        type=Path,
        default=DEFAULT_EXPERIMENTS,
        help="历史复现批次目录，仅用于挂载逐轮舆情指标",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="产物输出目录")
    parser.add_argument("--mode", choices=("auto", "heuristic", "llm"), default="auto", help="抽取方式")
    parser.add_argument("--llm", action="store_true", help="等价于 --mode llm")
    parser.add_argument("--event", action="append", default=[], help="只处理指定 event_id（可重复）")
    parser.add_argument("--refresh", action="store_true", help="忽略大模型缓存，重新请求")
    parser.add_argument("--no-viz", action="store_true", help="不生成 HTML 可视化")
    parser.add_argument("--legacy-corpus", type=Path, default=None, help="其他历史数据/event.xlsx（历史语料，单阶段）")
    parser.add_argument("--include-store", action="store_true", help="并入 MongoDB events 集合中的非历史复现事件")
    parser.add_argument("--no-keep-snapshot", action="store_true", help="不把本地快照中已有事件并回产物")
    parser.add_argument("--store-uri", default="mongodb://127.0.0.1:27017")
    parser.add_argument("--store-db", default="future_simulation")
    parser.add_argument("--reuse", action="store_true", help="复用 out/extractions.json，不重新抽取")
    parser.add_argument("--load", action="store_true", help="把 Cypher 写入 Neo4j 并验收")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("-u", "--user", default="neo4j")
    parser.add_argument("-p", "--password", default="password")
    parser.add_argument("--database", default=None)
    return parser.parse_args(argv)


def _select_bundles(bundles, keywords: list[str]):
    if not keywords:
        return bundles
    selected = []
    for bundle in bundles:
        if any(key == bundle.event_id or key in bundle.event_id for key in keywords):
            selected.append(bundle)
    return selected


def _snapshot_event_ids() -> set[str]:
    """本地快照中已存在的事件 id，避免重复并入同一个事件。"""

    path = ROOT / "var" / "knowledge_graph" / "graph.json"
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = set()
    for node in payload.get("nodes") or []:
        if not isinstance(node, dict) or node.get("label") != "Event":
            continue
        props = node.get("props") or {}
        event_id = props.get("event_id") or str(node.get("id") or "").split(":", 1)[-1]
        if event_id:
            ids.add(str(event_id))
    return ids


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    historical = _select_bundles(discover_historical_events(args.events), args.event)
    attach_historical_metrics(historical, args.experiments)
    bundles = list(historical)

    legacy_count = 0
    if args.legacy_corpus:
        from pipelines.kg.legacy_corpus import build_bundles, load_legacy_events

        legacy = _select_bundles(build_bundles(load_legacy_events(args.legacy_corpus)), args.event)
        legacy_count = len(legacy)
        bundles.extend(legacy)

    store_count = 0
    if args.include_store:
        from pipelines.kg.event_store import discover_store_events

        exclude = {bundle.event_id for bundle in bundles} | _snapshot_event_ids()
        store = _select_bundles(
            discover_store_events(args.store_uri, args.store_db, exclude), args.event
        )
        store_count = len(store)
        bundles.extend(store)

    if not bundles:
        print(
            "没有找到可用事件（历史事件库需要 event_manifest.json / event_input.json / "
            "official_response_timeline.json / public_context_timeline.json / initial_opinion.json；"
            "历史语料需要 --legacy-corpus；MongoDB 事件需要 --include-store）。",
            file=sys.stderr,
        )
        return 1

    with_run = sum(1 for bundle in bundles if bundle.run_dir)
    print(
        f"[1/3] 事件：{len(bundles)} 个（历史复现 {len(historical)}，历史语料 {legacy_count}，"
        f"事件库 {store_count}；{with_run} 个挂载了历史复现批次指标）"
    )

    args.out.mkdir(parents=True, exist_ok=True)
    extractions_path = args.out / "extractions.json"

    mode = "llm" if args.llm else args.mode
    if mode == "auto":
        mode = "llm" if config_from_env() else "heuristic"
    if mode == "llm" and config_from_env() is None:
        print("      未检测到 KG_LLM_API_KEY / DEEPSEEK_API_KEY，回退规则抽取。")
        mode = "heuristic"

    if args.reuse and extractions_path.exists():
        extractions = json.loads(extractions_path.read_text(encoding="utf-8"))["events"]
        warnings: list[str] = ["复用已有抽取结果。"]
        print(f"[2/3] 复用 {extractions_path}（{len(extractions)} 个事件）")
    else:
        print(f"[2/3] 抽取（{mode}）…")
        extractions, warnings = extract_all(bundles, mode, args.out / "cache", args.refresh)
        if not args.no_keep_snapshot:
            snapshot = load_snapshot(ROOT / "var" / "knowledge_graph" / "graph.json")
            known = {item.get("event", {}).get("id") for item in extractions}
            restored = sorted(snapshot_event_ids(snapshot) - known)
            kept = 0
            for event_id in restored:
                extraction = extraction_from_snapshot(snapshot, event_id) if snapshot else None
                if extraction:
                    extractions.append(extraction)
                    kept += 1
            if kept:
                print(f"      保留本地快照事件 {kept} 个：{'、'.join(restored)}")
        extractions_path.write_text(
            json.dumps(
                {
                    "meta": {
                        "extraction_mode": mode,
                        "source_dir": str(args.events),
                        "event_count": len(extractions),
                    },
                    "events": extractions,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"      抽取完成：{extractions_path}")

    modes = {item.get("extraction_mode", "heuristic") for item in extractions}
    extraction_mode = modes.pop() if len(modes) == 1 else "mixed"

    snapshots = {bundle.event_id: build_snapshots(bundle) for bundle in bundles}
    sources = [str(args.events)]
    if args.legacy_corpus:
        sources.append(str(args.legacy_corpus))
    if args.include_store:
        sources.append(f"mongodb://{args.store_db}.events")
    if not args.no_keep_snapshot:
        sources.append("var/knowledge_graph/graph.json")
    meta = {
        "extraction_mode": extraction_mode,
        "source_dir": " | ".join(sources),
        "metrics_source": str(args.experiments) if with_run else "",
        "event_scope": (
            f"{len(extractions)} 个事件（历史复现 {len(historical)}、"
            f"历史语料 {legacy_count}、事件库 {store_count}）"
        ),
    }
    payload = write_graph_artifacts(extractions, snapshots, args.out, meta)
    print(
        f"[3/3] 建图完成：{payload['meta']['nodes']} 节点 / {payload['meta']['edges']} 关系"
        f" → {args.out}"
    )

    if not args.no_viz:
        write_html(payload, args.out / "graph.html")
        print(f"      可视化：{args.out / 'graph.html'}")

    for warning in warnings[:10]:
        print(f"      ! {warning}")
    if len(warnings) > 10:
        print(f"      ! 其余 {len(warnings) - 10} 条提示已省略")

    if args.load:
        from pipelines.kg.load import load_statements, verify

        statements = json.loads((args.out / "statements.json").read_text(encoding="utf-8"))
        executed = load_statements(
            statements, args.uri, args.user, args.password, args.database
        )
        print(f"[4/4] 已写入 Neo4j：{executed} 条语句（{args.uri}）")
        result = verify(args.uri, args.user, args.password, args.database)
        labels = ", ".join(f"{row['label']}={row['count']}" for row in result["labels"])
        rels = ", ".join(f"{row['type']}={row['count']}" for row in result["relationships"])
        print(f"      节点：{labels}")
        print(f"      关系：{rels}")
        for row in result["events"]:
            print(f"      {row['event']}：子事件 {row['sub_events']}，议题 {row['topics']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
