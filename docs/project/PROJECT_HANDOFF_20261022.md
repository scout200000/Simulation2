# 项目交接与使用教程（2026/10/22）

> **文档状态（2026-11-10 核对）**：本文写于 2026/10/22，部分命令和数据位置
> 已变化：Persona、默认事件和网络配置已迁入 MongoDB；回应方案为 4 个
> （`response_plan_1`～`response_plan_3` + `custom`，连同不回应基线共 5 个
> 场景）；新增 Neo4j 知识图谱、采集式舆论池和单套 `frontend/` 控制台。
> 运行命令以 [README.md](../../README.md)、[backend.md](../guides/backend.md)
> 和 [PROJECT_STATUS.md](PROJECT_STATUS.md) 为准；本文保留作为完整交接教程
> 和历史背景。

本文档面向第一次接触本项目的接手人员。它首先回答三个问题：系统能做什么、要准备什么、怎样一步一步运行。研发状态、验证边界和风险放在文档后部。

> 使用原则：先用可视化查看已有结果，再决定是否运行新实验。模拟会产生大量 DeepSeek 请求和费用；可视化不会调用 DeepSeek。

## 1. 系统能做什么

本系统把微博用户资料和历史表达整理为 Persona，在固定社交网络和个人可见信息约束下，模拟 Agent 的内部情绪、对官方信息的态度、沉默/原创/转发行为以及评论传播。当前提供四类能力：

1. **查看已有实验**：浏览已完成的方案对照、历史复现、Agent 状态、评论传播和社交网络。
2. **四种回应方案对照**：在同一事件、同一初始评论、同一 Agent 和同一网络条件下，对比 `response_plan_1`～`response_plan_3` 与 `custom` 四个回应方案，并自动加入一组“不回应”基线。
3. **历史趋势复现**：按真实时间线逐轮投入当时已知的客观事实、公众语境和官方通告，观察 Agent 在这些条件下如何响应，并与人工收集的真实群体趋势作探索性对照。
4. **Persona 构建**：从 MongoDB 的用户和微博集合生成 Agent Persona、派系偏好与情绪分位配置。

系统用于机制探索和方案相对比较，不等同于真实人口预测、因果识别或公安业务决策系统。结果应解释为“在当前样本、规则和模型条件下的模拟表现”。

## 2. 按任务选择入口

| 你要做的事 | 直接阅读 | 入口命令 | 是否调用 DeepSeek |
| --- | --- | --- | --- |
| 只查看已有结果 | 第4节 | `python legacy/visualization/app.py` | 否 |
| 运行四方案对照 | 第5节 | `py -3 backend/scripts/run_simulation.py` | 是 |
| 复现已有历史事件 | 第6节 | `py -3 backend/scripts/run_historical_replay.py --event-id <event_id>` | 是 |
| 新增一个历史事件 | 第7节 | 建立事件目录后运行历史复现 | 是 |
| 从 MongoDB 更新 Persona | 第8节 | `python pipelines/persona_pipeline/build_personas.py ...` | 是 |
| 检查结果是否有效 | 第9节 | 查看状态、指标口径和日志 | 否 |

## 3. 第一次使用前的准备

### 3.1 进入项目并安装环境

在 PowerShell 中执行（路径替换为实际项目根目录）：

```powershell
cd <项目根目录>
# Python 3.10+；当前开发机为 3.14。使用 conda 时可选执行前两行
conda create -n persona_sim python=3.11 -y
conda activate persona_sim
py -3 -m pip install -r requirements.txt
py -3 -m pip check
```

如果环境已经存在，以后只需进入项目目录并激活环境（未使用 conda 可跳过）：

```powershell
cd <项目根目录>
conda activate persona_sim
```

`python -m pip check` 输出 `No broken requirements found` 表示依赖关系完整。

### 3.2 设置 DeepSeek API Key

只在当前 PowerShell 窗口临时设置，不要写入源码、JSON、日志或交接文档：

```powershell
$env:DEEPSEEK_API_KEY = "替换为有效的API Key"
```

确认变量已存在时，不要打印完整密钥，可只检查长度：

```powershell
$env:DEEPSEEK_API_KEY.Length
```

关闭当前 PowerShell 后，该临时环境变量会失效。再次运行实验前需要重新设置。

### 3.3 检查基础 Persona

仿真默认从 MongoDB `future_simulation.personas` 和 `persona_policies` 读取
Persona。`data/processed/personas` 只是 Persona 管线的生成目录，源 JSON
已清理；首次使用应先启动 MongoDB 并执行
`py -3 backend/scripts/seed_mongodb.py`（无源 JSON 时自动从
`data/backups/future_simulation.json` 恢复）。

只运行模拟也需要 MongoDB；只有在显式设置
`SIMULATION_STORAGE_BACKEND=json` 且源 JSON 齐全时，才可退回纯文件存储。

## 4. 最快上手：查看已有实验

这是最安全的第一步，不调用 DeepSeek，也不会修改实验数据。

```powershell
conda activate persona_sim
python legacy/visualization/app.py
```

