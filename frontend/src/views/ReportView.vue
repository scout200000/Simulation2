<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import {
  downloadSessionReportPdf,
  generateSessionReport,
  getSessionReport
} from "../api/reports.js";

const route = useRoute();
const sessionId = computed(() => String(route.query.session || ""));
const status = ref("idle");
const error = ref("");
const report = ref(null);
const pdfBusy = ref(false);
const pdfError = ref("");
let pollTimer = null;

const chartWidth = 760;
const chartHeight = 260;
const chartMargin = { left: 54, right: 20, top: 26, bottom: 42 };
const chartInnerWidth = chartWidth - chartMargin.left - chartMargin.right;
const chartInnerHeight = chartHeight - chartMargin.top - chartMargin.bottom;

const series = [
  { key: "negative", label: "负面", color: "#b0544a" },
  { key: "neutral", label: "中性", color: "#93a19b" },
  { key: "positive", label: "正面", color: "#177f6f" }
];

const trend = computed(() => report.value?.sentiment_trend || []);
const bestAnnouncement = computed(() => {
  const current = report.value;
  if (!current?.summary) return null;
  return (
    (current.announcements || []).find(
      (item) => item.id === current.summary.best_announcement_id
    ) || null
  );
});
const hasDimensions = computed(() =>
  (report.value?.announcements || []).some(
    (item) => Array.isArray(item.score?.dimensions) && item.score.dimensions.length
  )
);

const trendChart = computed(() => {
  if (!trend.value.length) {
    return { xLabels: [], grid: [], series: [] };
  }
  return {
    xLabels: trend.value.map((item) => ({
      round: item.round,
      x: chartX(item.round)
    })),
    grid: [0, 0.25, 0.5, 0.75, 1].map((value) => ({
      value,
      y: chartY(value)
    })),
    series: series.map((item) => ({
      ...item,
      points: trend.value
        .map((entry) => `${chartX(entry.round)},${chartY(entry[item.key])}`)
        .join(" "),
      dots: trend.value.map((entry) => ({
        round: entry.round,
        value: entry[item.key],
        x: chartX(entry.round),
        y: chartY(entry[item.key])
      }))
    }))
  };
});

const scoreRanking = computed(() =>
  (report.value?.announcements || []).map((item) => ({
    ...item,
    width: `${item.score?.total ?? 0}%`
  }))
);

function chartX(round) {
  return (
    chartMargin.left +
    ((round - 1) / Math.max(trend.value.length - 1, 1)) * chartInnerWidth
  );
}

function chartY(value) {
  return chartMargin.top + (1 - value) * chartInnerHeight;
}

function percent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "—";
}

function scoreTone(score) {
  if (score >= 86) return "#177f6f";
  if (score >= 80) return "#b98a4b";
  return "#b0544a";
}

function scoreStyle(score) {
  return {
    "--score": score,
    "--score-angle": `${score * 3.6}deg`,
    "--score-color": scoreTone(score)
  };
}

function scoreBars(item) {
  const dimensions = item.score?.dimensions;
  if (Array.isArray(dimensions) && dimensions.length) {
    return dimensions.map((dimension) => ({
      name: dimension.name,
      score: dimension.score,
      percent: Math.min(100, Math.max(0, (dimension.score / 20) * 100))
    }));
  }
  const rounds = item.score?.rounds || [];
  const average = (field) => {
    if (!rounds.length) return 0;
    const total = rounds.reduce(
      (sum, row) => sum + Number(row[field] || 0),
      0
    );
    return total / rounds.length;
  };
  return [
    {
      name: "评论情绪分",
      score: Math.round(average("comment_score")),
      percent: average("comment_score")
    },
    {
      name: "官方态度分",
      score: Math.round(average("attitude_score")),
      percent: average("attitude_score")
    }
  ];
}

