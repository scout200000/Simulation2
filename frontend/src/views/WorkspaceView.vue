<script setup>
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { getAuthSession, signOut } from "../core/auth.js";
import { listSessions } from "../api/sessions.js";

const router = useRouter();
const account = computed(() => getAuthSession()?.account || "用户");
const greeting = computed(() => {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
});
const today = computed(() =>
  new Date().toLocaleDateString("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long"
  })
);

const recentSessions = ref([]);

const STATUS_LABELS = {
  running: "运行中",
  paused: "已暂停",
  created: "已创建",
  completed: "已完成",
  completed_no_entry: "未进场",
  not_run: "未运行",
  failed: "失败",
  partial_failed: "部分失败"
};

function statusLabel(session) {
  if (session.status === "running" && session.paused) return "已暂停";
  return STATUS_LABELS[session.status] || session.status || "未知";
}

function statusTone(session) {
  if (session.status === "completed") return "success";
  if (["failed", "partial_failed"].includes(session.status)) return "danger";
  if (session.status === "paused" || (session.status === "running" && session.paused)) return "warning";
  if (session.status === "running") return "active";
  return "muted";
}

async function loadRecentSessions() {
  try {
    const data = await listSessions();
    const sessions = [...(data.sessions || [])];
    sessions.sort((left, right) => {
      const leftTime = Number(left.created_at) || 0;
      const rightTime = Number(right.created_at) || 0;
      if (leftTime !== rightTime) return rightTime - leftTime;
      return String(right.experiment_id || "").localeCompare(
        String(left.experiment_id || "")
      );
    });
    recentSessions.value = sessions.slice(0, 3);
  } catch {
    recentSessions.value = [];
  }
}

function logout() {
  signOut();
  router.replace({ name: "portal" });
}

onMounted(loadRecentSessions);
</script>