浏览器默认打开：

```text
http://127.0.0.1:8765
```

若浏览器没有自动打开：

```powershell
python legacy/visualization/app.py --no-browser
```

然后手动访问上述地址。页面中可以选择：

- **回应方案对照推演**：查看四个回应方案（含 `custom`）与不回应基线；
- **历史数据复现**：查看模拟趋势与真实群体趋势参考；
- **共享网络视图**：查看逐轮网络曝光、传播路径、Agent 节点状态和评论级联。

停止服务按 `Ctrl+C`。可视化只读取 `var/experiments` 中结构完整、状态可用的实验。

## 5. 运行四种回应方案对照实验

### 5.1 准备事件输入

默认事件已迁入 MongoDB（作用域 `configs/events/event_example.json`），
`configs/events/event_example.json` 源文件已清理。要更换默认事件，可更新
MongoDB/备份，或在控制台直接输入事件正文；只跑 CLI 时确保事件文档已存在。
事件 JSON 的最小结构如下：

```json
{
  "event_id": "event_example_001",
  "event_content": "填写事件发生时已知的公开信息",
  "event_labels": {
    "topic": "社会事件",
    "event_valence": "negative"
  }
}
```

注意：

- `event_id` 使用英文、数字和下划线，后续不要随意改变；
- `event_content` 只写实验起点已经公开的信息，不要提前写入后续调查结论；
- `event_valence` 是事件背景标签，不会禁止 Agent 表达积极、中性或负面情绪。

### 5.2 准备四个回应方案

编辑 `configs/strategies/official_response_options.json`：

- 顶层 `event_id` 必须与当前默认事件完全一致；
- `content_strategies` 必须恰好包含四项：
  `response_plan_1`、`response_plan_2`、`response_plan_3` 和 `custom`；
- 四项可代表任意回应内容，不要求固定类别；
- 每项需要唯一的 `strategy_id`、展示名称、公告正文和公告状态；
- `custom` 默认公告为空；严格 CLI 校验要求四项公告都非空，空公告会使
  `run_simulation.py` 直接报错。只做单方案 Web 会话时，未填写的方案会
  以占位内容通过校验，但不会参与运行；
- 不回应基线由系统自动增加，不要手工写入第五项。

建议为每项补齐 `evidence_dimensions`，说明该公告是否包含已核实事实、已完成行动、责任处理、同理表达、尚未解决的过程和辟谣信息。该字段帮助系统区分公告提供了什么证据，而不是只按文本情绪判断。

### 5.3 运行实验

```powershell
conda activate persona_sim
$env:DEEPSEEK_API_KEY = "替换为有效的API Key"
py -3 backend/scripts/run_simulation.py
```

程序将依次：

1. 生成初始评论池；
2. 运行官方进场前共享基线；
3. 根据阈值判断官方进场轮次；
4. 从相同基线分流为不回应基线和四个回应方案；
5. 将每个场景独立演化并汇总比较。

每次运行都会新建目录，不覆盖旧实验：

```text
var/experiments/<event_id>_<timestamp>/
```

主结果为 `experiment_result.json`。每个方案子目录还包含逐轮状态、评论和传播记录。

### 5.4 判断是否运行成功

终端应显示五个场景均完成。打开 `experiment_result.json`，重点检查：

- 顶层 `status` 是否为 `completed`；
- `success_count` 是否为 5；
- `failed_count` 是否为 0；
- 五个场景是否都存在；
- 共享输入哈希和跨场景污染检查是否通过。

`partial_failed` 或 `failed` 不能当作完整对照实验。某一方案没有运行时，先看是否因官方进场条件未触发而标记为 `not_run`，不要把它误判为程序崩溃。

官方进场原因常见取值：

- `negative_threshold`：Agent负面率达到配置阈值；
- `global_worsening`：全局趋势被判断为恶化；
- `stagnation`：舆情连续多轮没有明显改善。

新批次还应检查 `experiment_result.json.counterfactual_controls.cross_scenario_audit.status` 是否为 `passed`。五个场景的 `shared_input_sha256` 应一致，`scenario_input_sha256` 应各不相同；通告投入后的公众反应和 Agent 表达必须保存在各自场景目录，不得继续复制不回应场景的数据。

## 6. 运行已有历史事件

### 6.1 查看可用事件

```powershell
py -3 backend/scripts/run_historical_replay.py --list-events
```

当前事件仓库包括：

- `event_huxinyu_2022_001`；
- `event_beiguo_xiantianxia_crash_20260920_002`；
- `event_baoding_driving_school_crash_20261006_001`。

### 6.2 运行指定事件

以胡鑫宇事件为例：

```powershell
conda activate persona_sim
$env:DEEPSEEK_API_KEY = "替换为有效的API Key"
py -3 backend/scripts/run_historical_replay.py --event-id event_huxinyu_2022_001
```

另外两个事件：

```powershell
py -3 backend/scripts/run_historical_replay.py --event-id event_beiguo_xiantianxia_crash_20260920_002
py -3 backend/scripts/run_historical_replay.py --event-id event_baoding_driving_school_crash_20261006_001
```

