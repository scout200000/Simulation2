# Future

多 Agent 社会舆情仿真系统：后端提供实验编排、逐轮会话控制、指标与报告
接口，前端提供控制台、历史会话、知识图谱与报告页面。

```text
future/
├─ backend/              仿真引擎、历史复现与 JSON API（docs/guides/backend.md）
├─ frontend/             Vue 3 控制台（docs/guides/frontend.md）
├─ pipelines/
│  ├─ kg/                事件知识图谱抽取管线（docs/guides/kg.md）
│  ├─ comment_harvest/   事件热帖与评论采集 Agent（docs/guides/comment_harvest.md）
│  └─ persona_pipeline/  Persona 构建管线（docs/guides/persona_pipeline.md）
├─ legacy/
│  └─ visualization/     旧版只读可视化（docs/design/VISUALIZATION.md）
├─ third_party/          参考工程，不参与运行（docs/guides/reference_projects.md）
├─ configs/              部署配置（评论人物类型、事件与回应方案、初始舆论池、Neo4j）
├─ data/                 输入数据：历史事件资料、历史语料、样例与可提交备份
├─ var/                  运行产物：state、experiments、reports、knowledge_graph、comment_harvest、legacy
├─ docs/                 文档中心（结构、接口、数据契约、历史复现）
├─ README.md
└─ requirements.txt
```

快速开始：

```powershell
# 1. 确认 MongoDB 已启动（Windows 服务 MongoDB 自动启动；
#    若不可用，可运行 py -3 backend/scripts/start_mongodb.py 启动项目实例）
py -3 backend/scripts/start_mongodb.py --status

# 2. 初始化 Persona、关系网络与事件记录
#    （源 JSON 存在时优先导入；源 JSON 已清理时自动从单文件备份恢复）
py -3 backend/scripts/seed_mongodb.py

# 3. 后端 API（默认 127.0.0.1:8770，前端开发代理指向该地址）
py -3 backend/scripts/run_api_server.py

# 4. 前端控制台（默认 127.0.0.1:5173）
cd frontend
pnpm install
pnpm run dev
```

Persona、关系网络和事件记录以 MongoDB 为唯一数据源，可提交的备份为
`data/backups/future_simulation.json`；数据库名、连接地址、备份恢复与集合
说明见 [docs/guides/backend.md](docs/guides/backend.md)。

事件知识图谱以 Neo4j 为主存储：

```powershell
# 可选：启动仓库自带的 Neo4j 5.26（未启动时后端自动回退到 graph.json 快照）
docker compose -f pipelines/kg/docker-compose.yml up -d

# 首次导入历史事件图谱（后端也会在 Neo4j 为空时自动导入）
py -3 backend/scripts/seed_knowledge_graph.py
```

每次策略运行结束后，后端会判断事件是否已存在，新事件自动抽取并写入
Neo4j；Neo4j 不可用时先写入 `var/knowledge_graph/graph.json` 本地快照，
页面仍可查看，Neo4j 恢复后自动补录。

运行完整仿真实验需要配置 `DEEPSEEK_API_KEY`：

```powershell
py -3 backend/scripts/run_simulation.py
```

`run_simulation.py` 使用 `configs/strategies/official_response_options.json`
的严格四方案配置：运行前必须把 `response_plan_1`～`response_plan_3` 与
`custom` 四个方案的公告都填写完整（`custom` 默认留空，留空会直接报错），
并保证文件的 `event_id` 与当前默认事件一致。只做交互式推演时，也可以从
控制台创建单方案会话，由 Web 输入层用占位公告跳过未填写的方案。

后端目录结构、迁移对照与接口说明见 [docs/guides/backend.md](docs/guides/backend.md)；
全部文档索引见 [docs/README.md](docs/README.md)。