"""后端路径与运行配置。

其他模块只从本文件读取路径和运行参数，避免各自拼接路径。
原 ``backend/demo/project_config.py`` 中的配置在迁移时集中到这里，
并改为面向 ``backend/app`` 分层结构：代码位于 ``backend/``，
可部署的配置位于 ``configs/``，输入数据位于 ``data/``，运行产物位于 ``var/``。
"""

import json
import os
from pathlib import Path


# settings.py -> config -> main -> app -> backend
BACKEND_DIR = Path(__file__).resolve().parents[3]
PROJECT_DIR = BACKEND_DIR.parent
CONFIG_DIR = PROJECT_DIR / "configs"
DATA_DIR = PROJECT_DIR / "data"
VAR_DIR = PROJECT_DIR / "var"

PERSONA_DIR = DATA_DIR / "processed" / "personas"
EXAMPLE_DIR = DATA_DIR / "examples"

# 默认运行状态放在 var/state；实验场景可以通过环境变量使用独立目录。
DEFAULT_STATE_DIR = (VAR_DIR / "state").resolve()
STATE_DIR = Path(
    os.environ.get("SIMULATION_STATE_DIR", str(DEFAULT_STATE_DIR))
).resolve()
# 状态目录的安全根目录：默认状态、实验场景和检查点必须落在项目目录内。
# 允许通过 SIMULATION_EXPERIMENT_DIR 把实验目录指向项目内的其他位置。
STATE_ROOT = PROJECT_DIR.resolve()
DEFAULT_EXPERIMENT_DIR = VAR_DIR / "experiments"
EXPERIMENT_DIR = Path(
    os.environ.get("SIMULATION_EXPERIMENT_DIR", str(DEFAULT_EXPERIMENT_DIR))
).resolve()
REPORT_DIR = Path(
    os.environ.get("SIMULATION_REPORT_DIR", str(VAR_DIR / "reports"))
).resolve()
# 历史事件知识图谱产物：默认使用仓库内快照，可用 KG_GRAPH_FILE 指向 kg 管线最新输出。
KG_GRAPH_FILE = Path(
    os.environ.get(
        "KG_GRAPH_FILE",
        str(VAR_DIR / "knowledge_graph" / "graph.json"),
    )
).resolve()
# 2026/11/04 Neo4j 图数据库：事件知识图谱的主存储；不可用时回退 graph.json。
KG_NEO4J_ENABLED = os.environ.get(
    "KG_NEO4J_ENABLED", "1"
).strip().lower() not in {"0", "false", "no", "off"}


def _read_neo4j_credentials(path_value: str) -> dict:
    """读取 Neo4j Aura 下载的凭据文件（NEO4J_URI=... 等）。"""

    if not path_value:
        return {}
    path = Path(path_value)
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _neo4j_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    for name in names:
        value = _neo4j_credentials.get(name)
        if value:
            return str(value).strip()
    return default


_neo4j_config = {}
_neo4j_config_file = CONFIG_DIR / "neo4j.json"
if _neo4j_config_file.is_file():
    try:
        _neo4j_config = json.loads(
            _neo4j_config_file.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError):
        _neo4j_config = {}
if not isinstance(_neo4j_config, dict):
    _neo4j_config = {}

_neo4j_credentials = _read_neo4j_credentials(
    os.environ.get("NEO4J_CREDENTIALS_FILE", "").strip()
    or str(_neo4j_config.get("credentials_file") or "").strip()
)
_neo4j_uri = _neo4j_value("NEO4J_URI")
_neo4j_http_url = _neo4j_value("NEO4J_HTTP_URL")
if not _neo4j_http_url:
    if _neo4j_uri.startswith(("neo4j+s://", "neo4j://", "bolt+s://", "bolt://")):
        host = _neo4j_uri.split("://", 1)[1].split("/")[0].split(":")[0]
        scheme = "https" if "+s" in _neo4j_uri else "http"
        _neo4j_http_url = f"{scheme}://{host}"
    else:
        _neo4j_http_url = "http://127.0.0.1:7474"
