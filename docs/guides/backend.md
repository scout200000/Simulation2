# Future 后端

多 Agent 社会舆情仿真后端。原 `backend/demo` 目录中的全部代码已按分层结构
迁入本目录，`demo` 目录不再保留；历史趋势复现代码也已从旧仓库的
`demo/historical_replay` 迁入 `app/historical_replay`。

本文档已集中到 `docs/`，文档索引见 [README.md](../README.md)；架构、数据契约、
历史复现等设计文档见 [ARCHITECTURE.md](../design/ARCHITECTURE.md)、
[DATA_CONTRACT.md](../design/DATA_CONTRACT.md)、[HISTORICAL_REPLAY.md](../design/HISTORICAL_REPLAY.md)。

## 目录结构

```text
backend/
├─ app/
│  ├─ api/                 HTTP 接口层
│  │  ├─ router.py         路由表与请求分发
│  │  ├─ responses.py      统一 JSON 响应构造
│  │  ├─ routes/           资源路由（health / inputs / sessions / reports / knowledge_graph）
│  │  └─ schemas/          请求体类型说明
│  ├─ application/         用例编排
│  │  ├─ experiment_runner.py   完整策略对照实验
│  │  ├─ session_service.py     逐轮会话控制、暂停、回滚、检查点、删除
│  │  ├─ session_facade.py      面向 Web 的会话门面
│  │  ├─ input_compat.py        事件/公告/进场时机的输入归一化
│  │  ├─ announcement_drafts.py 公告草稿批次校验与场景构造
│  │  ├─ knowledge_graph_service.py 知识图谱读取与兜底
│  │  ├─ knowledge_graph_sync.py    策略运行后的图谱同步
│  │  ├─ batch_manager.py       实验批次目录与快照
│  │  ├─ state_manager.py       状态目录初始化与校验
│  │  ├─ experiment_audit.py    场景隔离与共同输入指纹审计
│  │  ├─ step_executor.py       单轮仿真子进程协议
│  │  ├─ scenario_state.py / round_results.py / runtime_config.py
│  ├─ domain/             稳定领域规则
│  │  ├─ contracts.py           仿真上下文与决策契约
│  │  ├─ comment_semantics.py   评论语义归一化
│  │  ├─ events/                事件输入、事件状态
│  │  ├─ knowledge_graph/       事件图谱视图与关联推导
│  │  └─ strategies/            策略证据强度规则
│  ├─ infrastructure/     外部设施
│  │  ├─ database/        MongoDB 连接、索引与 Persona/网络/事件仓储
│  │  ├─ graph/           Neo4j HTTP Cypher 仓储
│  │  ├─ storage/json_storage.py  JSON/JSONL 兼容镜像与运行产物
│  │  └─ llm/llm_service.py     DeepSeek 请求、重试与统计
│  ├─ agents/             Agent 感知、认知决策与状态
│  ├─ comments/           评论角度、生成、舆论池与采集
│  ├─ simulation/         固定社交网络、传播采样、单轮执行
│  ├─ evaluation/         指标计算、报告 JSON 与 PDF 生成
│  ├─ historical_replay/  历史事件仓库、时间线、公众语境与连续回放
│  ├─ main/               配置、异常、日志与启动入口
│  │  ├─ config/settings.py     全部路径与运行参数
│  │  ├─ exceptions/            业务异常到 HTTP 状态码的映射
│  │  ├─ middleware/            访问日志
│  │  ├─ api_server.py          JSON API 服务
│  │  └─ cli.py                 完整仿真入口
│  └─ shared/utils/       跨层小工具
├─ workers/               后台/子进程入口
│  ├─ simulation_tasks/run_step.py   单轮仿真子进程（被实验编排器调用）
│  └─ graph_tasks/、strategy_tasks/  预留入口（当前只有包初始化）
├─ strategies/            回应策略
│  ├─ base/               方案稳定结构
│  └─ registry/           方案数量、声明状态、证据维度与校验
├─ scripts/               运维命令行入口（含图谱导入、采集试跑、修复）
└─ tests/unit/            规则回归测试

仓库根目录的 requirements.txt 提供统一运行依赖。
```

## 迁移对照