当前命令不支持 `--with-initial-opinion` 或 `--without-initial-opinion`。第一轮人工情绪比例校准由事件目录中的 `initial_opinion.json` 固定提供。

历史复现结果同样新建在：

```text
var/experiments/<event_id>_<timestamp>/
```

主要文件：

- `historical_replay_result.json`：历史复现总结果；
- `historical_replay/state/metrics_history.jsonl`：逐轮指标；
- `historical_replay/state/incremental_comment_history.jsonl`：逐轮新增表达；
- `historical_replay/state/propagation_history.jsonl`：传播记录。

### 6.3 转换真实趋势并查看页面

若事件的 `real_trend_source.xlsx` 已新增或更新，先执行：

```powershell
python legacy/visualization/historical/real_data_processor.py --event-id event_huxinyu_2022_001
```

生成文件位于：

```text
legacy/visualization/data/real_trends/<event_id>.json
```

然后启动页面：

```powershell
python legacy/visualization/app.py
```

## 7. 新增一个历史事件并完成复现

新增事件通常不需要修改 Python 代码。每个事件是一套独立、可追溯的输入资料，统一放在：

```text
data/historical_replay/events/<event_id>/
```

下面流程从建立目录开始，一直到运行、验收和网页查看。建议严格按顺序操作。

### 7.1 先确定事件编号和阶段

1. 为事件确定唯一的 `event_id`，建议格式为 `event_<英文简称>_<日期>_001`，例如 `event_example_crash_20261022_001`。为避免命令行和路径兼容问题，建议只使用小写英文字母、数字和下划线。
2. 根据真实时间线划分阶段。每一阶段对应仿真的一轮，至少需要 2 轮。
3. 第 1 轮必须是首份官方通告发布前的阶段；官方通告只能从第 2 轮开始投入。
4. 通告发布、重要事实确认或舆情环境明显变化时，可以划分新阶段。不要为了凑轮数虚构阶段。
5. `official_response_timeline.json` 和 `public_context_timeline.json` 必须使用相同的轮数、轮次和时间边界。

历史复现必须有第一轮人工情绪比例。若没有可追溯的第一轮材料，应先补充采集或明确记录人工估计依据，不要伪造比例后再把结果称为历史拟合。

### 7.2 建立事件目录

最稳妥的做法是复制一个阶段数和材料结构相近的已有事件作为模板，然后只修改副本。不要覆盖原事件目录。

```powershell
$eventId = "event_example_crash_20261022_001"
$template = "data\historical_replay\events\event_beiguo_xiantianxia_crash_20260920_002"
$target = "data\historical_replay\events\$eventId"
Copy-Item -LiteralPath $template -Destination $target -Recurse
```

复制后，必须逐个检查并替换所有旧事件名称、旧正文、旧时间、旧来源和旧 `event_id`，不能只修改目录名。

### 7.3 准备五个必需 JSON 和一个可选 Excel

| 文件 | 是否必须 | 用途 | 是否进入 Agent 决策 |
| --- | --- | --- | --- |
| `event_manifest.json` | 是 | 记录事件名称、原始材料名称和来源哈希 | 否 |
| `event_input.json` | 是 | 记录事件开始时已经公开的初始事实和仿真参数 | 是 |
| `initial_opinion.json` | 是 | 将第一轮人工情绪比例换算为初始评论整数配额 | 只用于第 1 轮初始化 |
| `public_context_timeline.json` | 是 | 记录每轮当时可见的客观事实、公众议题和建设性证据 | 是 |
| `official_response_timeline.json` | 是 | 记录阶段范围及官方通告的真实正文、状态和发布时间 | 是 |
| `real_trend_source.xlsx` | 可选 | 保存人工收集的逐阶段真实群体趋势 | 否，只用于可视化对照 |

所有 JSON 的 `event_id` 必须与目录名完全一致。

#### 7.3.1 `event_manifest.json`

最小示例：

```json
{
  "event_id": "event_example_crash_20261022_001",
  "title": "示例事件",
  "initial_opinion_file": "initial_opinion.json",
  "public_context_timeline_file": "public_context_timeline.json",
  "real_trend_source_file": "real_trend_source.xlsx",
  "real_trend_source_original_name": "原始人工统计表.xlsx",
  "real_trend_source_sha256": "替换为真实SHA-256"
}
```

若有 Excel，可用下面的命令计算哈希并填入清单：

```powershell
(Get-FileHash -Algorithm SHA256 -LiteralPath "$target\real_trend_source.xlsx").Hash
```

若没有真实趋势 Excel，应删除示例中的三个 `real_trend_source_*` 字段，不要保留虚假的文件名或哈希。

#### 7.3.2 `event_input.json`

`event_content` 只能写第 1 轮开始时已经公开的事实，不能提前写入后续通告或调查结论。建议沿用当前历史复现参数：