NEO4J_HTTP_URL = _neo4j_http_url.rstrip("/")
NEO4J_USER = _neo4j_value("NEO4J_USER", "NEO4J_USERNAME", default="neo4j")
NEO4J_PASSWORD = _neo4j_value("NEO4J_PASSWORD", default="eventkg123")
NEO4J_DATABASE = _neo4j_value("NEO4J_DATABASE", default="neo4j") or "neo4j"
# 空表示自动：https（Neo4j Aura）走 Query API，http（本地）走事务接口。
_neo4j_query_api = os.environ.get("NEO4J_QUERY_API", "").strip().lower()
NEO4J_QUERY_API = (
    None
    if not _neo4j_query_api
    else _neo4j_query_api not in {"0", "false", "no", "off"}
)
NEO4J_TIMEOUT = float(os.environ.get("NEO4J_TIMEOUT", "30"))
# 2026/08/22 系统重置与状态初始化，修改功能：正式实验可读取本批次独立的事件快照。
EVENT_FILE = Path(
    os.environ.get(
        "SIMULATION_EVENT_FILE",
        str(CONFIG_DIR / "events" / "event_example.json"),
    )
).resolve()
# 2026/08/23 内容策略对照，新增功能：配置人工维护的官方内容策略输入文件。
OFFICIAL_RESPONSE_FILE = CONFIG_DIR / "strategies" / "official_response_options.json"
# 历史趋势复现：事件资料放在 data/historical_replay，当前事件指针放在 configs/events。
HISTORICAL_REPLAY_DIR = DATA_DIR / "historical_replay"
HISTORICAL_EVENTS_DIR = HISTORICAL_REPLAY_DIR / "events"
HISTORICAL_ACTIVE_EVENT_FILE = CONFIG_DIR / "events" / "active_event.json"
EVENT_STATE_FILE = STATE_DIR / "event_state_history.json"
POLICY_FILE = PERSONA_DIR / "policy_config.json"

# 2026/11/03 MongoDB 主存储：Persona、关系网络与事件记录统一入库。
# SIMULATION_STORAGE_BACKEND=json 可退回旧的文件存储，便于离线调试和对照。
STORAGE_BACKEND = os.environ.get(
    "SIMULATION_STORAGE_BACKEND", "mongodb"
).strip().lower()
MONGO_URI = os.environ.get(
    "MONGO_URI", "mongodb://127.0.0.1:27017"
).strip()
MONGO_DATABASE = os.environ.get(
    "MONGO_DATABASE", "future_simulation"
).strip()
MONGO_SERVER_SELECTION_TIMEOUT_MS = int(
    os.environ.get("MONGO_SERVER_SELECTION_TIMEOUT_MS", "3000")
)
# JSON 镜像与 MongoDB 同步写入：清理源 JSON 后默认关闭，MongoDB 为唯一存储。
# 需要与旧文件流程对照时可设置 MONGO_WRITE_JSON_MIRROR=true。
MONGO_WRITE_JSON_MIRROR = os.environ.get(
    "MONGO_WRITE_JSON_MIRROR", "false"
).strip().lower() not in {"0", "false", "no", "off"}
# 单文件备份/恢复：清理 Persona、关系网络与事件 JSON 后用它重建数据库。
MONGO_BACKUP_FILE = DATA_DIR / "backups" / "future_simulation.json"

# Agent 动态状态单独放在 state 目录中，不再和决策代码、示例输入混在一起。
AGENT_STATE_FILE = STATE_DIR / "agent_state_history.jsonl"
DECISION_HISTORY_FILE = STATE_DIR / "decision_history.jsonl"
INCREMENTAL_COMMENT_FILE = STATE_DIR / "incremental_comment_history.jsonl"
METRICS_HISTORY_FILE = STATE_DIR / "metrics_history.jsonl"
# 2026/9/5，社交网络传播第二阶段A，新增功能：为每个场景保存独立传播事件历史。
PROPAGATION_HISTORY_FILE = STATE_DIR / "propagation_history.jsonl"

# 2026/08/22 系统重置与状态初始化，修改功能：正式实验可读取本批次独立的评论池。
COMMENT_POOL_FILE = Path(
    os.environ.get(
        "SIMULATION_COMMENT_POOL_FILE",
        str(STATE_DIR / "comment_pool.json"),
    )
).resolve()
# 2026/09/05 评论人物类型配置归档，修改功能：从部署配置目录读取评论生成模板。
COMMENT_PROFILE_FILE = CONFIG_DIR / "comment_profiles.json"
# 2026/11/09 初始舆论池双来源，新增功能：生成式 / 采集式的默认配置与开关。
# 运行时可被单个会话的 opinion_pool_config 覆盖，优先级见 app.comments.opinion_pool。
OPINION_POOL_CONFIG_FILE = CONFIG_DIR / "opinion_pool.json"
OPINION_POOL_SOURCE = os.environ.get("OPINION_POOL_SOURCE", "").strip() or "generate"
# 2026/9/5，社交网络传播，新增功能：集中配置固定网络并允许实验子进程读取同一份网络快照。
SOCIAL_NETWORK_CONFIG_FILE = CONFIG_DIR / "social_network_config.json"
SOCIAL_NETWORK_FILE = Path(
    os.environ.get(
        "SIMULATION_SOCIAL_NETWORK_FILE",
        str(STATE_DIR / "social_network_snapshot.json"),
    )
).resolve()
# 单Agent LLM调试结果保存在示例目录；正式批次不写入此文件。
SINGLE_LLM_RESULT_FILE = EXAMPLE_DIR / "decision_result_llm.json"