function wordStyle(item, index) {
  const palette = {
    negative: "#b0544a",
    neutral: "#756d5f",
    positive: "#177f6f"
  };
  return {
    fontSize: `${14 + item.weight * 0.16}px`,
    color: palette[item.tone] || palette.neutral,
    opacity: 0.72 + item.weight / 360,
    transform: `rotate(${[-4, 2, -1, 3, -2, 1][index % 6]}deg)`
  };
}

function emotionLabel(emotion) {
  return {
    negative: "负面",
    neutral: "中性",
    positive: "正面"
  }[emotion] || emotion;
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePoll() {
  stopPolling();
  pollTimer = setTimeout(pollReport, 1500);
}

async function pollReport() {
  if (status.value !== "generating" || !sessionId.value) return;
  try {
    const data = await getSessionReport(sessionId.value);
    report.value = data.report || report.value;
    status.value = data.status || "generating";
    if (status.value === "generating") {
      schedulePoll();
    } else if (status.value === "failed") {
      error.value = data.error || "报告生成失败";
    }
  } catch (pollError) {
    status.value = "failed";
    error.value = pollError.message;
  }
}

async function loadReport() {
  stopPolling();
  report.value = null;
  error.value = "";
  if (!sessionId.value) {
    status.value = "no-session";
    return;
  }
  status.value = "loading";
  try {
    const data = await getSessionReport(sessionId.value);
    report.value = data.report || null;
    status.value = data.status || (data.report ? "ready" : "missing");
    if (status.value === "generating") schedulePoll();
  } catch (loadError) {
    const message = String(loadError.message || "");
    if (/404|not found/i.test(message)) {
      status.value = "unsupported";
      error.value = "当前后端还没有报告接口，请重启后端服务后重试。";
      return;
    }
    status.value = "failed";
    error.value = message;
  }
}

async function generateReport() {
  if (!sessionId.value || status.value === "generating") return;
  stopPolling();
  error.value = "";
  status.value = "generating";
  try {
    const data = await generateSessionReport(sessionId.value);
    report.value = data.report || report.value;
    status.value = data.status || "generating";
    if (status.value === "generating") schedulePoll();
  } catch (generateError) {
    const message = String(generateError.message || "");
    if (/404|not found/i.test(message)) {
      status.value = "unsupported";
      error.value = "当前后端还没有报告接口，请重启后重试。";
      return;
    }
    status.value = "failed";
    error.value = message;
  }
}

async function downloadPdf() {
  if (!sessionId.value || pdfBusy.value) return;
  pdfBusy.value = true;
  pdfError.value = "";
  try {
    const blob = await downloadSessionReportPdf(sessionId.value);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${sessionId.value}-report.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1500);
  } catch (downloadError) {
    pdfError.value = downloadError.message || "PDF 下载失败";
  } finally {
    pdfBusy.value = false;
  }
}

onMounted(loadReport);
watch(sessionId, loadReport);
onBeforeUnmount(stopPolling);
</script>