```json
{
  "event_id": "event_example_crash_20261022_001",
  "event_content": "填写事件发生后、首份官方通告发布前已经公开的事实。",
  "event_labels": {
    "topic": "社会事件",
    "event_valence": "negative"
  },
  "simulation_options": {
    "emotion_choice_mode": "evidence_based_all",
    "incremental_comment_count": 50,
    "active_opinion_window": 2,
    "network": {
      "neighbors_per_agent": 5
    },
    "visibility": {
      "neighbor_comment_count": 4,
      "public_comment_count": 11
    },
    "context_exposure": {
      "public_discourse_reach_rate": 0.65,
      "positive_evidence_reach_rate": 0.5
    }
  }
}
```

首次新增事件时不要随意调参；先保持与现有事件一致，才能判断差异来自事件材料还是参数变化。

#### 7.3.3 `initial_opinion.json`

本文件只校准第 1 轮的初始公共评论环境，不直接指定 Agent 的内部情绪，也不会在第 2 轮以后继续注入真实比例。

```json
{
  "schema_version": 1,
  "event_id": "event_example_crash_20261022_001",
  "step": 1,
  "mode": "historical_calibration",
  "comment_count": 60,
  "emotion_targets": {
    "negative": 36,
    "neutral": 18,
    "positive": 6
  },
  "observed_distribution": {
    "negative": {"estimate": 0.60, "source_expression": "约60%"},
    "neutral": {"estimate": 0.30, "source_expression": "约30%"},
    "positive": {"estimate": 0.10, "source_expression": "约10%"}
  },
  "source": {
    "type": "manual_group_trend_reference",
    "file": "real_trend_source.xlsx",
    "sheet": "Sheet1",
    "source_row": 3
  },
  "evaluation_role": "initial_condition"
}
```

约束如下：

- `step` 必须为 `1`；
- `mode` 必须为 `historical_calibration`；
- `evaluation_role` 必须为 `initial_condition`；
- 三类 `emotion_targets` 必须是非负整数，且总和必须等于 `comment_count`；
- 当前标准初始评论池为 60 条，因此通常把人工比例换算成总数为 60 的整数配额；
- 不得增加 `public_discourse_context`，公众语境应写入单独的时间线文件。

#### 7.3.4 `official_response_timeline.json`

下面是一个三阶段、一次通告的示例：

```json
{
  "event_id": "event_example_crash_20261022_001",
  "total_steps": 3,
  "step_periods": [
    {"step": 1, "period": "2026.10.22 08:00-12:00", "phase": "通告前"},
    {"step": 2, "period": "2026.10.22 12:00-2026.10.23 12:00", "phase": "通告发布一天内"},
    {"step": 3, "period": "2026.10.23 12:00以后", "phase": "通告发布一天后"}
  ],
  "official_updates": [
    {
      "step": 2,
      "published_at": "2026-10-22 12:00",
      "official_statement": "填写官方通告原文，不要自行概括或补充未公开结论。",
      "official_statement_status": "incomplete",
      "source_url": "填写原始链接或人工材料位置"
    }
  ]
}
```

约束如下：

- `total_steps` 必须是不小于 2 的整数；
- `step_periods` 必须从 1 开始连续覆盖全部轮次；
- 同一轮最多首次投入一条官方信息；后续轮次会持续使用最近一次有效通告；
- 官方信息只能放在第 2 轮及以后；
- `official_statement_status` 只能是 `clear`、`incomplete` 或 `conflict`；
- 若有多次官方通告，在各自真实发布轮次分别增加 `official_updates` 记录。

#### 7.3.5 `public_context_timeline.json`

该文件描述“这一轮的 Agent 当时能够接触到什么”，不是为了填写希望模型达到的结果。最小结构如下：

```json
{
  "schema_version": 1,
  "event_id": "event_example_crash_20261022_001",
  "steps": [
    {
      "step": 1,
      "period": "2026.10.22 08:00-12:00",
      "phase": "通告前",
      "verified_updates": [
        {
          "evidence_id": "verified_001_incident",
          "update_kind": "confirmed_fact",
          "evidence_strength": "strong",
          "evidence_target": "event_outcome",
          "content": "填写本阶段已经确认的客观事实。",
          "source_refs": ["event_input.json"]
        }
      ],
      "public_discourse": [
        {
          "context_id": "public_001_question",
          "content": "填写本阶段真实存在的主要公众议题或未解决疑问。",
          "source_refs": ["人工材料名称或链接"],
          "status": "public_question",
          "unresolved_concern": true
        }
      ],
      "positive_evidence": []
    },
    {
      "step": 2,
      "period": "2026.10.22 12:00-2026.10.23 12:00",
      "phase": "通告发布一天内",
      "verified_updates": [],
      "public_discourse": [],
      "positive_evidence": []
    },
    {
      "step": 3,
      "period": "2026.10.23 12:00以后",
      "phase": "通告发布一天后",
      "verified_updates": [],
      "public_discourse": [],
      "positive_evidence": []
    }
  ]
}
```

填写规则：

