# Future 文档中心

本目录集中保存项目文档。设计文档迁移自旧仓库的 `demo/docs`，
代码路径已按本仓库的 `backend/app` 分层结构调整；`kg`、`comment_harvest`、
`persona_pipeline` 归入 `pipelines/`，`visualization` 归入 `legacy/`，
参考工程归入 `third_party/`。

## 目录结构

```text
docs/
├─ README.md     文档索引
├─ guides/       组件使用说明（backend、frontend、kg、comment_harvest、opinion_pool、persona_pipeline、参考工程）
├─ design/       架构、数据契约、接口与机制说明
├─ project/      交接教程、项目状态、变更与协作规范
└─ assets/       静态资产
   ├─ ppt/       研发汇报材料
   └─ screenshots/ 页面截图
```

## 项目说明

| 文档 | 内容 |
| --- | --- |
| [backend.md](guides/backend.md) | 后端分层结构、迁移对照、MongoDB、API、运行与测试 |
| [frontend.md](guides/frontend.md) | 前端路由、启动、代理与报告接口 |
| [kg.md](guides/kg.md) | 事件知识图谱抽取管线（`pipelines/kg/`） |
| [comment_harvest.md](guides/comment_harvest.md) | 事件评论采集 Agent：B 站检索、抓取、抽样与立场分析（`pipelines/comment_harvest/`） |
| [persona_pipeline.md](guides/persona_pipeline.md) | Persona 构建管线（`pipelines/persona_pipeline/`） |
| [opinion_pool.md](guides/opinion_pool.md) | 初始舆论池：生成式 / 采集式双来源、配置与成本 |
| [reference_projects.md](guides/reference_projects.md) | 参考工程说明（`third_party/`） |
| [../README.md](../README.md) | 仓库总览与快速开始 |

## 数据与资产

- `data/processed/personas/`：Persona 源文件目录；当前运行数据已迁入
  MongoDB，目录默认留空，仅作为历史源文件与回填入口；
- `data/historical_replay/`：历史事件库、真实趋势与对照数据；
- `data/legacy_corpus/`：旧事件语料表（`event.xlsx`），知识图谱管线可选用；
- `data/examples/`：结构样例；
- `var/experiments/`：实验批次（含从源仓库迁移的历史批次）；
- `var/state/`、`var/reports/`：运行状态与报告；
- `var/legacy/output/`：源仓库 `output/` 的日志与构建进度文件（Persona 画像
  已去重并迁入 MongoDB `future_simulation.personas`）；
- `docs/assets/ppt/`：研发汇报 PPT 与大纲；
- `docs/assets/screenshots/`：控制台、知识图谱、报告、设置等页面截图。

## 第一次接手

按以下顺序阅读：

1. [../README.md](../README.md)：仓库总览、目录和快速开始。
2. [backend.md](guides/backend.md) / [frontend.md](guides/frontend.md)：当前后端命令、存储、API 和前端启动。
3. [PROJECT_STATUS.md](project/PROJECT_STATUS.md)：当前已完成内容、验证边界、主要风险和下一步工作。
4. [ARCHITECTURE.md](design/ARCHITECTURE.md)：系统流程、代码地图、目录职责和依赖方向。
5. [DATA_CONTRACT.md](design/DATA_CONTRACT.md)：输入、状态、评论、传播和结果字段。
6. [SIMULATION_INTERFACE_SPEC.md](design/SIMULATION_INTERFACE_SPEC.md)：稳定入口、模块接口和禁止事项。

想了解 2026/10 的交接背景，可再读
[PROJECT_HANDOFF_20261022.md](project/PROJECT_HANDOFF_20261022.md)；该文档
写于 MongoDB、Neo4j 和单套前端接入之前，部分命令已被上面的当前文档替代。

## 专题文档

| 文档 | 适用场景 |
| --- | --- |
| [HISTORICAL_REPLAY.md](design/HISTORICAL_REPLAY.md) | 维护历史事件输入、时间线、Agent响应和真实趋势边界 |
| [VISUALIZATION.md](design/VISUALIZATION.md) | 维护方案对照、历史复现和共享网络页面（`legacy/visualization/`） |
| [LLM_SERVICE.md](design/LLM_SERVICE.md) | 检查DeepSeek调用位置、重试、费用和本地逻辑边界 |
| [GIT_WORKFLOW.md](project/GIT_WORKFLOW.md) | 分支、提交、审查和团队协作 |
| [WEB_API.md](design/WEB_API.md) | 会话接口、输入合并、逐轮控制与报告 |
| [CHANGE_SUMMARY.md](project/CHANGE_SUMMARY.md) | 2026/10 自定义策略与 Web 会话改造摘要 |

## 稳定入口

~~~powershell
# 回应方案对照实验（四种回应方案＋一组不回应基线）
# 运行前需填好全部四个方案公告，尤其是默认留空的 custom
py -3 backend/scripts/run_simulation.py

# 条件化历史复现
py -3 backend/scripts/run_historical_replay.py --event-id <event_id>

# 旧版只读可视化（历史复现、方案对照、共享网络；默认 127.0.0.1:8765）
# 新前端不再包含历史复现页，查看历史复现需要使用这个旧版入口
python legacy/visualization/app.py

# 知识图谱管线（读取 data/historical_replay/events 与 data/legacy_corpus，
# 产物在 pipelines/kg/out）
py pipelines/kg/pipeline.py

# Persona 构建（需要 MongoDB 与 DeepSeek Key）
py pipelines/persona_pipeline/build_personas.py --output-dir data/processed/personas
~~~

后端 API 服务：

~~~powershell
py -3 backend/scripts/run_api_server.py --port 8770
~~~

环境安装、API Key 设置与运行命令以 [backend.md](guides/backend.md)、
[frontend.md](guides/frontend.md) 为准；历史交接教程中的部分命令写在
MongoDB、Neo4j 和前端接入之前，已不再全部适用。本仓库的存储、目录和运行
差异见 [backend.md](guides/backend.md)。

## 文档维护规则

- 当前可执行命令以 `guides/backend.md`、`guides/frontend.md` 为准；
  交接教程保留历史流程，不再作为唯一命令来源；
- 当前完成状态只写在 PROJECT_STATUS.md；
- 代码职责和目录结构只写在 ARCHITECTURE.md 与 backend.md；
- 字段变化先更新 DATA_CONTRACT.md；
- 模块入口或依赖变化先更新 SIMULATION_INTERFACE_SPEC.md 和 ARCHITECTURE.md；
- 尚未实现的内容不得写成当前能力；需要启动新阶段时，应先重新评审并建立与代码同步维护的设计说明；
- 不再创建按日期累计的超长开发日志或逐次联调流水账；有效结果摘要写入 PROJECT_STATUS.md，原始证据保存在实验目录和 Git 历史；
- 文档不得包含 API Key、个人敏感数据或不必要的本机绝对路径。
