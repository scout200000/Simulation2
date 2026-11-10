# Simulation2 Web API 文档

本文描述当前面向未来 web 页面提供的 Python API 层，并附带一个纯标准库
HTTP 路由服务；后端也可直接调用这些函数或在此基础上增加生产路由。

> **适配状态（2026-11-10）**：机制侧是"1 个不回应基线 + 4 个回应方案"
> （`RESPONSE_PLAN_COUNT = 4`）：事实通报、共情安抚、辟谣澄清三个预置方案，
> 外加一个 `custom` 自定义方案槽位。`custom` 的公告默认为空，由前端填写；
> 其余三个方案由 `configs/strategies/official_response_options.json` 预填。
> 输入层、逐轮驱动、回滚、追加公告、公告草稿批次与重启已实测通过；下文表格中
> 出现的旧策略编号（`fact_report` 等）仅适用于五策略时期的历史批次。
>
> **公告填写规则**：默认公告只由 `/api/input/defaults` 提供给前端预填，创建时
> 不会静默回填。任何方案（含 `custom`）公告留空即视为"未填写"，以空正文 +
> `none` 状态占位：单方案会话启动时直接标记 `not_run`（不生成评论池、不调用
> 模型），不会产生任何输出；"全部策略"模式要求所有方案都已填写。

## 默认数据文件

| 输入 | 默认来源 |
| --- | --- |
| 事件 | MongoDB `future_simulation.events`（默认事件文档，备份见 `data/backups/future_simulation.json`） |
| 官方公告策略 | `configs/strategies/official_response_options.json` |
| 策略选择 | `content_strategies` + 系统内置的 `no_response` |

所有输入都先加载默认数据，再由 web 输入按字段覆盖并进入既有校验。

## 输入 API

### 1. 事件 web 输入

```python
# 工作目录为 backend，或先把 backend 加入 PYTHONPATH
from app.application.session_facade import get_event_web_default, apply_event_web_input

default_event = get_event_web_default()
event = apply_event_web_input({
    "event_content": "网页填写的事件正文",
    "event_labels": {"event_valence": "negative"}
})
```

规则：

- 不传 `web_event_input` 时完全使用默认事件。
- 只传 `event_content` 时沿用默认 `event_id` 与未覆盖标签。
- `event_labels` 浅层合并。
- 提供与默认不同的 `event_id` 时必须同时提供 `event_content`。

### 2. 公告内容 web 输入

```python
from app.application.session_facade import (
    get_official_content_web_default,
    prepare_web_inputs,
)

default_options = get_official_content_web_default()
inputs = prepare_web_inputs(
    web_event_input=None,
    official_content_input={
        "custom": {
            "official_statement": "网页公告内容",
            "official_statement_status": "clear"
        }
    }
)
```

`official_content_input` 只接受**以 `strategy_id` 为键的映射**，例如
`{"custom": {...}, "response_plan_1": {...}}`；不是列表，也不接受完整的
`{"content_strategies": [...]}` 结构。每个键必须是当前事件已有的方案编号，
值只允许覆盖 `strategy_name`、`official_statement`、
`official_statement_status` 和 `evidence_dimensions`。未覆盖的策略保留
默认 JSON 内容；未知方案、不可覆盖字段或非法状态会直接抛出 `ValueError`。

### 3. 策略选择 web 输入

```python
from app.application.session_facade import (
    list_strategy_web_options,
    apply_strategy_web_input,
)

options = list_strategy_web_options()
selection = apply_strategy_web_input("custom")
```

返回的策略项：

```json
{
  "strategy_id": "custom",
  "strategy_name": "自定义",
  "custom": true,
  "ready": false
}
```

`ready=false` 表示 custom 尚未填写公告，web 端不应允许启动该策略会话。

## HTTP 服务

```powershell
py -3 backend/scripts/run_api_server.py --host 127.0.0.1 --port 8770
```

默认地址为 `http://127.0.0.1:8770`。HTTP 服务只提供后端 JSON API；同仓库的
`frontend/` 是 Vue 3 控制台，开发时由 Vite 代理 `/api`，生产部署时需要把
静态文件和 API 放在同一来源，或在反向代理上配置 `/api` 转发（服务本身未
内置 CORS 头）。

以下为创建会话的 JSON 请求体：

