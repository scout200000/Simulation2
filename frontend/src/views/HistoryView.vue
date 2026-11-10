<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { deleteSession, listSessions } from "../api/sessions.js";

const router = useRouter();
const sessions = ref([]);
const loading = ref(false);
const error = ref("");
const keyword = ref("");
const statusFilter = ref("all");
const page = ref(1);
const pageSize = ref(10);
const deleteTarget = ref(null);
const deleting = ref(false);
const deleteError = ref("");

const statusLabels = {
  created: "已创建",
  ready: "待运行",
  running: "运行中",
  all_running: "全部运行中",
  completed: "已完成",
  completed_no_entry: "未进场",
  completed_with_pending: "待补公告",
  partial_failed: "部分失败",
  failed: "失败",
  not_run: "未运行"
};

const phaseLabels = {
  created: "已创建",
  ready: "待运行",
  baseline: "进场前基线",
  scenario: "策略运行",
  all_running: "策略运行",
  drafts_running: "草稿运行",
  completed: "已完成",
  not_run: "未运行"
};

const strategyLabels = {
  __all__: "全部策略",
  __drafts__: "全部草稿",
  no_response: "不回应",
  fact_report: "事实通报",
  empathy: "共情安抚",
  rumor_clarification: "辟谣澄清",
  handling_progress: "处置进展",
  custom: "自定义"
};

function sessionStatus(session) {
  if (session.status === "running" && session.paused) return "paused";
  return session.status || "not_run";
}

function statusText(session) {
  const status = sessionStatus(session);
  return status === "paused" ? "已暂停" : (statusLabels[status] || status || "—");
}

function statusTone(session) {
  const status = sessionStatus(session);
  if (status === "completed") return "success";
  if (["failed", "partial_failed"].includes(status)) return "danger";
  if (["not_run", "completed_no_entry"].includes(status)) return "muted";
  if (status === "paused") return "warning";
  return "active";
}

function strategyText(session) {
  if (session.selected_strategy_id === "__drafts__") {
    return `全部草稿（${session.draft_count || 0}）`;
  }
  return strategyLabels[session.selected_strategy_id] ||
    session.selected_strategy_id ||
    "—";
}

function phaseText(session) {
  return phaseLabels[session.phase] || session.phase || "—";
}

function progress(session) {
  const total = Number(session.max_steps) || 10;
  const completed = Number(session.completed_step_count) || 0;
  return Math.min(100, Math.round(completed / total * 100));
}

function formatTime(session) {
  const match = String(session.experiment_id || "").match(
    /_(\d{8})_(\d{6})_/
  );
  if (!match) return "—";
  const [, date, time] = match;
  return `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)} ` +
    `${time.slice(0, 2)}:${time.slice(2, 4)}:${time.slice(4, 6)}`;
}

const filteredSessions = computed(() => {
  const search = keyword.value.trim().toLowerCase();
  return sessions.value
    .filter((session) => {
      if (statusFilter.value !== "all" && sessionStatus(session) !== statusFilter.value) {
        return false;
      }
      if (!search) return true;
      return [
        session.experiment_id,
        session.experiment_name,
        session.event_id,
        session.selected_strategy_id,
        session.status,
        session.phase
      ].some((value) => String(value || "").toLowerCase().includes(search));
    })
    .sort((left, right) =>
      String(right.experiment_id || "").localeCompare(String(left.experiment_id || ""))
    );
});

const totalPages = computed(() =>
  Math.max(1, Math.ceil(filteredSessions.value.length / pageSize.value))
);

const pagedSessions = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filteredSessions.value.slice(start, start + pageSize.value);
});

const summary = computed(() => {
  const count = (predicate) => sessions.value.filter(predicate).length;
  return {
    total: sessions.value.length,
    running: count((session) =>
      ["running", "all_running"].includes(session.status) && !session.paused
    ),
    completed: count((session) => session.status === "completed"),
    attention: count((session) =>
      ["failed", "partial_failed", "not_run", "completed_no_entry"].includes(session.status)
    )
  };
});

function openSession(session) {
  router.push({
    path: "/console",
    query: { session: session.experiment_id }
  });
}

function openReport(session) {
  router.push({
    path: "/report",
    query: { session: session.experiment_id }
  });
}