<template>
  <main class="report-page">
    <header class="report-topbar">
      <RouterLink class="report-brand" to="/workspace">
        <span>舆</span>
        <div>
          <strong>Simulation2</strong>
          <small>舆情推演报告</small>
        </div>
      </RouterLink>

      <nav class="report-nav" aria-label="报告导航">
        <span>WEB REPORT</span>
        <RouterLink to="/workspace">工作台</RouterLink>
        <RouterLink to="/console">返回控制台</RouterLink>
      </nav>
    </header>

    <div class="report-shell">
      <section v-if="status === 'loading'" class="report-state">
        <div class="report-state-card">
          <p>LOADING REPORT</p>
          <h2>正在加载报告</h2>
          <span>正在读取会话的推演结果与评分数据…</span>
        </div>
      </section>

      <section v-else-if="status === 'no-session'" class="report-state">
        <div class="report-state-card">
          <p>REPORT</p>
          <h2>还没有选择会话</h2>
          <span>请从历史会话或控制台打开一个批次，再查看它的推演报告。</span>
          <div class="report-state-actions">
            <RouterLink class="report-state-link primary" to="/history">查看历史会话</RouterLink>
            <RouterLink class="report-state-link" to="/console">返回控制台</RouterLink>
          </div>
        </div>
      </section>

      <section v-else-if="status === 'missing'" class="report-state">
        <div class="report-state-card">
          <p>REPORT</p>
          <h2>这个会话还没有报告</h2>
          <div class="report-state-actions">
            <button class="report-state-link primary" type="button" @click="generateReport">生成报告</button>
            <RouterLink class="report-state-link" :to="{ path: '/console', query: { session: sessionId } }">返回控制台</RouterLink>
          </div>
        </div>
      </section>

      <section v-else-if="status === 'generating'" class="report-state">
        <div class="report-state-card">
          <p>GENERATING</p>
          <h2>正在生成报告</h2>
          <span>正在汇总逐轮指标、公告评分与高价值评论；启用模型分析时可能需要更久。</span>
          <div class="report-state-progress"><i></i></div>
        </div>
      </section>

      <section v-else-if="status === 'unsupported'" class="report-state">
        <div class="report-state-card error">
          <p>BACKEND UPDATE REQUIRED</p>
          <h2>后端还没有启用报告接口</h2>
          <span>报告现在由后端生成。请重启后端（或重新运行 start.py），再回到本页刷新。</span>
          <div class="report-state-actions">
            <button class="report-state-link primary" type="button" @click="loadReport">重新检查</button>
            <RouterLink class="report-state-link" :to="{ path: '/console', query: { session: sessionId } }">返回控制台</RouterLink>
          </div>
        </div>
      </section>

      <section v-else-if="status === 'failed'" class="report-state">
        <div class="report-state-card error">
          <p>REPORT ERROR</p>
          <h2>报告暂时不可用</h2>
          <span>{{ error || "生成报告时发生错误，请稍后重试。" }}</span>
          <div class="report-state-actions">
            <button class="report-state-link primary" type="button" @click="generateReport">重新生成</button>
            <RouterLink class="report-state-link" :to="{ path: '/console', query: { session: sessionId } }">返回控制台</RouterLink>
          </div>
        </div>
      </section>

      <template v-else-if="status === 'ready' && report">
      <div class="report-toolbar">
        <span>会话 {{ sessionId }}</span>
        <div>
          <span v-if="pdfError" class="report-pdf-error">{{ pdfError }}</span>
          <button
            type="button"
            class="report-pdf-button"
            :disabled="pdfBusy"
            @click="downloadPdf"
          >{{ pdfBusy ? "正在生成 PDF…" : "下载 PDF" }}</button>
          <button type="button" :disabled="status === 'generating'" @click="generateReport">重新生成</button>
          <RouterLink :to="{ path: '/console', query: { session: sessionId } }">返回控制台</RouterLink>
        </div>
      </div>
      <section class="report-cover">
        <div class="report-cover-copy">
          <p>PUBLIC OPINION SIMULATION REPORT</p>
          <h1>{{ report.title }}</h1>
          <span>{{ report.subtitle }}</span>
        </div>
        <div class="report-meta">
          <div>
            <span>报告编号</span>
            <strong>{{ report.report_id }}</strong>
          </div>
          <div>
            <span>生成时间</span>
            <strong>{{ report.generated_at }}</strong>
          </div>
          <div>
            <span>推演规模</span>
            <strong>{{ report.simulation.agent_count }} Agent · {{ report.simulation.rounds }} 轮</strong>
          </div>
          <div>
            <span>模型</span>
            <strong>{{ report.simulation.model }}</strong>
          </div>
        </div>
      </section>

      <section class="report-summary" aria-label="报告摘要">
        <article>
          <span>综合风险</span>
          <strong>{{ report.summary.risk_level }}</strong>
          <small>负面峰值 {{ percent(report.summary.peak_negative_rate) }}</small>
        </article>
        <article>
          <span>最终负面率</span>
          <strong>{{ percent(report.summary.final_negative_rate) }}</strong>
          <small>较峰值下降 {{ percent(report.summary.peak_negative_rate - report.summary.final_negative_rate) }}</small>
        </article>
        <article>
          <span>最佳公告</span>
          <strong>{{ bestAnnouncement?.name || '—' }}</strong>
          <small>总分 {{ report.summary.best_score }}</small>
        </article>
        <article>
          <span>官方进场</span>
          <strong>{{ bestAnnouncement?.score?.response_step ? `第 ${bestAnnouncement.score.response_step} 轮` : "未进场" }}</strong>
          <small>{{ report.simulation.rounds }} 轮推演 · {{ report.announcements.length }} 个公告方案</small>
        </article>
      </section>

      <section class="report-section event-section">
        <div class="section-heading">
          <div>
            <p>01 · EVENT</p>
            <h2>事件本身</h2>
          </div>
          <span v-if="report.event.time || report.event.location">{{ [report.event.time, report.event.location].filter(Boolean).join(" · ") }}</span>
        </div>

        <div class="event-layout">
          <div class="event-copy">
            <h3>{{ report.event.title }}</h3>
            <p>{{ report.event.content }}</p>
          </div>
          <aside class="event-labels">
            <span v-for="label in report.event.labels" :key="label">{{ label }}</span>
          </aside>
        </div>
      </section>

      <section class="analysis-grid">
        <article class="report-panel trend-panel">
          <div class="panel-heading">
            <div>
              <p>02 · TREND</p>
              <h2>情绪趋势</h2>
            </div>
            <div class="trend-legend">
              <span v-for="item in series" :key="item.key">
                <i :style="{ background: item.color }"></i>{{ item.label }}
              </span>
            </div>
          </div>

          <div class="trend-chart">
            <svg :viewBox="`0 0 ${chartWidth} ${chartHeight}`" role="img" aria-label="负面、中性和正面情绪趋势">
              <line
                v-for="line in trendChart.grid"
                :key="line.value"
                :x1="chartMargin.left"
                :x2="chartWidth - chartMargin.right"
                :y1="line.y"
                :y2="line.y"
                class="trend-grid-line"
              />
              <text
                v-for="line in trendChart.grid"
                :key="'label-' + line.value"
                :x="chartMargin.left - 10"
                :y="line.y + 4"
                class="trend-axis-label"
                text-anchor="end"
              >{{ Math.round(line.value * 100) }}%</text>
              <text
                v-for="item in trendChart.xLabels"
                :key="'round-' + item.round"
                :x="item.x"
                :y="chartHeight - 14"
                class="trend-axis-label"
                text-anchor="middle"
              >第{{ item.round }}轮</text>
              <g v-for="item in trendChart.series" :key="item.key">
                <polyline
                  :points="item.points"
                  fill="none"
                  :stroke="item.color"
                  stroke-width="2.8"
                  stroke-linejoin="round"
                  stroke-linecap="round"
                />
                <circle
                  v-for="dot in item.dots"
                  :key="item.key + '-' + dot.round"
                  :cx="dot.x"
                  :cy="dot.y"
                  r="3.7"
                  fill="#fff"
                  :stroke="item.color"
                  stroke-width="2.2"
                >
                  <title>第{{ dot.round }}轮 {{ item.label }} {{ percent(dot.value) }}</title>
                </circle>
              </g>
            </svg>
          </div>
          <p class="trend-hint">左右滑动查看全部轮次</p>
        </article>

        <article class="report-panel ranking-panel">
          <div class="panel-heading">
            <div>
              <p>SCORE</p>
              <h2>公告总分</h2>
            </div>
            <span>满分 100</span>
          </div>
          <div class="score-ranking">
            <div v-for="item in scoreRanking" :key="item.id">
              <div>
                <span>{{ item.name }}</span>
                <strong>{{ item.score.total }}</strong>
              </div>
              <i>
                <b :style="{ width: item.width, background: scoreTone(item.score.total) }"></b>
              </i>
            </div>
          </div>
        </article>
      </section>

      <section v-if="report.announcements?.length" class="report-section announcement-section">
        <div class="section-heading">
          <div>
            <p>03 · ANNOUNCEMENTS</p>
            <h2>公告评分与解析</h2>
          </div>
          <span>{{ hasDimensions ? '五个维度各 20 分' : '评论情绪 40% · 官方态度 60%' }}</span>
        </div>

        <div class="announcement-grid">
          <article v-for="item in report.announcements" :key="item.id" class="announcement-card">
            <header>
              <div>
                <span>{{ item.published_at }}</span>
                <h3>{{ item.name }}</h3>
              </div>
              <div class="score-dial" :style="scoreStyle(item.score.total)">
                <strong>{{ item.score.total }}</strong>
                <span>{{ item.score.level || item.score.judgement }}</span>
              </div>
            </header>

            <p class="announcement-text">{{ item.text }}</p>

            <div class="dimension-list">
              <div v-for="dimension in scoreBars(item)" :key="dimension.name">
                <span>{{ dimension.name }}</span>
                <i><b :style="{ width: `${dimension.percent}%` }"></b></i>
                <strong>{{ dimension.score }}</strong>
              </div>
            </div>

            <div class="announcement-analysis">
              <p>{{ item.analysis.summary }}</p>
              <div>
                <section>
                  <h4>优势</h4>
                  <ul>
                    <li v-for="point in item.analysis.strengths" :key="point">{{ point }}</li>
                  </ul>
                </section>
                <section>
                  <h4>风险</h4>
                  <ul>
                    <li v-for="point in item.analysis.risks" :key="point">{{ point }}</li>
                  </ul>
                </section>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section
        v-if="report.word_cloud?.length || report.key_comments?.length"
        class="insight-grid"
        :class="{ 'is-single': !report.word_cloud?.length || !report.key_comments?.length }"
      >
        <article v-if="report.word_cloud?.length" class="report-panel cloud-panel">
          <div class="panel-heading">
            <div>
              <p>04 · KEYWORDS</p>
              <h2>讨论词云</h2>
            </div>
            <span>按讨论权重</span>
          </div>
          <div class="word-cloud">
            <span
              v-for="(word, index) in report.word_cloud"
              :key="word.text"
              :style="wordStyle(word, index)"
            >{{ word.text }}</span>
          </div>
        </article>

        <article v-if="report.key_comments?.length" class="report-panel comments-panel">
          <div class="panel-heading">
            <div>
              <p>05 · COMMENTS</p>
              <h2>关键评论示例</h2>
            </div>
            <span>精选 4 条</span>
          </div>
          <div class="key-comments">
            <article v-for="comment in report.key_comments" :key="comment.id">
              <header>
                <span :class="'emotion-' + comment.emotion">{{ emotionLabel(comment.emotion) }}</span>
                <strong>{{ comment.faction }}</strong>
                <small>第 {{ comment.round }} 轮</small>
              </header>
              <p>“{{ comment.text }}”</p>
              <footer>{{ comment.insight }}</footer>
            </article>
          </div>
        </article>
      </section>

      <section class="report-section conclusion-section">
        <div class="conclusion-copy">
          <p>06 · CONCLUSION</p>
          <h2>结论与建议</h2>
          <blockquote v-if="report.summary.overall">{{ report.summary.overall }}</blockquote>
        </div>
        <ol>
          <li v-for="item in report.conclusion.recommendations" :key="item">{{ item }}</li>
        </ol>
      </section>

      <footer class="report-footer">
        <span>{{ report.conclusion?.limitations }}</span>
        <span>Simulation2 · 会话推演报告</span>
      </footer>
      </template>
    </div>
  </main>
</template>

<style src="../styles/report.css"></style>