```json
{
  "web_event_input": {
    "event_content": "网页事件正文"
  },
  "official_content_input": {
    "custom": {
      "official_statement": "网页公告内容",
      "official_statement_status": "clear"
    }
  },
  "selected_strategy_id": "custom"
}
```

创建请求还支持以下可选字段：

- `entry_timing_input`：`{"mode": "dynamic"}` 或
  `{"mode": "fixed_round", "round": 3}`；
- `announcement_timeline_input`：预先安排任意轮次的公告，不能与
  `__all__` 模式同时使用；
- `announcement_drafts_input`：公告草稿批次，见下一节；
- `opinion_pool_config`：初始舆论池来源，例如
  `{"source": "generate"}` 或 `{"source": "harvest", "harvest": {...}}`，
  未提供时读取 `configs/opinion_pool.json`。

公告草稿批次在创建请求中额外携带 `announcement_drafts_input`。每条草稿绑定
一个回应方案，后端把每条草稿构造成一个独立场景（`draft_1`、`draft_2`……），
共享同一份进场前基线，并与“不回应”基线一起比较：
```json
{
  "announcement_drafts_input": [
    {
      "draft_id": "announcement-2",
      "strategy_id": "custom",
      "official_statement": "第一条自定义公告",
      "official_statement_status": "clear"
    },
    {
      "draft_id": "announcement-3",
      "strategy_id": "response_plan_1",
      "official_statement": "第二条事实通报公告",
      "official_statement_status": "incomplete"
    }
  ],
  "selected_strategy_id": "custom"
}
```

`selected_strategy_id` 在草稿批次中会被忽略并写为 `__drafts__`；草稿不能与
`__all__` 同时提交。创建后调用 `POST /api/sessions/{id}/run` 依次执行全部
草稿。响应中的 `mode` 为 `drafts`，并返回 `drafts` 与 `draft_count`。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 服务与存储状态（MongoDB、Neo4j、DeepSeek Key 来源） |
| GET | `/api/input/defaults` | 返回事件、公告与可选策略默认值 |
| POST | `/api/input/preview` | 校验事件/公告 web 输入并返回解析结果 |
| GET | `/api/sessions` | 列出所有 web 控制会话（当前返回完整快照） |
| POST | `/api/sessions` | 创建会话（201） |
| GET | `/api/sessions/{experiment_id}` | 查询会话状态 |
| DELETE | `/api/sessions/{experiment_id}` | 删除会话目录与对应 MongoDB 状态文档 |
| POST | `/api/sessions/{id}/start` | 启动并准备初始评论池 |
| POST | `/api/sessions/{id}/step` | 执行一个时间步 |
| POST | `/api/sessions/{id}/continue` | 清空暂停并执行一个时间步 |
| POST | `/api/sessions/{id}/pause` | 暂停 |
| POST | `/api/sessions/{id}/resume` | 继续（不自动推进） |
| POST | `/api/sessions/{id}/rollback` | 回滚，body 可传 `{"steps": 1}` |
| POST | `/api/sessions/{id}/restart` | 创建同输入的新批次 |
| POST | `/api/sessions/{id}/run` | 串行执行全部策略或全部公告草稿 |
| POST | `/api/sessions/{id}/announcement` | 暂停时向指定轮次追加公告 |
| GET | `/api/sessions/{id}/report` | 报告状态（`missing / generating / ready / failed`） |
| POST | `/api/sessions/{id}/report` | 后台生成报告（202） |
| GET | `/api/sessions/{id}/report.pdf` | 下载已生成的 PDF 报告 |
| GET | `/api/knowledge-graph` | 事件知识图谱（Neo4j 优先，本地快照兜底） |

## 会话控制 API

控制粒度为单策略、全部策略或全部公告草稿。会话由 `web_control.json`
记录在 `var/experiments/<experiment_id>/` 下。

