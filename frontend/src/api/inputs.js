/**
 * 输入准备接口。
 *
 * 对应后端 `backend/app/api/routes/inputs`：
 * `GET  /api/input/defaults`
 * `POST /api/input/preview`
 */

import { apiGet, apiPost } from "./client.js";

export function getInputDefaults() {
  return apiGet("/api/input/defaults");
}

export function previewInputs(payload = {}) {
  return apiPost("/api/input/preview", payload);
}
