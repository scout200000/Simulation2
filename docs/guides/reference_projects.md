# 参考工程（third_party/）

`third_party/` 保存从旧仓库 `other` 目录迁移来的参考工程，仅用于对照和
查阅，**不参与本项目运行**，也不属于后端依赖：

| 目录 | 内容 |
| --- | --- |
| `agentsociety2/` | AgentSociety2 参考实现（Agent 技能、环境与示例） |
| `oasis-master/` | OASIS 多智能体社会模拟参考实现及技术方案 |
| `TrendSim/` | 趋势模拟参考工程 |

这些目录保留各自的 README、依赖清单和许可证声明，未改写代码路径，也未纳入
`backend/` 的导入体系。需要复用其中的能力时，应先在 `backend/app` 中实现
适配层，而不是直接从 `third_party/` 导入。