- `steps` 必须完整覆盖 `1..total_steps`，`period` 和 `phase` 应与官方时间线一致；
- 每一条证据或语境都要有全事件唯一的编号、非空 `content` 和非空 `source_refs`；
- `verified_updates.update_kind` 只能是 `status_continuation`、`procedural_update`、`confirmed_fact` 或 `final_conclusion`；
- `public_discourse.status` 只能是 `public_question`、`unverified_claim`、`ongoing_discussion` 或 `social_action`；
- 没有相应材料时填写空数组，不要编造证据；
- 严禁写入 `emotion_targets`、`observed_distribution`、`negative_rate`、`neutral_rate` 或 `positive_rate`；
- 严禁把后续才发生的事实提前放入前一轮。

#### 7.3.6 `real_trend_source.xlsx`（可选）

该表只用于运行后的真实趋势对照，不会进入 Agent 提示词或改变决策。工作表默认名为 `Sheet1`，处理器会动态读取表头之后的有效阶段，不要求固定八阶段。

表中必须能识别以下列：

| 列名 | 含义 |
| --- | --- |
| `关键节点` | 阶段名称 |
| `时间线` | 阶段时间范围 |
| `当前` | 采样方法或材料说明 |
| `社会情绪` | 至少包含可识别的负面百分比，例如“负面约60%” |
| `网络当前舆论` | 该阶段的群体舆论摘要 |

至少需要两个同时包含“时间线”和“社会情绪”的有效阶段。正面、中性、负面最好均记录，人工估计的限制和来源也应保留。

### 7.4 先做不调用大模型的结构校验

先确认事件能被事件仓库识别：

```powershell
py -3 backend/scripts/run_historical_replay.py --list-events
```

`--list-events` 主要检查目录和必需文件。再运行下面的只读深度校验，检查事件输入、第一轮配额、官方时间线和公众语境之间是否一致：

```powershell
$eventId = "event_example_crash_20261022_001"
$env:HISTORICAL_EVENT_ID = $eventId
@'
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path("backend").resolve()))

from app.historical_replay.event_repository import resolve_event_files
from app.historical_replay.initial_opinion import validate_initial_opinion
from app.historical_replay.public_context import load_public_context_timeline
from app.historical_replay.timeline_service import load_official_response_timeline
from app.infrastructure.storage.json_storage import load_json
from app.domain.events.context import validate_event_input

paths = resolve_event_files(os.environ["HISTORICAL_EVENT_ID"])
event = validate_event_input(load_json(paths["event_file"]))
timeline = load_official_response_timeline(
    paths["timeline_file"], event["event_id"]
)
validate_initial_opinion(
    load_json(paths["initial_opinion_file"]),
    expected_event_id=event["event_id"],
)
load_public_context_timeline(
    paths["public_context_file"],
    expected_event_id=event["event_id"],
    expected_total_steps=timeline["total_steps"],
)
print(
    f"事件输入校验通过：{event['event_id']}，"
    f"共 {timeline['total_steps']} 轮，"
    f"官方通告 {len(timeline['official_updates'])} 次"
)
'@ | py -3 -
Remove-Item Env:HISTORICAL_EVENT_ID
```

结构校验通过不代表材料内容一定准确，仍需人工复核时间边界、通告原文和来源引用。

### 7.5 转换真实趋势（有 Excel 时执行）

```powershell
$eventId = "event_example_crash_20261022_001"
python legacy/visualization/historical/real_data_processor.py --event-id $eventId
```

若工作表不是 `Sheet1`：

```powershell
python legacy/visualization/historical/real_data_processor.py --event-id $eventId --sheet "实际工作表名"
```

成功后会生成：

```text
legacy/visualization/data/real_trends/<event_id>.json
```

没有真实趋势 Excel 时可以跳过此步，历史仿真仍可运行，但网页不会提供该事件的真实群体趋势对照，不能据此声称完成了拟合验证。

### 7.6 设置密钥并运行历史复现

在当前 PowerShell 会话中设置有效密钥：

```powershell
$env:DEEPSEEK_API_KEY = "替换为有效的DeepSeek API Key"
```

运行指定事件：

```powershell
$eventId = "event_example_crash_20261022_001"
py -3 backend/scripts/run_historical_replay.py --event-id $eventId
```

不要添加已经移除的 `--with-initial-opinion` 或 `--without-initial-opinion` 参数。当前历史复现固定使用 `initial_opinion.json` 校准第一轮。

每次运行都会在 `var/experiments/` 下创建新的实验目录，不覆盖事件源目录，也不覆盖以前的实验结果。

### 7.7 验收运行结果

控制台和结果文件至少应满足：

1. 控制台显示“历史趋势复现完成”，而不是“失败”；
2. `status` 为 `completed`；
3. `step_count` 与 `official_response_timeline.json.total_steps` 一致；
4. `official_update_count` 与配置的官方通告次数一致；
5. 新实验目录中存在 `historical_replay_result.json`；
6. 各轮结果、Agent 实际表达、官方态度和传播数据均能被读取；
7. 若有真实趋势文件，结果中的 `event_id` 必须与真实趋势 JSON 一致。