function canDelete(session) {
  return !(
    ["running", "all_running"].includes(session.status) && !session.paused
  );
}

function askDelete(session) {
  deleteError.value = "";
  deleteTarget.value = session;
}

function closeDelete() {
  if (deleting.value) return;
  deleteTarget.value = null;
  deleteError.value = "";
}

async function confirmDelete() {
  if (!deleteTarget.value) return;
  deleting.value = true;
  deleteError.value = "";
  try {
    await deleteSession(deleteTarget.value.experiment_id);
    deleteTarget.value = null;
    await loadSessions();
    if (page.value > totalPages.value) page.value = totalPages.value;
  } catch (deleteFailure) {
    deleteError.value = deleteFailure.message;
  } finally {
    deleting.value = false;
  }
}

async function loadSessions() {
  loading.value = true;
  error.value = "";
  try {
    const payload = await listSessions();
    sessions.value = Array.isArray(payload?.sessions) ? payload.sessions : [];
  } catch (loadError) {
    error.value = loadError.message;
  } finally {
    loading.value = false;
  }
}

watch([keyword, statusFilter], () => {
  page.value = 1;
});

watch(totalPages, (value) => {
  if (page.value > value) page.value = value;
});

onMounted(loadSessions);
</script>

<template>
  <main class="history-page">
    <header class="history-header">
      <div class="history-title-group">
        <RouterLink class="history-back" to="/workspace">← 返回工作台</RouterLink>
        <div>
          <p class="history-eyebrow">SESSION ARCHIVE</p>
          <h1>历史记录</h1>
        </div>
      </div>
      <button class="refresh-button" type="button" :disabled="loading" @click="loadSessions">
        {{ loading ? "加载中" : "刷新" }}
      </button>
    </header>

    <section class="history-summary" aria-label="历史记录统计">
      <article>
        <span>全部会话</span>
        <strong>{{ summary.total }}</strong>
      </article>
      <article>
        <span>运行中</span>
        <strong>{{ summary.running }}</strong>
      </article>
      <article>
        <span>已完成</span>
        <strong>{{ summary.completed }}</strong>
      </article>
      <article>
        <span>需要关注</span>
        <strong>{{ summary.attention }}</strong>
      </article>
    </section>

    <section class="history-panel">
      <div class="history-toolbar">
        <label class="search-field">
          <span>搜索</span>
          <input
            v-model="keyword"
            type="search"
            placeholder="事件、策略或实验编号"
          >
        </label>
        <label class="filter-field">
          <span>状态</span>
          <select v-model="statusFilter">
            <option value="all">全部状态</option>
            <option value="running">运行中</option>
            <option value="paused">已暂停</option>
            <option value="created">已创建</option>
            <option value="completed">已完成</option>
            <option value="completed_no_entry">未进场</option>
            <option value="not_run">未运行</option>
            <option value="failed">失败</option>
            <option value="partial_failed">部分失败</option>
          </select>
        </label>
        <span class="result-count">{{ filteredSessions.length }} 条记录</span>
      </div>

      <div v-if="error" class="history-message error">{{ error }}</div>

      <div class="history-table-wrap">
        <table class="history-table">
          <thead>
            <tr>
              <th>实验名称</th>
              <th>策略</th>
              <th>阶段</th>
              <th>进度</th>
              <th>状态</th>
              <th>时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody v-if="!loading && pagedSessions.length">
            <tr v-for="session in pagedSessions" :key="session.experiment_id">
              <td data-label="实验名称">
                <strong class="experiment-name" :title="session.experiment_id">
                  {{ session.experiment_name || session.experiment_id }}
                </strong>
              </td>
              <td data-label="策略">{{ strategyText(session) }}</td>
              <td data-label="阶段">
                <span>{{ phaseText(session) }}</span>
                <small>
                  第 {{ session.current_step || 0 }}/{{ session.max_steps || 10 }} 轮
                </small>
              </td>
              <td data-label="进度">
                <div class="progress-cell">
                  <span><i :style="{ width: progress(session) + '%' }"></i></span>
                  <small>{{ progress(session) }}%</small>
                </div>
              </td>
              <td data-label="状态">
                <span class="status-pill" :class="statusTone(session)">
                  {{ statusText(session) }}
                </span>
              </td>
              <td data-label="时间">{{ formatTime(session) }}</td>
              <td data-label="操作">
                <div class="row-actions">
                  <button type="button" @click="openSession(session)">打开控制台</button>
                  <button type="button" @click="openReport(session)">报告</button>
                  <button
                    class="danger"
                    type="button"
                    :disabled="!canDelete(session)"
                    :title="canDelete(session) ? '删除该实验批次' : '运行中的批次不能删除，请先暂停'"
                    @click="askDelete(session)"
                  >删除</button>
                </div>
              </td>
            </tr>
          </tbody>
          <tbody v-else-if="loading">
            <tr v-for="row in 5" :key="row" class="skeleton-row">
              <td v-for="column in 7" :key="column"><span></span></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!loading && !pagedSessions.length" class="history-message">
          没有符合条件的历史记录
        </div>
      </div>

      <footer class="history-pagination">
        <button type="button" :disabled="page <= 1" @click="page -= 1">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button type="button" :disabled="page >= totalPages" @click="page += 1">下一页</button>
      </footer>
    </section>

    <div
      v-if="deleteTarget"
      class="history-dialog-backdrop"
      @click.self="closeDelete"
    >
      <div class="history-dialog" role="dialog" aria-modal="true" aria-label="删除实验批次">
        <p class="history-eyebrow">DELETE SESSION</p>
        <h2>删除实验批次？</h2>
        <p class="history-dialog-name">{{ deleteTarget.experiment_name }}</p>
        <p class="history-dialog-hint">
          批次目录、已生成的报告和运行状态会一并移除，且不可恢复。
        </p>
        <p v-if="deleteError" class="history-dialog-error">{{ deleteError }}</p>
        <div class="history-dialog-actions">
          <button type="button" :disabled="deleting" @click="closeDelete">取消</button>
          <button
            class="danger"
            type="button"
            :disabled="deleting"
            @click="confirmDelete"
          >{{ deleting ? "删除中…" : "确认删除" }}</button>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.history-page {
  min-height: 100vh;
  padding-bottom: 42px;
  color: var(--ink, #15211d);
  background:
    radial-gradient(1100px 620px at 94% -14%, rgba(23, 127, 111, .12), transparent 62%),
    radial-gradient(760px 500px at -10% 110%, rgba(23, 127, 111, .07), transparent 58%),
    #fff;
  font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
}

.history-page * { box-sizing: border-box; }

/* ── 顶栏 ───────────────────────────────────────────────── */
.history-header {
  max-width: 1180px;
  margin: 0 auto;
  padding: 26px 28px 20px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
}

.history-title-group { display: grid; gap: 12px; }

.history-back {
  width: fit-content;
  color: var(--muted, #6a7a73);
  font-size: 10.5px;
  font-weight: 700;
  text-decoration: none;
}

.history-back:hover { color: var(--green-deep, #0f5f53); }

.history-eyebrow {
  margin: 0 0 5px;
  color: var(--green, #177f6f);
  font-size: 9.5px;
  font-weight: 800;
  letter-spacing: .16em;
}

.history-header h1 {
  margin: 0;
  font-size: clamp(26px, 3vw, 36px);
  font-weight: 800;
  letter-spacing: -.025em;
}

.refresh-button {
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--line-strong, #d8e2db);
  border-radius: 9px;
  color: var(--ink, #15211d);
  background: #fff;
  font: inherit;
  font-size: 10.5px;
  font-weight: 700;
  cursor: pointer;
}

.refresh-button:hover:not(:disabled) {
  color: var(--green-deep, #0f5f53);
  border-color: #bcd6cb;
  background: #f5fbf8;
}

button:disabled { cursor: not-allowed; opacity: .45; }

/* ── 统计 ───────────────────────────────────────────────── */
.history-summary {
  max-width: 1180px;
  margin: 0 auto 14px;
  padding: 0 28px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.history-summary article {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--line, #e8ede9);
  border-radius: 13px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(21, 33, 29, .03);
}

.history-summary span { color: var(--muted, #6a7a73); font-size: 10px; }
.history-summary strong {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -.02em;
  font-variant-numeric: tabular-nums;
}

/* ── 主面板 ─────────────────────────────────────────────── */
.history-panel {
  max-width: 1180px;
  margin: 0 auto;
  border: 1px solid var(--line, #e8ede9);
  border-radius: 18px;
  background: #fff;
  box-shadow: var(--shadow, 0 1px 2px rgba(21,33,29,.04), 0 16px 40px rgba(21,33,29,.05));
  overflow: hidden;
}

.history-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px auto;
  align-items: end;
  gap: 14px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--line, #e8ede9);
  background: #fcfefd;
}

.search-field,
.filter-field { display: grid; gap: 6px; }

.search-field span,
.filter-field span {
  color: var(--muted, #6a7a73);
  font-size: 9.5px;
  font-weight: 700;
}

.search-field input,
.filter-field select {
  width: 100%;
  height: 36px;
  padding: 0 11px;
  border: 1px solid #dfe7e2;
  border-radius: 9px;
  outline: none;
  color: var(--ink, #15211d);
  background: #fff;
  font: inherit;
  font-size: 11px;
}

.search-field input:focus,
.filter-field select:focus {
  border-color: var(--green, #177f6f);
  box-shadow: 0 0 0 3px rgba(23, 127, 111, .10);
}

.result-count { padding-bottom: 9px; color: var(--muted, #6a7a73); font-size: 10px; white-space: nowrap; }

/* ── 表格 ───────────────────────────────────────────────── */
.history-table-wrap { overflow-x: auto; }

.history-table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
  text-align: left;
}

.history-table th {
  padding: 11px 16px;
  border-bottom: 1px solid var(--line, #e8ede9);
  color: var(--faint, #93a19b);
  background: #fff;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: .10em;
  white-space: nowrap;
}

.history-table td {
  padding: 13px 16px;
  border-bottom: 1px solid #f0f4f1;
  color: var(--ink-soft, #33443d);
  font-size: 11px;
  vertical-align: middle;
}

.history-table tbody tr:hover td { background: #f8fcf9; }
.history-table tbody tr:last-child td { border-bottom: 0; }

.history-table td small { display: block; margin-top: 4px; color: var(--faint, #93a19b); font-size: 9.5px; }

.experiment-id,
.experiment-name {
  display: block;
  max-width: 260px;
  overflow: hidden;
  color: var(--ink, #15211d);
  font-size: 10.5px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-cell { display: flex; align-items: center; gap: 8px; min-width: 120px; }
.progress-cell > span {
  flex: 1;
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: #eef3ef;
}
.progress-cell i { display: block; height: 100%; border-radius: inherit; background: var(--green, #177f6f); }
.progress-cell small { margin: 0; color: var(--muted, #6a7a73); font-variant-numeric: tabular-nums; }

.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 9.5px;
  font-weight: 700;
  white-space: nowrap;
}

.status-pill.success { color: #1f6b4f; background: #e9f6ef; }
.status-pill.active { color: #146b5e; background: #e6f5f1; }
.status-pill.warning { color: #8a6420; background: #fbf2df; }
.status-pill.danger { color: #a7473c; background: #fdf0ee; }
.status-pill.muted { color: #6a7a73; background: #f2f5f3; }

.row-actions { display: flex; flex-wrap: wrap; gap: 6px; }

.row-actions button {
  height: 27px;
  padding: 0 10px;
  border: 1px solid var(--line-strong, #d8e2db);
  border-radius: 7px;
  color: var(--ink-soft, #33443d);
  background: #fff;
  font: inherit;
  font-size: 9.5px;
  font-weight: 700;
  cursor: pointer;
}

.row-actions button:hover {
  color: var(--green-deep, #0f5f53);
  border-color: #bcd6cb;
  background: #f5fbf8;
}

.history-message {
  padding: 26px 18px;
  color: var(--muted, #6a7a73);
  font-size: 11px;
  text-align: center;
}

.history-message.error { color: #a7473c; background: #fdf6f4; }

.skeleton-row td { padding: 16px; }
.skeleton-row span {
  display: block;
  height: 10px;
  border-radius: 999px;
  background: linear-gradient(90deg, #f1f5f2, #e7efea, #f1f5f2);
  background-size: 200% 100%;
  animation: history-shimmer 1.4s linear infinite;
}

/* ── 分页 ───────────────────────────────────────────────── */
.history-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 14px 18px;
  border-top: 1px solid var(--line, #e8ede9);
  color: var(--muted, #6a7a73);
  font-size: 10px;
}

.history-pagination button {
  height: 29px;
  padding: 0 12px;
  border: 1px solid var(--line-strong, #d8e2db);
  border-radius: 8px;
  color: var(--ink, #15211d);
  background: #fff;
  font: inherit;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
}

.history-pagination button:hover:not(:disabled) {
  color: var(--green-deep, #0f5f53);
  border-color: #bcd6cb;
  background: #f5fbf8;
}

@keyframes history-shimmer {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-row span { animation: none; }
}

@media (max-width: 1020px) {
  .history-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .history-toolbar { grid-template-columns: minmax(0, 1fr) minmax(0, 160px); }
  .result-count { grid-column: 1 / -1; padding-bottom: 0; }
}

@media (max-width: 700px) {
  .history-header { padding: 20px 16px 16px; align-items: flex-start; flex-direction: column; gap: 12px; }
  .history-summary { padding: 0 16px; gap: 10px; }
  .history-summary article { padding: 12px 14px; }
  .history-summary strong { font-size: 19px; }
  .history-panel { margin: 0 16px; }
  .history-toolbar { grid-template-columns: minmax(0, 1fr); padding: 14px; }
  .history-pagination { justify-content: space-between; padding: 12px 14px; }
}

/* 移动端：表格改为卡片列表 */
@media (max-width: 700px) {
  .history-table-wrap { overflow: visible; }
  .history-table { display: block; min-width: 0; }
  .history-table thead { display: none; }
  .history-table tbody { display: grid; gap: 10px; padding: 12px; }
  .history-table tr {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    padding: 14px;
    border: 1px solid var(--line, #e8ede9);
    border-radius: 12px;
  }
  .history-table td { padding: 0; border: 0; font-size: 10.5px; }
  .history-table td::before {
    display: block;
    margin-bottom: 4px;
    color: var(--faint, #93a19b);
    font-size: 8px;
    font-weight: 800;
    letter-spacing: .08em;
    content: attr(data-label);
  }
  .history-table td:first-child,
  .history-table td:last-child { grid-column: 1 / -1; }
  .experiment-id,
  .experiment-name { max-width: none; white-space: normal; word-break: break-all; }
  .progress-cell { min-width: 0; }
  .row-actions button { height: 30px; }
  .skeleton-row { display: none; }
}

/* ── 删除确认 ───────────────────────────────────────────── */
.history-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(21, 33, 29, .42);
  backdrop-filter: blur(3px);
}

.history-dialog {
  width: min(420px, 100%);
  padding: 26px 26px 22px;
  border: 1px solid var(--line, #e8ede9);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 30px 80px rgba(21, 33, 29, .22);
}

.history-dialog h2 {
  margin: 8px 0 10px;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -.02em;
}

.history-dialog-name {
  margin: 0 0 6px;
  color: var(--ink, #15211d);
  font-size: 12px;
  font-weight: 700;
}

.history-dialog-hint {
  margin: 0;
  color: var(--muted, #6a7a73);
  font-size: 11px;
  line-height: 1.7;
}

.history-dialog-error {
  margin: 10px 0 0;
  padding: 8px 10px;
  border-radius: 8px;
  color: #a7473c;
  background: #fdf1ef;
  font-size: 10.5px;
}

.history-dialog-actions {
  margin-top: 18px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.history-dialog-actions button {
  height: 34px;
  padding: 0 14px;
  border: 1px solid var(--line-strong, #d8e2db);
  border-radius: 8px;
  color: var(--ink, #15211d);
  background: #fff;
  font: inherit;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

.history-dialog-actions button.danger {
  border-color: #c26055;
  color: #fff;
  background: #b0544a;
}

.history-dialog-actions button.danger:hover:not(:disabled) {
  background: #9a463d;
}

.history-dialog-actions button:disabled {
  cursor: not-allowed;
  opacity: .55;
}

.row-actions button.danger {
  color: #a7473c;
  border-color: #eccfca;
  background: #fff8f6;
}

.row-actions button.danger:hover:not(:disabled) {
  color: #fff;
  border-color: #b0544a;
  background: #b0544a;
}
</style>
