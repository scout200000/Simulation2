# 历史语料（知识图谱背景事件）

`event.xlsx` 来自 2026-10-15 交付包《数据整理与Github（2026.10.15前）系统Mongo版》的
`其他历史数据/event.xlsx`。Sheet1 共 60 个事件，字段为
`Title / Content / Year / Bilibili / Douyin`。

- **用途**：以「单阶段背景事件」并入事件知识图谱（`pipelines/kg/`），补充跨事件的议题、
  地点与来源；不作为历史复现输入。
- **同源未纳入**：`清洗评论的推理.xlsx`（44,809 条评论，约 13 MB）体积较大，未放入仓库；
  需要做议题归纳、评论生成评测或微调时，从原始交付包取用。
- **口径**：正文是二手叙述，没有官方通报时间线和真实趋势。入库事件统一
  `origin=legacy_corpus`，不生成 Claim / Snapshot，质疑与传闻类子事件标
  `discourse / unconfirmed`。

重新生成图谱：

```powershell
py pipelines/kg/pipeline.py --legacy-corpus data/legacy_corpus/event.xlsx --include-store
```