# 2026/09/06 GitHub推送安全处理，修改功能：从环境变量读取模型配置，避免提交本机密key。
# 2026/11/04 Windows 用户变量兼容：进程环境没有时回退 HKCU/HKLM 环境变量。
def _clean_secret(value) -> str:
    """去掉首尾空白与成对引号，避免环境变量复制时带入多余字符。"""

    text = str(value or "").strip()
    for _ in range(2):
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
            text = text[1:-1].strip()
    return text


def _windows_environment_values(name: str):
    """读取 Windows 用户/机器级环境变量，返回 [(来源, 值)]。"""

    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    locations = (
        ("user", winreg.HKEY_CURRENT_USER, "Environment"),
        (
            "machine",
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    )
    values = []
    for source, root, path in locations:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if not isinstance(value, str):
            continue
        try:
            value = winreg.ExpandEnvironmentStrings(value)
        except OSError:
            pass
        cleaned = _clean_secret(value)
        if cleaned:
            values.append((source, cleaned))
    return values


def _deepseek_key_with_source():
    """返回 (API Key, 来源)：process / user / machine / none。"""

    process_value = _clean_secret(os.environ.get("DEEPSEEK_API_KEY", ""))
    if process_value:
        return process_value, "process"
    for source, value in _windows_environment_values("DEEPSEEK_API_KEY"):
        return value, source
    return "", "none"


def get_deepseek_api_key() -> str:
    """读取 DeepSeek API Key（进程环境优先，Windows 用户变量兜底）。"""

    return _deepseek_key_with_source()[0]


def get_deepseek_api_key_source() -> str:
    """返回 Key 来源，用于健康检查与排查；不会返回 Key 本身。"""

    return _deepseek_key_with_source()[1]


DEEPSEEK_API_KEY = get_deepseek_api_key()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_ENDPOINT = os.environ.get(
    "DEEPSEEK_ENDPOINT",
    "https://api.deepseek.com/chat/completions",
)
REQUEST_TIMEOUT = 120

# 联调修改：增加DeepSeek请求和评论批次的重试配置 2026/08/21 19：06
HTTP_RETRY_COUNT = 3
HTTP_RETRY_INTERVAL = 2
# 2026/08/24 增量评论第二次修改，修改功能：增加评论批次补齐次数，并统一配置冗余生成数量。
COMMENT_BATCH_RETRY_COUNT = 5
COMMENT_BATCH_EXTRA_COUNT = 2
# 2026/09/04 增量评论生成架构优化，新增功能：限制增量评论首轮并发批次数，并将业务补齐收敛为一次。
INCREMENTAL_COMMENT_BATCH_WORKERS = 2
INCREMENTAL_COMMENT_REFILL_ATTEMPTS = 1
# 2026/09/04 评论质量与耗时平衡，新增功能：质量未达标时最多追加一次救援请求，并允许少量备选表达。
INCREMENTAL_COMMENT_QUALITY_RESCUE_ATTEMPTS = 1
INCREMENTAL_COMMENT_RESCUE_EXTRA_COUNT = 2
# 2026/08/24 增量评论稳定补齐，修改功能：三条仅作为数据质量告警阈值，不再作为场景失败上限。
INCREMENTAL_COMMENT_FALLBACK_WARNING_LIMIT = 3

# 批量决策配置。
MAX_AGENT_COUNT = 30
MAX_WORKERS = 5
RETRY_COUNT = 2

# 公共黑板配置。每个 Agent 每轮只随机看见部分全局评论。
VISIBLE_COMMENT_COUNT = 15
# 2026/08/25 第六次联调问题修复，新增功能：每轮优先向 Agent 展示 10 条当前轮评论。
CURRENT_STEP_VISIBLE_COUNT = 10
COMMENT_VISIBILITY_SEED = int(
    os.environ.get("SIMULATION_RANDOM_SEED", "2026")
)
# 2026/08/25 第六次联调问题修复，新增功能：从评分最高的 3 条评论中进行可复现选择。
COMMENT_SELECTION_TOP_K = 3
COMMENT_SELECTION_SEED = COMMENT_VISIBILITY_SEED

# 评论池配置。每个派系和情绪组合都会尽量覆盖。
COMMENT_POOL_SIZE = 60
# 2026/08/23 评论派系覆盖对齐，新增功能：配置初始评论池中每个派系的最低评论数量。
COMMENT_POOL_MIN_FACTION_COUNT = 5
INCREMENTAL_COMMENT_COUNT = 20
# 2026/10/19，修改功能：回应方案实验中每轮外生LLM评论降为8条，
# 避免20条外部评论长期压过7～17名实际发言Agent的内生表达。
# 历史复现继续使用 INCREMENTAL_COMMENT_COUNT，不受此配置影响。
STRATEGY_INCREMENTAL_COMMENT_COUNT = 8
COMMENT_POOL_TEMPERATURE = float(
    os.environ.get("SIMULATION_COMMENT_TEMPERATURE", "0.7")
)
COMMENT_POOL_MAX_TOKENS = 8000


def ensure_runtime_directories():
    """创建运行过程中需要的目录。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