实验目录形式如下：

```text
var/experiments/<event_id>_<运行时间>/
```

不要只看命令是否结束；若余额不足、认证失败或某轮 Agent 决策失败，程序可能已经留下一个 `status: failed` 的批次目录，该目录不能作为完成结果。

### 7.8 打开网页检查

```powershell
python legacy/visualization/app.py
```

在页面中切换到“历史复现”，选择刚生成的实验，至少检查：

- 阶段数、时间边界和官方通告标记是否正确；
- Agent 内部情绪、实际表达情绪和官方态度是否都有逐轮数据；
- 社交网络与逐轮传播记录是否可见；
- 若提供 Excel，真实群体趋势是否与相同 `event_id` 的实验正确关联；
- 第一轮是否明确标记为历史初始条件，后续轮次是否没有继续注入真实情绪比例。

### 7.9 常见错误与处理

| 现象 | 常见原因 | 处理方法 |
| --- | --- | --- |
| 新事件未出现在 `--list-events` | 缺少必需文件，或文件中的 `event_id` 与目录名不一致 | 检查五个 JSON 及其中所有 `event_id` |
| 提示 `total_steps` 或阶段不一致 | 两条时间线的轮数、编号或覆盖范围不同 | 统一轮数，并连续覆盖 `1..total_steps` |
| 提示官方信息 `step` 不合法 | 把通告配置在第 1 轮，或轮次超过总轮数 | 第 1 轮保留为通告前，通告从第 2 轮开始 |
| 提示初始评论总数不一致 | 三类整数配额之和不等于 `comment_count` | 重新换算并检查整数总和 |
| 提示公众语境包含拟合目标 | 把真实情绪比例写进了公众语境 | 删除比例，只保留当时真实可见的事实和议题 |
| Excel 无法识别 | 表头、工作表名或阶段行不符合要求 | 检查五个必需列、`--sheet` 和至少两个有效阶段 |
| HTTP 401 | API Key 无效或当前会话未设置 | 重新设置 `DEEPSEEK_API_KEY` |
| HTTP 402 | DeepSeek 账户余额不足 | 充值或更换有效账户后重新运行 |
| 页面没有真实趋势 | 未转换 Excel，或真实趋势与实验 `event_id` 不一致 | 重新执行 7.5，并核对 `event_id` |

补充说明：`active_event.json` 只决定省略 `--event-id` 时的默认事件。新增和验收事件时建议始终显式传入 `--event-id`，不需要修改 `active_event.json`。

## 8. 从 MongoDB 更新 Persona

只有新增/更新用户数据并希望重建 Agent 时才执行本节。普通模拟从 MongoDB
`future_simulation.personas` 读取 Persona，不再直接读取
`data/processed/personas`；该目录只是生成源文件。

### 8.1 数据库要求

默认连接：

- MongoDB：`mongodb://localhost:27017`；
- 数据库：`weibo`；
- 用户集合：`user`；
- 微博集合：`weibo`。

微博集合至少保留：

- `user_id`：将微博关联到用户，必须；
- `text`：分类与指标的主要文本，必须；
- `id`：任务 ID 和断点续跑 ID，强烈建议；
- `retweet` 和 `retweet.text`：转发判断与转发正文，可选但会影响结果。

### 8.2 先构建基础 Persona

当前 `build_personas.py` 不会自动读取 `DEEPSEEK_API_KEY` 环境变量，需通过命令行显式传入：

```powershell
conda activate persona_sim
$env:DEEPSEEK_API_KEY = "替换为有效的API Key"
python pipelines/persona_pipeline/build_personas.py --deepseek-api-key $env:DEEPSEEK_API_KEY --limit-users 0 --output-dir "data/processed/personas"
```

`--limit-users 0` 表示处理用户集合中的全部用户。分类进度文件会恢复已完成任务，并处理数据库中新增的任务。不要为了“重新读取数据库”随意删除断点文件。

### 8.3 再生成派系偏好和情绪分位

```powershell
python pipelines/persona_pipeline/build_faction_preferences.py
python pipelines/persona_pipeline/emotion.py
```

必须按“基础 Persona → 派系偏好 → 情绪分位”顺序执行，因为第一步会重写 Persona，并可能移除需要重新计算的派系字段。

> 已知限制：`build_faction_preferences.py` 当前仍从 `build_personas.py` 导入 DeepSeek 配置，尚未提供独立命令行参数或完整环境变量入口。正式交接后若需要重建派系偏好，应优先把该脚本统一改成读取 `DEEPSEEK_API_KEY` 环境变量；不要把真实密钥重新硬编码进源码。

### 8.4 如何看待跳过的数据

`Content Exists Risk` 表示服务端内容安全策略拒绝了该条文本；JSON 解析失败表示模型返回格式不符合约定。程序会尝试拆批、逐条定位，并将仍失败的微博记为跳过。

少量跳过通常不会让整批 Persona 无法使用，但相应微博不会参与该项指标。交接人员应记录跳过数量和用户分布；若某个用户没有任何有效微博，其 Persona 指标可能缺少有效数据，不能与正常用户等同使用。

