/**
 * 历史事件知识图谱接口。
 *
 * 对应后端 `backend/app/api/routes/knowledge_graph`：
 * `GET /api/knowledge-graph`
 */

import { apiGet } from "./client.js";

export function getKnowledgeGraph() {
  return apiGet("/api/knowledge-graph");
}