| 迁移前（demo/） | 迁移后（本仓库） |
| --- | --- |
| demo/main.py | app/main/cli.py + backend/scripts/run_simulation.py |
| demo/api_server.py | app/main/api_server.py + app/api/ |
| demo/project_config.py | app/main/config/settings.py |
| demo/experiment_runner.py | app/application/experiment_runner.py |
| demo/web_control.py | app/application/session_service.py |
| demo/web_api.py | app/application/session_facade.py |
| demo/web_compat.py | app/application/input_compat.py |
| demo/simulation/batch_manager.py | app/application/batch_manager.py |
| demo/simulation/state_manager.py | app/application/state_manager.py |
| demo/simulation/counterfactual_controls.py | app/application/experiment_audit.py |
| demo/application/round_results.py 等 | app/application/round_results.py 等 |
| demo/application/error_summary.py | app/shared/utils/error_summary.py |
| demo/simulation/event_context.py | app/domain/events/context.py |
| demo/simulation/event_state_updater.py | app/domain/events/state.py |
| demo/simulation/evidence_policy.py | app/domain/strategies/evidence.py |
| demo/infrastructure/json_storage.py | app/infrastructure/storage/json_storage.py |
| demo/infrastructure/llm_service.py | app/infrastructure/llm/llm_service.py |
| demo/agents/* | app/agents/* |
| demo/comments/* | app/comments/* |
| demo/simulation/{options,social_network,propagation,propagation_tracking,context_exposure,runner}.py | app/simulation/ |
| demo/evaluation/* | app/evaluation/* |
| demo/historical_replay/*.py | app/historical_replay/*.py |
| demo/historical_replay/events/* | data/historical_replay/events/* |
| demo/historical_replay/active_event.json | configs/events/active_event.json |
| demo/config/comment_profiles.json | configs/comment_profiles.json |
| demo/config/social_network_config.json | MongoDB `social_networks`（`kind=config`，源文件已清理） |
| demo/event_example.json | MongoDB `events`（默认事件，源文件已清理） |
| demo/official_response_options.json | configs/strategies/official_response_options.json |
| demo/example/* | data/examples/* |
| demo/docs/*.md | docs/*.md |
| python -m simulation.runner | python -m workers.simulation_tasks.run_step |

迁移过程中同步做了以下调整：

- 全部模块改为以 app. / strategies. / workers. 开头的绝对导入；
- HTTP 报文处理与业务逻辑拆分，api_server 只负责读写、分发和错误映射；
- 策略方案的数量、状态、证据维度与校验从 experiment_runner 抽取到
  strategies/registry；
- 单轮子进程入口移入 workers，实验编排器通过 -m 调用；
- 历史复现模块移入 app/historical_replay，事件资料移入
  data/historical_replay，当前事件指针移入 configs/events；
- 设计文档集中到 docs/，组件 README 只保留指向文档中心的链接；
- 配置目录改为 configs/，示例数据改为 data/examples/，运行状态默认
  写入 var/state/，实验批次写入 var/experiments/，报告写入
  var/reports/。

补充迁移（2026/11/03，旧仓库 `Simulation2-main` 其余内容）：

| 迁移前 | 迁移后 |
| --- | --- |
| `demo/docs/*.md` | `docs/*.md`（另见 `docs/guides/kg.md`、`docs/guides/persona_pipeline.md`） |
| `demo/experiments/*`（历史批次） | `var/experiments/*` |
| `demo/state/.gitkeep` | `var/state/.gitkeep` |
| `data/reports/*.json` | `var/reports/*.json` |
| `output/`（日志、进度与备份；Persona 画像已存在） | `var/legacy/output/` |
| `demo/ppt_assets/` | `docs/assets/ppt/` |
| `kg/` | `pipelines/kg/`（默认输入改为 data/、var/ 路径） |
| `persona_pipeline/` | `pipelines/persona_pipeline/`（默认输出改为 data/processed/personas） |
| `visualization/` | `legacy/visualization/`（默认输入改为 data/、var/、configs/ 路径） |
| `other/` | `third_party/`（参考工程，不参与运行） |

## 运行

所有命令默认在仓库根目录执行。

```powershell
# 依赖
py -3 -m pip install -r requirements.txt

# 本地 MongoDB（数据目录 .data/mongodb，日志 .data/mongodb-log）
py -3 backend/scripts/start_mongodb.py

# 单文件备份/恢复（清理源 JSON 后用于重建数据库）
py -3 backend/scripts/backup_mongodb.py
py -3 backend/scripts/backup_mongodb.py --restore data/backups/future_simulation.json

# 源 JSON 存在时导入；不存在时自动从备份恢复
py -3 backend/scripts/seed_mongodb.py

# JSON API（前端默认代理 http://127.0.0.1:8770）
py -3 backend/scripts/run_api_server.py --host 127.0.0.1 --port 8770

# 完整仿真实验（需要 DEEPSEEK_API_KEY）
# 运行前必须填好 4 个回应方案的公告；custom 默认为空，strict 校验会直接报错
py -3 backend/scripts/run_simulation.py

# 运行当前时间步
py -3 backend/scripts/run_simulation_step.py --max-agents 30 --workers 5

# 历史趋势复现（需要 DEEPSEEK_API_KEY）
py -3 backend/scripts/run_historical_replay.py --list-events
py -3 backend/scripts/run_historical_replay.py --event-id event_huxinyu_2022_001
```

`start_mongodb.py` 支持 `--status` 查看状态、`--stop` 停止本地实例。生产环境
可直接使用 Windows 服务或容器，并通过 `MONGO_URI` 指向对应实例。

如果本机已把 MongoDB 注册为 Windows 服务（通常自动启动），直接使用该服务
即可。`start_mongodb.py` 只用于服务未启动或未安装时，以 `.data/mongodb`
启动项目内临时实例；两者不能同时占用 27017。服务的数据目录由安装时配置，
不在本仓库内。

也可以使用模块方式运行（工作目录为 `backend`）：

```powershell
python -m app.main.api_server
python -m app.simulation.runner
python -m app.historical_replay.main
python -m workers.simulation_tasks.run_step
```

## MongoDB 存储

Persona、关系网络与事件记录以 MongoDB 为唯一数据源。2026/11/03 已清理
132 个已入库的源 JSON/镜像文件：54 个 Persona、`policy_config.json`、网络
配置与 21 个网络快照、默认事件与 11 个批次事件输入、43 个事件状态历史
（这是清理当天的口径；当前文档数会随实验增加，以 `/api/health` 的
`storage.collections` 为准）。当前只保留一个可提交的备份文件：
`data/backups/future_simulation.json`。

默认数据库：`future_simulation`（`MONGO_DATABASE` 可改）。

| 集合 | 内容 | 主键/索引 |
| --- | --- | --- |
| `personas` | Persona 完整人物画像 | `_id=agent_id`，`agent_id` 唯一 |
| `persona_policies` | 全局分位数与候选规则 | `_id=policy` |
| `social_networks` | 网络配置（`kind=config`）与固定关注网络快照（`kind=snapshot`） | `_id=文件作用域`，`network_id` 内容哈希 |
| `events` | 默认事件与各实验批次的事件输入 | `_id=文件作用域`，`event_id` 索引 |
| `event_states` | 逐轮官方声明与客观事件状态 | `(scope, event_id, step)` 唯一 |

“文件作用域”是项目内相对路径（例如
`var/experiments/<批次>/social_network_snapshot.json`）。即使对应 JSON 已
删除，作用域仍保留，用于区分共享基线、各策略场景和回滚检查点。
复制/回滚/删除状态目录时，
`app/infrastructure/database/repositories/state_scope.py` 会同步复制或清理
MongoDB 文档。

以下数据**没有**迁移到 MongoDB，仍保留为文件：评论池、Agent 决策、Agent
状态、增量评论、指标、传播记录、实验控制与结果、报告 JSON/PDF，以及
`data/examples` 示例数据和 `data/historical_replay` 历史复现输入。知识图谱
运行时以 Neo4j 为主存储，`var/knowledge_graph/graph.json` 只是本地兜底
快照；图谱本身不属于 MongoDB 受管集合。

### 备份与恢复

```powershell
# 导出全部受管集合到 data/backups/future_simulation.json
py -3 backend/scripts/backup_mongodb.py

# 从备份恢复（合并）
py -3 backend/scripts/backup_mongodb.py --restore data/backups/future_simulation.json

# 清空受管集合后从备份恢复
py -3 backend/scripts/seed_mongodb.py --from-backup --reset

# 源 JSON 不存在时，seed_mongodb.py 会自动改用备份
py -3 backend/scripts/seed_mongodb.py
```

`GET /api/health` 的 `storage` 字段会返回当前后端、数据库、连接状态和各集合
文档数。若 MongoDB 未启动，默认会报出明确连接错误；设置
`SIMULATION_STORAGE_BACKEND=json` 可临时退回纯文件存储（需要源 JSON 存在）。
`MONGO_WRITE_JSON_MIRROR` 默认关闭；仅在需要与旧文件流程对照时才设置
`true`，正常 MongoDB 单存储模式不要开启。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/input/defaults` | 默认事件、公告方案与策略清单 |
| POST | `/api/input/preview` | 合并并校验一次实验输入 |
| GET | `/api/sessions` | 会话列表 |
| POST | `/api/sessions` | 创建会话（201） |
| GET | `/api/sessions/{id}` | 会话快照与状态 |
| DELETE | `/api/sessions/{id}` | 删除会话目录与对应 MongoDB 状态文档 |
| POST | `/api/sessions/{id}/{action}` | `start` / `step` / `continue` / `pause` / `resume` / `rollback` / `restart` / `run` / `announcement` |
| GET | `/api/sessions/{id}/report` | 报告状态 |
| POST | `/api/sessions/{id}/report` | 触发生成报告（202） |
| GET | `/api/sessions/{id}/report.pdf` | 下载已生成报告的 PDF |
| GET | `/api/knowledge-graph` | 历史事件知识图谱（事件、共享实体与事件关联） |

业务异常统一由 `app.main.exceptions.resolve_http_error` 映射：`FileNotFoundError`
→ 404，`ValueError` / `KeyError` / `TypeError` / JSON 解析错误 → 400，其余 → 500。

## 配置

- `configs/comment_profiles.json`：评论人物类型模板与派系配置；
- `configs/events/active_event.json`：历史复现默认事件指针；
- `configs/strategies/official_response_options.json`：4 个回应方案
  （`response_plan_1`～`response_plan_3` 与 `custom`）；
- `configs/opinion_pool.json`：初始舆论池来源（`generate` / `harvest`）与参数；
- `configs/neo4j.json`：可选的 Neo4j 凭据文件路径；该文件是本机配置，
  不要把个人绝对路径或凭据提交到共享仓库；
- `data/backups/future_simulation.json`：Persona、网络配置、事件输入与事件
  状态的单文件备份；源 JSON 已清理，默认从该文件恢复；
- `data/historical_replay/events/<event_id>/`：历史事件资料（输入、时间线、
  初始观点、公众语境与真实趋势源）；
- `data/historical_replay/real_trends/`：由真实趋势源生成的对照数据。

Persona、默认事件和固定网络参数已迁入 MongoDB，不再以
`data/processed/personas/*.json`、`configs/events/event_example.json`、
`configs/social_network_config.json` 作为运行数据源。修改这些数据时应直接
更新 MongoDB，或恢复/更新备份后执行 `seed_mongodb.py --from-backup`。

可通过环境变量覆盖运行位置与模型配置：

```text
SIMULATION_STATE_DIR / SIMULATION_EXPERIMENT_DIR / SIMULATION_REPORT_DIR
SIMULATION_EVENT_FILE / SIMULATION_COMMENT_POOL_FILE / SIMULATION_SOCIAL_NETWORK_FILE
SIMULATION_RANDOM_SEED / SIMULATION_COMMENT_TEMPERATURE
OPINION_POOL_SOURCE
DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_ENDPOINT
KG_GRAPH_FILE
KG_NEO4J_ENABLED / NEO4J_HTTP_URL / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE / NEO4J_TIMEOUT
NEO4J_CREDENTIALS_FILE / NEO4J_QUERY_API
SIMULATION_STORAGE_BACKEND / MONGO_URI / MONGO_DATABASE
MONGO_SERVER_SELECTION_TIMEOUT_MS / MONGO_WRITE_JSON_MIRROR
```

`KG_GRAPH_FILE` 默认指向 `var/knowledge_graph/graph.json`，也可改为
`pipelines/kg/out/graph.json`（仓库内知识图谱管线的最新产物），接口会按文件修改时间
自动重新加载。

### DeepSeek 密钥

`DEEPSEEK_API_KEY` 在每次模型调用时解析，优先级：

1. 进程环境变量（启动后端/脚本的终端）；
2. Windows 用户变量（`HKCU\Environment`）；
3. Windows 机器变量。

Windows 用户变量是写入注册表的，**只对之后新启动的进程生效**；已经打开的
终端、DSH/IDE 或后端进程不会自动刷新环境。旧代码只在启动时读取一次，因此会
出现“用户变量已设置但仍提示未设置”的情况；现在改为调用时解析用户变量，
无需重启后端即可生效。

排查接口：

```powershell
curl http://127.0.0.1:8770/api/health
# llm.deepseek_configured = true
# llm.deepseek_key_source = process / user / machine / none
```

接口只返回来源，不返回 Key 本身。若来源是 `none`，说明当前账号下没有读到
变量；可在启动后端的终端显式设置：

```powershell
$env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable("DEEPSEEK_API_KEY", "User")
py -3 backend/scripts/run_api_server.py
```

## 历史趋势复现

历史复现由独立入口驱动，不经过动态进场和回应方案对照：

- 入口：`app/historical_replay/main.py`，脚本为
  `backend/scripts/run_historical_replay.py`；
- 事件仓库：`data/historical_replay/events/<event_id>/`，包含
  `event_input.json`、`official_response_timeline.json`、
  `initial_opinion.json`、`public_context_timeline.json`、
  `event_manifest.json` 和真实趋势源；
- 当前事件指针：`configs/events/active_event.json`；
- 每次运行在 `var/experiments/<event_id>_<timestamp>/` 新建批次，
  写入 `historical_replay_result.json`；新批次另有 `run_manifest.json`，
  旧批次可能没有该文件；
- 真实趋势对照数据：`data/historical_replay/real_trends/`。

设计说明见 [HISTORICAL_REPLAY.md](../design/HISTORICAL_REPLAY.md)。

## 测试

```powershell
cd backend
py -3 -m unittest discover -s tests/unit -t .

# Persona 管线（4 项）
cd pipelines/persona_pipeline
py -3 -m unittest discover -s tests -t tests

# 旧版只读可视化（22 项，4 项按可选旧实验目录跳过）
py -3 -m unittest discover -s legacy/visualization/tests -t .
```

当前 `backend/tests/unit` 共 247 项，测试只使用离线规则与 mock，不会访问
DeepSeek；文件型用例需要可写的临时目录。`requests` 为运行依赖，缺失时
LLM 相关模块无法导入。legacy 的旧批次兼容用例依赖 `var/experiments` 中
早期批次的网络快照文件；如果对应文件已清理、只剩 MongoDB 文档，该用例会
因找不到文件而失败，属于测试数据依赖问题，不是可视化服务启动失败。

## 目录约定

- `backend/`：全部可导入代码与测试；
- `configs/`：可部署配置（事件指针、策略、评论模板、舆论池、Neo4j）；
- `data/`：输入数据（历史事件、历史语料、样例、备份），可提交；
- `var/`：运行产物（`state/`、`experiments/`、`reports/`、
  `knowledge_graph/`、`legacy/`），不应提交；
- `docs/`：文档中心；`pipelines/`、`legacy/`、`third_party/` 为独立组件。

原骨架中预留的空目录（`api/routes/data_sources`、`shared/{constants,enums,types}`、
`workers/collectors`、`tests/{e2e,integration,...}` 等）已清理。`application/`
下已有 `announcement_drafts.py`、`knowledge_graph_service.py` 等实际服务，
`infrastructure/graph/` 也已接入 Neo4j 仓储；`workers/graph_tasks/` 与
`workers/strategy_tasks/` 目前只保留包初始化，尚未接入任务。新增能力时直接
在对应包内创建，不再保留无实现的空占位。

## 历史事件知识图谱

图谱本体与抽取由仓库根目录的 `pipelines/kg/` 管线实现（详见 [kg.md](kg.md)）：该管线
从历史复现事件库（`data/historical_replay/events`）、旧事件语料
（`data/legacy_corpus/event.xlsx`，可选）与实验批次（`var/experiments`）抽取
事件要素，生成 `pipelines/kg/out/graph.json`
（Event / SubEvent / Phase / Topic / Location / Actor / Cause / Consequence /
Claim / Source / Snapshot，共 11 类节点）。

### 存储：Neo4j 优先，JSON 兜底

- **Neo4j 主存储**：`GET /api/knowledge-graph` 优先从 Neo4j 读取整张事件图；
- **自动初始化/补录**：Neo4j 可用时，后端把 `KG_GRAPH_FILE` 中尚未进入
  Neo4j 的事件 MERGE 进去（可重复执行），首次打开页面即可看到已有事件；
- **本地快照兜底**：Neo4j 未启动时回退到 `var/knowledge_graph/graph.json`，
  页面顶部显示「本地快照」；Neo4j 正常时显示「Neo4j 图数据库」。
- **事件不会丢**：策略运行结束时先写本地快照；Neo4j 可用再写图数据库。
  Neo4j 恢复后，后端会把本地快照中尚不存在于图数据库的事件自动补录。

Neo4j 通过 HTTP 访问，不需要 `neo4j` Python 驱动。本地 Neo4j 使用
事务接口（`/db/{db}/tx/commit`），**Neo4j Aura 使用 Query API**
（`/db/{db}/query/v2`），后端会根据 URL 是否以 `https://` 开头自动选择，
也可以用 `NEO4J_QUERY_API=1/0` 强制。

```powershell
# 方式 A：本地 Neo4j 5.26（仓库自带 compose）
docker compose -f pipelines/kg/docker-compose.yml up -d
py -3 backend/scripts/run_api_server.py

# 方式 B：Neo4j Aura（云端 Free 实例）
# 把 Aura 下载的 Neo4j-xxxx.txt 凭据文件路径传给后端；
# 后端会读取其中的 URI / USERNAME / PASSWORD / DATABASE。
$env:NEO4J_CREDENTIALS_FILE = "C:\path\to\Neo4j-xxxx.txt"
$env:NEO4J_TIMEOUT = "30"
py -3 backend/scripts/run_api_server.py
```

```text
# 本地 Neo4j
NEO4J_HTTP_URL=http://127.0.0.1:7474
NEO4J_USER=neo4j
NEO4J_PASSWORD=eventkg123
NEO4J_DATABASE=neo4j
# 云端 Aura（优先于上面的手工配置；文件里包含 URI/USERNAME/PASSWORD/DATABASE）
NEO4J_CREDENTIALS_FILE=C:\path\to\Neo4j-xxxx.txt
NEO4J_QUERY_API=1            # 可留空自动判断；Aura 必须为 Query API
NEO4J_TIMEOUT=30             # Aura 冷启动/批量写入可能超过 5 秒
KG_NEO4J_ENABLED=1           # 0/false 关闭 Neo4j，强制走 JSON 快照
KG_GRAPH_FILE=var/knowledge_graph/graph.json
```

也可以把凭据文件路径写进 `configs/neo4j.json`（`{"credentials_file": "..."}`），
这样以后重启后端不需要再设环境变量；环境变量优先级更高。

手动导入/刷新历史事件：

```powershell
py -3 backend/scripts/seed_knowledge_graph.py
py -3 backend/scripts/seed_knowledge_graph.py --file pipelines/kg/out/graph.json

# 把已完成的策略会话补录到图谱（Neo4j 不可用时写入本地快照）
py -3 backend/scripts/sync_knowledge_graph.py
```

### 策略运行后自动入库

每次策略会话运行完成（单方案跑到 `completed`，或全部策略/全部草稿 `run` 结束）后，
`session_service` 会调用 `knowledge_graph_sync.sync_event_after_run`：

1. 从会话读取事件材料：优先本地 `event_input.json`，文件不存在时从
   MongoDB 读取（`MONGO_WRITE_JSON_MIRROR=0` 时事件只在 MongoDB 中）；
2. 用 `pipelines/kg` 的规则抽取，把事件正文、公告时间线/所选方案、
   `comment_pool.json` 的讨论角度生成事件子图，先合并进本地快照
   `KG_GRAPH_FILE`（按 event_id 替换该事件的旧子图，保留共享实体）；
3. Neo4j 可用时，`MATCH (e:Event {event_id})` 判断事件是否已存在：
   已存在则跳过；新事件则以 `MERGE` 写入，`Actor / Topic / Location` 等
   实体全局复用，自动建立跨事件关联；
4. 同步结果写入会话控制文件的 `knowledge_graph` 字段，并随
   `GET /api/sessions/{id}` 返回（`added / exists / stored_locally / failed`）。

Neo4j 不可用时返回 `stored_locally`，事件仍能在页面「本地快照」模式看到，
不会中断仿真；Neo4j 恢复后本地快照中的缺失事件会自动补录。策略运行事件
默认使用规则抽取（不调用大模型），也不会生成历史复现批次的阶段快照。

前端只提交事件正文时，若正文与默认事件不同，后端会按正文哈希生成
`event_custom_<hash>` 作为新 `event_id`：同一正文重复运行复用同一事件，
修改正文即视为新事件，避免知识图谱把新事件误判为旧事件而跳过。

相关模块：

- `app/infrastructure/graph/neo4j_repository.py`：HTTP Cypher、MERGE、读取图；
- `app/application/knowledge_graph_service.py`：Neo4j 优先读取、自动初始化、兜底；
- `app/application/knowledge_graph_sync.py`：事件判定、抽取、入库；
- `app/domain/knowledge_graph`：事件视图与事件—事件关联推导；
- `app/api/routes/knowledge_graph`：`GET /api/knowledge-graph`。