## 9. 如何判断实验结果

### 9.1 先看完成状态

- `completed`：流程完整结束，可以进入结果分析；
- `partial_failed`：部分场景失败，只能排错，不能作为完整策略对照；
- `failed`：实验失败；
- `failed_isolation_audit`：共同输入、场景编号、状态目录或公众反应存在跨场景污染；
- `not_run`：场景因条件未触发而未运行，不等同于代码异常。

评论质量状态另行解释：`normal` 表示未触发兜底告警；`degraded` 表示实验完成但部分轮次兜底较多；`emergency` 表示使用了本地应急评论。后两种状态不一定等于流程失败，但结论必须降级说明。

### 9.2 三类情绪指标不是一回事

- **Agent 情绪分布**：全部 Agent 的内部状态；
- **Agent 实际表达情绪分布**：本轮真正发言的 Agent，其表达情绪；
- **评论池情绪分布**：评论记录的情绪，可分当前新增、活跃窗口或历史累计。

三者的分母和语义不同，不应要求曲线完全一致。负面 Agent 可能沉默，中性 Agent 也可能针对调查过程表达负面评价。

### 9.3 官方态度与事件情绪分开解释

Agent 可以“接受官方结论但仍对事件感到负面”，也可以“情绪中性但质疑调查过程”。因此：

- `positive / neutral / negative` 描述对事件或表达对象的情绪；
- `accept / wait / question` 描述对官方信息的态度。

不能把“接受官方”直接解释为“积极情绪”，也不能把“质疑官方”直接解释为“负面情绪”。

### 9.4 历史拟合的正确说法

历史复现中的真实趋势是运行后参考，不进入 Agent 决策。第一轮若标记为历史初始条件，不计入 MAE 和峰值等拟合指标。样本点很少时，MAE 只能称为探索性差异，不能称为模型准确率。

### 9.5 推荐的结果检查顺序

1. 状态是否完整；
2. 输入事件、Persona、模型和机制版本是否一致；
3. 五场景共享条件是否一致且没有跨场景污染；
4. Agent 内部情绪、实际表达、评论池指标是否使用了正确口径；
5. 官方通告是否在预期轮次投入；
6. 是否出现 100% 同一情绪/态度、无人沉默、所有人每轮发言等异常趋同；
7. 社交网络是否存在有效邻居曝光和传播路径；
8. 回应方案实验是否通过 `counterfactual_controls` 场景隔离审计；
9. 最后再讨论与真实趋势的方向和幅度差异。

## 10. 常见问题与处理

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| HTTP 401 | API Key 缺失、无效或旧密钥已失效 | 在当前 PowerShell 重新设置有效 `DEEPSEEK_API_KEY` |
| HTTP 402 | DeepSeek 余额不足 | 充值或更换有余额的账户后重跑 |
| `Content Exists Risk` | 服务端内容安全拒绝 | 记录被跳过的微博；不要把它解释为重复微博 |
| JSON 无法解析、批次未补齐 | 模型返回空内容、格式错误或数量不足 | 等待自动重试；持续失败时保留日志并停止批量重跑 |
| `--with-initial-opinion` 无法识别 | 当前历史入口没有该参数 | 删除该参数，直接运行 `--event-id` |
| 页面看不到新实验 | 实验未完成、结构不完整或事件 ID 不匹配 | 检查结果状态、目录结构和真实趋势 `event_id` |
| 页面能开但没有真实趋势 | 尚未转换 Excel | 运行 `real_data_processor.py --event-id <event_id>` |
| 浏览器没有自动打开 | 自动打开失败 | 使用 `--no-browser` 后手动访问 `127.0.0.1:8765` |
| MongoDB 连接失败 | 服务未启动、URI/库名/集合名不匹配 | 检查 MongoDB 服务和四项连接配置 |
| `Ctrl+C` 后仍需等待 | 主进程正在回收子进程或网络请求未立即返回 | 再按一次 `Ctrl+C`，确认没有遗留 Python 进程后再重跑 |
| Git 提示 LF 将替换为 CRLF | Windows 换行提示，不是暂存失败 | 用 `git status` 和 `git diff --cached --check` 检查即可 |

PowerShell 中建议整条命令写在一行。不要复制带多余空格的反引号续行，否则会出现 `unrecognized arguments: \``。

## 11. 不要做的事情

- 不要把 API Key 写回源码、配置文件、日志或提交记录；
- 不要用 `git reset --hard`、`git clean` 或批量删除处理不熟悉的工作区；
- 不要删除 `var/experiments`、`data/processed/personas`、MongoDB 导出或真实趋势源文件，除非已明确确认保留策略并有备份；
- 不要修改旧实验目录中的输入来“修正”结果；新实验应创建新批次；
- 不要把不同日期、不同机制版本的实验直接合并成同一组统计结果；
- 不要为了得到更好曲线，把真实趋势比例写入后续轮次决策输入；
- 不要恢复已淘汰的北国旧事件 `event_beiguo_xiantianxia_crash_20260920_001` 作为当前运行入口。

