/** 前端 API 请求底座：统一拼接基址、序列化请求体并抛出后端错误。 */
export function apiUrl(path) {
  const base = (globalThis.SIMULATION_API_BASE || "").replace(/\/$/, "");
  return `${base}${path}`;
}

export async function apiRequest(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });
  const payload = await response.json();
  if (!response.ok || payload?.error) {
    throw new Error(payload?.error || `HTTP ${response.status}`);
  }
  return payload;
}

export function apiGet(path) {
  return apiRequest(path);
}

export function apiPost(path, body = {}) {
  return apiRequest(path, {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function apiDelete(path) {
  return apiRequest(path, { method: "DELETE" });
}
