# 运行与排错手册

## 环境准备

当前验证环境使用Conda环境`persona_sim`。在项目根目录执行：

```powershell
conda activate persona_sim
python demo\main.py
```

正式交接前需要补充可复现依赖清单，并将LLM密钥放入本地环境变量，不得写入或发送到代码仓库。

## 更换测试事件

1. 修改`demo/event_example.json`。
2. 修改`demo/official_response_options.json`。
3. 确认两个文件的`event_id`完全一致。
4. 保持Agent数、轮数、增量评论数和随机种子不变，再进行跨事件性能比较。

## 输出位置

每次运行会创建新的：

```text
demo/experiments/<event_id>_<timestamp>/
```

重点查看：

- `experiment_result.json`：总体结果、策略比较和性能摘要；
- 各策略目录中的状态和逐轮指标；
- `comment_quality`和`data_quality`：LLM评论及兜底情况；
- `performance`：阶段耗时和分类LLM请求。

## 常见状态

| 状态 | 含义 |
| --- | --- |
| `completed` | 应运行的策略均成功完成 |
| `completed_with_pending` | 应运行策略全部完成，空公告的`custom`策略等待填写 |
| `partial_failed` | 部分策略失败 |
| `failed` | 所有策略失败或关键流程失败 |
| `not_run` | 动态进场条件始终未触发，或空公告`custom`策略未参与对照 |
| `normal` | 评论兜底未触发质量告警 |
| `degraded` | 实验完成，但部分轮次历史兜底较多 |
| `emergency` | 使用了本地应急评论，结果需谨慎解释 |

## 进场原因

| 值 | 含义 |
| --- | --- |
| `negative_threshold` | Agent负面率达到当前阈值 |
| `global_worsening` | LLM全局趋势判断为恶化 |
| `stagnation` | 舆情连续多轮没有明显改善 |

## 未运行原因

| 值 | 含义 |
| --- | --- |
| `official_response_not_triggered` | 共享基线结束仍未触发官方进场 |
| `custom_statement_empty` | `custom`策略的公告内容为空，等待填写后重新运行 |

## 最小交接检查

新成员首次接手时应依次完成：

1. `python -m compileall -q demo`；
2. 校验两个输入JSON的`event_id`；
3. 使用小规模参数完成一次运行；
4. 确认生成新实验目录且没有覆盖旧批次；
5. 确认结果中包含策略状态、数据质量和性能摘要。

## Web 输入与会话 API

本仓库只启动后端 API：

```powershell
& .\.venv\Scripts\python.exe demo\api_server.py
```

默认服务地址为 `http://127.0.0.1:8770`。事件、公告内容、策略选择和
暂停/继续/回滚/重启接口说明见 [`WEB_API.md`](./WEB_API.md)。

V1/V2 前端源码已迁移到独立项目，启动方式：

```powershell
cd D:\Simulation2-frontend
pnpm run dev
```

浏览器访问 `http://127.0.0.1:5173`。Vite 会把 `/api` 请求代理到后端。

会话控制补充规则：

- 不回应策略不运行进场前基线，启动后直接从第 1 轮进入控制场景；
- 重启新批次成功后会更新页面中的会话编号和 URL 哈希；
- 重启只创建新批次，不覆盖旧实验目录。