<template>
  <main class="workspace-page">
    <header class="ws-header">
      <RouterLink class="ws-brand" to="/workspace">
        <span class="brand-mark">舆</span>
        <span class="brand-text">
          <strong>Simulation2</strong>
          <small>舆情推演控制台</small>
        </span>
      </RouterLink>

      <div class="ws-actions">
        <span class="ws-date">{{ today }}</span>
        <RouterLink class="ws-link" to="/">项目首页</RouterLink>
        <RouterLink class="ws-link" to="/settings">个人设置</RouterLink>
        <span class="ws-account">{{ account }}</span>
        <button class="btn btn-ghost" type="button" @click="logout">退出</button>
      </div>
    </header>

    <section class="ws-intro">
      <span class="eyebrow">WORKSPACE SELECT</span>
      <h1>{{ greeting }}，{{ account }}</h1>
      <p>选择一个工作区继续：进入实时推演、复盘历史会话，或查看关系型知识图谱。</p>
    </section>

    <section class="ws-grid" aria-label="工作区选择">
      <RouterLink class="ws-card is-primary" to="/console">
        <header class="ws-card-head">
          <span class="ws-card-eyebrow">LIVE SIMULATION</span>
          <span class="ws-badge">推荐</span>
        </header>

        <div class="ws-visual" aria-hidden="true">
          <svg viewBox="0 0 320 150" preserveAspectRatio="none">
            <line x1="42" y1="82" x2="104" y2="42" />
            <line x1="42" y1="82" x2="112" y2="116" />
            <line x1="104" y1="42" x2="180" y2="68" />
            <line x1="112" y1="116" x2="180" y2="68" />
            <line x1="180" y1="68" x2="250" y2="34" />
            <line x1="180" y1="68" x2="278" y2="104" />
            <circle cx="42" cy="82" r="5" />
            <circle cx="104" cy="42" r="4" />
            <circle cx="112" cy="116" r="4" />
            <circle class="hub" cx="180" cy="68" r="7" />
            <circle cx="250" cy="34" r="4" />
            <circle cx="278" cy="104" r="5" />
          </svg>
        </div>

        <div class="ws-card-copy">
          <h2>实时推演控制台</h2>
          <p>输入事件与官方公告，观察 Agent 网络、指标趋势和舆论结构逐轮演化。</p>
        </div>

        <footer class="ws-card-foot">
          <span>30 Agent · 10 轮</span>
          <span class="ws-go">进入控制台 →</span>
        </footer>
      </RouterLink>

      <RouterLink class="ws-card" to="/history">
        <header class="ws-card-head">
          <span class="ws-card-eyebrow">SESSION ARCHIVE</span>
        </header>

        <div class="ws-visual is-bars" aria-hidden="true">
          <div class="ws-bars">
            <i v-for="height in [34, 58, 44, 76, 62, 88, 70]" :key="height" :style="{ height: height + '%' }"></i>
          </div>
        </div>

        <div class="ws-card-copy">
          <h2>历史会话记录</h2>
          <p>筛选、检查并重新打开过去的推演批次，继续运行或对比策略状态。</p>
        </div>

        <footer class="ws-card-foot">
          <span>会话归档 · 报告</span>
          <span class="ws-go">查看历史 →</span>
        </footer>
      </RouterLink>

      <RouterLink class="ws-card" to="/graph">
        <header class="ws-card-head">
          <span class="ws-card-eyebrow">KNOWLEDGE GRAPH</span>
        </header>

        <div class="ws-visual is-graph" aria-hidden="true">
          <svg viewBox="0 0 320 320" preserveAspectRatio="xMidYMid meet">
            <line x1="160" y1="160" x2="86" y2="86" />
            <line x1="160" y1="160" x2="246" y2="74" />
            <line x1="160" y1="160" x2="70" y2="232" />
            <line x1="160" y1="160" x2="248" y2="238" />
            <line x1="160" y1="160" x2="160" y2="52" />
            <line x1="86" y1="86" x2="160" y2="52" />
            <line x1="246" y1="74" x2="248" y2="238" />
            <line x1="70" y1="232" x2="248" y2="238" />
            <circle class="hub" cx="160" cy="160" r="15" />
            <circle cx="86" cy="86" r="7" />
            <circle cx="246" cy="74" r="7" />
            <circle cx="70" cy="232" r="7" />
            <circle cx="248" cy="238" r="7" />
            <circle cx="160" cy="52" r="6" />
          </svg>
        </div>

        <div class="ws-card-copy">
          <h2>知识图谱</h2>
          <p>汇总全部历史事件，按共享议题、主体与地域查看事件之间的关联。</p>
        </div>

        <footer class="ws-card-foot">
          <span>事件 · Agent · 评论</span>
          <span class="ws-go">查看图谱 →</span>
        </footer>
      </RouterLink>
    </section>

    <section v-if="recentSessions.length" class="ws-recent" aria-label="最近会话">
      <header>
        <span class="eyebrow">RECENT SESSIONS</span>
        <RouterLink to="/history">查看全部 →</RouterLink>
      </header>
      <div class="ws-recent-list">
        <RouterLink
          v-for="item in recentSessions"
          :key="item.experiment_id"
          class="ws-recent-item"
          :to="{ path: '/console', query: { session: item.experiment_id } }"
        >
          <span class="ws-recent-id" :title="item.experiment_id">
            {{ item.experiment_name || item.experiment_id }}
          </span>
          <span class="ws-recent-meta">
            <i :class="statusTone(item)"></i>
            {{ statusLabel(item) }} · {{ item.current_step || 0 }}/{{ item.max_steps || 10 }} 轮
          </span>
          <span class="ws-recent-go">继续 →</span>
        </RouterLink>
      </div>
    </section>

    <footer class="ws-footer">
      <span class="ws-status"><i></i>本地服务可用</span>
      <span>控制台 · 单屏模式</span>
      <span>Research simulation workspace</span>
    </footer>
  </main>
</template>

<style src="../styles/workspace.css"></style>
