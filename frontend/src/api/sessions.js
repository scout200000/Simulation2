/**
 * 推演会话接口。
 *
 * 对应后端 `backend/app/api/routes/sessions`：
 * `GET  /api/sessions`
 * `POST /api/sessions`
 * `GET  /api/sessions/{id}`
 * `POST /api/sessions/{id}/{action}`
 *
 * action 取值：start / step / continue / pause / resume /
 * rollback / restart / run / announcement。
 */

import { apiDelete, apiGet, apiPost } from "./client.js";

function sessionPath(experimentId) {
  return `/api/sessions/${encodeURIComponent(experimentId)}`;
}

export function listSessions() {
  return apiGet("/api/sessions");
}

export function createSession(payload = {}) {
  return apiPost("/api/sessions", payload);
}

export function getSession(experimentId) {
  return apiGet(sessionPath(experimentId));
}

export function runSessionAction(experimentId, action, payload = {}) {
  return apiPost(`${sessionPath(experimentId)}/${action}`, payload);
}

export function startSession(experimentId) {
  return runSessionAction(experimentId, "start");
}

export function stepSession(experimentId) {
  return runSessionAction(experimentId, "step");
}

export function continueSession(experimentId) {
  return runSessionAction(experimentId, "continue");
}

export function pauseSession(experimentId) {
  return runSessionAction(experimentId, "pause");
}

export function resumeSession(experimentId) {
  return runSessionAction(experimentId, "resume");
}

export function rollbackSession(experimentId, steps = 1) {
  return runSessionAction(experimentId, "rollback", { steps });
}

export function restartSession(experimentId) {
  return runSessionAction(experimentId, "restart");
}

export function runAllStrategies(experimentId) {
  return runSessionAction(experimentId, "run");
}

export function addAnnouncement(experimentId, payload = {}) {
  return runSessionAction(experimentId, "announcement", payload);
}

export function deleteSession(experimentId) {
  return apiDelete(sessionPath(experimentId));
}
