/**
 * 报告接口。
 *
 * 对应后端 `backend/app/api/routes/reports`：
 * `GET  /api/sessions/{id}/report`
 * `POST /api/sessions/{id}/report`
 * `GET  /api/sessions/{id}/report.pdf`
 */

import { apiGet, apiPost, apiUrl } from "./client.js";

function reportPath(experimentId) {
  return `/api/sessions/${encodeURIComponent(experimentId)}/report`;
}

function reportPdfPath(experimentId) {
  return `${reportPath(experimentId)}.pdf`;
}

export function getSessionReport(experimentId) {
  return apiGet(reportPath(experimentId));
}

export function generateSessionReport(experimentId) {
  return apiPost(reportPath(experimentId));
}

export async function downloadSessionReportPdf(experimentId) {
  const response = await fetch(apiUrl(reportPdfPath(experimentId)));
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.error) message = payload.error;
    } catch {
      // 非 JSON 错误体：保留状态码提示。
    }
    throw new Error(message);
  }
  return response.blob();
}