## 12. 当前可用样本与验证边界

当前保留的完整实验样本：

| 类型 | 实验编号 |
| --- | --- |
| 历史复现 | `event_baoding_driving_school_crash_20261006_001_20261010_154112_520553` |
| 历史复现 | `event_beiguo_xiantianxia_crash_20260920_002_20261011_172334_394683` |
| 历史复现 | `event_beiguo_xiantianxia_crash_20260920_002_20261013_122213_379538` |
| 历史复现 | `event_huxinyu_2022_001_20261013_181206_806798` |
| 方案对照（旧机制） | `event_gaoyang_assault_001_20260906_143939_040535` |
| 方案对照（旧机制） | `event_gaoyang_assault_001_20261015_204046_683644` |
| 方案对照（旧机制） | `event_gaoyang_assault_001_20261019_112035_030498` |
| 方案对照（旧机制） | `event_gaoyang_assault_001_20261020_141414_286129` |

2026/10/28 之后的当前机制单场景完成批次（每个 10 轮，可单独查看，但
不是同一批次的横向对照）：

| 策略 | 实验编号 |
| --- | --- |
| `custom`（公告内容为辟谣） | `event_gaoyang_assault_001_20261028_093619_971429` |
| `response_plan_2` | `event_gaoyang_assault_001_20261103_104757_406652` |
| `custom`（自定义公告） | `event_gaoyang_assault_001_20261104_150027_887498` |
| `response_plan_3` | `event_gaoyang_assault_001_20261105_081047_035779` |

2026/11/10 复核时的离线测试：

```powershell
cd backend
py -3 -m unittest discover -s tests/unit -t .
# 247 项；本机受限沙箱下 26 项文件型用例因临时目录权限失败，需普通终端复核

cd pipelines/persona_pipeline
py -3 -m unittest discover -s tests -t tests
# 4 项通过

py -3 -m unittest discover -s legacy/visualization/tests -t .
# 22 项，4 项跳过；1 项因旧批次网络快照文件缺失失败
```

验证边界：

- 尚未用最终 `strategy_directional_utility_v3` 完成新的 DeepSeek 五场景
  同批次全量实验；
- 当前机制只有单场景完成批次，不能证明横向方案效果；
- 尚未完成最终机制下的完整在线历史复现；
- 尚未完成多事件、多随机种子、多批次稳定性验证；
- MongoDB、JSON API 和 Neo4j 图谱已经实现，但生产级队列、权限、并发调度
  和部署仍未验证；
- 保留实验来自不同阶段的机制版本，只能分别作为历史样本，不能证明最终机制有效。

## 13. 接手开发人员的检查命令

先执行轻量检查，不调用 DeepSeek：

```powershell
conda activate persona_sim
$env:PYTHONDONTWRITEBYTECODE = "1"
cd backend; py -3 -m unittest discover -s tests/unit -t .
cd ..\pipelines\persona_pipeline; py -3 -m unittest discover -s tests -t tests
cd ..\..; py -3 -m unittest discover -s legacy/visualization/tests -t .
git diff --check
```

接手人员确认基础功能后，再决定是否支付在线模型费用运行完整实验。不要用离线单元测试替代对模型输出质量的验证。

## 14. Git 交接流程

当前仓库（若交付目录没有 `.git`，说明是文件复制交付，不能执行本节命令；
应以 PROJECT_STATUS.md 的版本风险说明为准）：

```text
origin https://github.com/jiuBABY6/Simulation2.git
branch main
```

交付人应在最终修改完成后：

```powershell
git status --short
git diff --cached --check
git diff --cached --stat
git commit -m "docs: complete project handoff tutorial"
git push origin main
git tag handoff-20261022
git push origin handoff-20261022
```

是否提交和推送由项目负责人决定；不要在未审阅暂存内容时直接执行。接手人获取代码后执行：

```powershell
git fetch origin --tags
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git rev-list -n 1 handoff-20261022
git status --short
```

`git rev-parse HEAD` 与标签指向一致且工作区为空，说明接收的是正式交接快照。若不一致，应先报告差异，不要立即重置或删除本地内容。

## 15. 推荐的首次接手顺序

1. 安装/激活 `persona_sim`；
2. 启动可视化，浏览一个方案对照样本和一个历史复现样本；
3. 阅读 `PROJECT_STATUS.md`、`ARCHITECTURE.md` 和 `DATA_CONTRACT.md`；
4. 运行三套离线单元测试；
5. 确认 API Key、余额和费用预算；
6. 选择一个已有历史事件做在线烟雾运行；
7. 检查完成状态、Agent 状态、实际表达、官方态度和传播网络；
8. 再运行完整四方案对照；
9. 最后才考虑新增事件、重建 Persona 或继续重构。

按照这一顺序，接手人员可以先验证“会不会看、能不能跑、结果在哪里”，再进入机制修改，避免在不了解数据口径时直接改动核心决策逻辑。