| 函数 | 行为 |
| --- | --- |
| `create_web_experiment(...)` | 创建不可覆盖批次并写入控制文件，不调用 LLM；可同时保存公告草稿与初始舆论池配置 |
| `start_web_experiment(experiment_id)` | 生成初始评论池并进入对应策略的首轮运行状态 |
| `step_web_experiment(experiment_id)` | 执行一个时间步，执行后自动暂停 |
| `continue_web_experiment(experiment_id)` | 清空暂停并执行一个时间步 |
| `pause_web_experiment(experiment_id)` | 设置暂停，阻止下一次推进 |
| `resume_web_experiment(experiment_id)` | 仅清除暂停，不自动推进 |
| `rollback_web_experiment(experiment_id, steps=1)` | 回滚到最近完成步之前的检查点 |
| `restart_web_experiment(experiment_id)` | 用相同输入创建新的实验批次 |
| `add_web_announcement(experiment_id, round_no, official_statement, official_statement_status)` | 暂停时追加或替换指定轮次公告 |
| `run_all_web_experiment(experiment_id)` | 串行执行全部策略（`all`）或全部公告草稿（`drafts`） |
| `delete_web_experiment(experiment_id)` | 删除会话目录并清理对应 MongoDB 状态文档 |
| `get_web_experiment_status(experiment_id)` | 查询状态、进度与场景结果 |
| `list_web_experiments()` | 列出所有带控制文件的会话 |
| `get_session_report(experiment_id)` | 读取报告状态（`missing / generating / ready / failed`） |
| `generate_session_report(experiment_id)` | 在后台线程生成报告并返回当前状态 |

### 典型调用顺序

```python
from app.application.session_facade import (
    apply_event_web_input,
    apply_strategy_web_input,
    continue_web_experiment,
    create_web_experiment,
    pause_web_experiment,
    rollback_web_experiment,
    start_web_experiment,
)

event = apply_event_web_input({"event_content": "事件正文"})
selection = apply_strategy_web_input("response_plan_1")

session = create_web_experiment(
    web_event_input=event,
    official_content_input=None,
    selected_strategy_id=selection["strategy_id"],
)
experiment_id = session["experiment_id"]

start_web_experiment(experiment_id)
continue_web_experiment(experiment_id)   # 第1轮，结束后暂停
continue_web_experiment(experiment_id)   # 第2轮或进场后策略轮
pause_web_experiment(experiment_id)
rollback_web_experiment(experiment_id, steps=1)
```

### 控制语义

- `create` 只创建事件/公告/策略快照，不生成评论池。
- `start` 生成初始评论池并创建 `_shared_baseline` 状态。
- 不回应策略不创建进场前基线，直接从第 1 轮运行控制场景。
- 固定轮次/公告时间线模式不创建基线，直接从第 1 轮运行所选策略，并按时间线
  在指定轮次发布公告。
- `step`/`continue` 每次最多执行一个时间步；步骤完成后 `paused=true`。
- 暂停与继续只发生在轮次边界；不能中止一个正在同步执行的单轮。
- `rollback` 恢复该步开始前的检查点；回滚跨越基线/场景边界时会清理旧的
  策略状态目录并删除过期的 `scenario_result.json`。
- `restart` 保留旧批次不可覆盖，新建一个同输入批次；若旧批次已有初始评论池，
  会复制该评论池以降低 LLM 成本。前端在重启成功后同步更新 URL 哈希，
  刷新页面仍打开新批次。
- 会话暂停时可通过 `add_web_announcement()` 或
  `POST /api/sessions/{id}/announcement` 添加/替换任意轮次的公告。

## 公告草稿批次

- 每条草稿只绑定一个已有回应方案，继承该方案的 `evidence_dimensions` 和
  方案名；场景编号固定为 `draft_<序号>`，显示名为“方案名 · 草稿N”。
- 草稿批次与“全部策略”一样先跑一次共享基线和不回应场景，再串行跑每条草稿；
  不并发执行。
- 单批最多 20 条草稿；公告正文为空或状态为 `none` 的草稿不可提交。
- 草稿快照写入批次目录的 `announcement_drafts.json`，控制文件同时保留
  `drafts`，便于审计和重启复制。

## 当前限制

- 会话支持单策略、`all`（全部策略）和 `drafts`（全部草稿）三种模式；
  `all`/`drafts` 由 `run_all_web_experiment()` 串行执行，不支持中途单步。
- HTTP 服务为本地开发形态，未包含生产鉴权、后台任务队列和任务取消接口；
  `start`/`run` 等长任务在请求线程内同步执行。
- 未包含多用户隔离；进程内只有一个全局 `RLock` 保护部分会话动作，
  不适合多用户同时操作同一批次。
