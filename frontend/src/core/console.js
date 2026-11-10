import {
  createSession as createSessionRequest,
  getInputDefaults,
  getSession,
  previewInputs as previewInputsRequest,
  runSessionAction
} from "../api/index.js";
import { getSettings, opinionPoolRequestConfig } from "./settings.js";

function createAnnouncementDraft(id, text = "", status = "clear", strategyId = "custom", explicit = false) {
  return {
    id,
    text,
    status,
    strategyId,
    explicit
  };
}

export default {
  name: "ConsoleOptions",
  data() {
    return {
      defaults: null,
      session: null,
      agentPrefs: getSettings().agents,
      showTokenStats: getSettings().ui?.showTokenStats !== false,
      selectedStrategyId: "custom",
      announcementState: {},
      suppressStrategySync: false,
      lastDraftByStrategy: {},
      eventContent: "",
      eventTopic: "社会事件",
      eventValence: "negative",
      entryMode: "dynamic",
      entryRound: 3,
      timelineRound: 2,
      timelineStatus: "clear",
      timelineText: "",
      busy: false,
      busyText: "",
      busyAction: null,
      autoRun: false,
      autoToken: 0,
      pauseRollbackPending: false,
      chartTooltip: null,
      poolOpen: false,
      poolDetail: null,
      agentOpen: false,
      agentDetail: null,
      networkHoverId: null,
      networkEdgeFilter: "strong",
      announcementDrafts: [createAnnouncementDraft("announcement-1", "", "clear", "custom")],
      activeAnnouncementId: "announcement-1",
      announcementSeed: 1,
      networkScale: getSettings().agents.zoom,
      networkPanX: 0,
      networkPanY: 0,
      networkDragging: false,
      networkDrag: null,
      networkFullscreen: false,
      composerOpen: false,
      composerTab: "event",
      railTab: "metrics",
      poolStep: null,
      liveText: "正在连接服务",
      liveOk: false
    };
  },

  watch: {
    selectedStrategyId(strategyId) {
      if (this.suppressStrategySync) return;
      if (!this.isContentStrategy(strategyId)) return;
      this.ensureAnnouncementState(strategyId);
      const existing = this.draftForStrategy(strategyId);
      if (existing) {
        this.activateDraft(existing.id, false);
        return;
      }
      this.addAnnouncementDraft({ strategyId, select: true });
    },
    activeAnnouncementDraft: {
      handler(draft) {
        if (!draft) return;
        const strategyId = draft.strategyId || this.selectedStrategyId;
        if (!this.isContentStrategy(strategyId)) return;
        this.lastDraftByStrategy[strategyId] = draft.id;
        if (!this.announcementState[strategyId]) return;
        const state = this.announcementState[strategyId];
        if (state.text === draft.text && state.status === draft.status) return;
        this.announcementState[strategyId] = {
          text: draft.text,
          status: draft.status
        };
      },
      deep: true,
      immediate: true
    },
    poolOpen(value) {
      if (value) this.resetPoolScroll();
    },
    poolDetail() {
      this.resetPoolScroll();
    },
    timelineText() {
      this.$nextTick(() => this.resizeTimelineTextarea());
    }
  },

  computed: {
    strategies() {
      const list = (this.defaults?.strategies || []).filter(
        (item) => item.strategy_id !== "no_response"
      );
      return [
        { strategy_id: "__all__", strategy_name: "依次运行全部策略", ready: true },
        { strategy_id: "no_response", strategy_name: "不回应", ready: true },
        ...list
      ];
    },




    strategyOverview() {
      return this.strategies.map((item, index) => {
        if (item.strategy_id === "__all__") {
          return {
            strategy_id: item.strategy_id,
            strategy_name: item.strategy_name,
            status: "all",
            ready: true,
            statement: "依次运行不回应与四种内置公告策略"
          };
        }
        if (item.strategy_id === "no_response") {
          return {
            strategy_id: item.strategy_id,
            strategy_name: item.strategy_name,
            status: "none",
            ready: true,
            statement: "不发布官方公告"
          };
        }
        const content = this.announcementState[item.strategy_id] || {};
        return {
          strategy_id: item.strategy_id,
          strategy_name: item.strategy_name,
          status: content.status || "none",
          ready:
            item.strategy_id !== "custom" ||
            Boolean(content.text?.trim() && content.status !== "none"),
          statement: content.text?.trim() || "尚未填写公告内容"
        };
      });
    },

    contentStrategies() {
      return (this.defaults?.official_default?.content_strategies || []).map((item) => ({
        ...item,
        ready:
          item.strategy_id !== "custom" ||
          Boolean(this.announcementState[item.strategy_id]?.text?.trim()) &&
          this.announcementState[item.strategy_id]?.status !== "none"
      }));
    },

    contentStrategyIds() {
      return this.contentStrategies.map((item) => item.strategy_id);
    },

    validDrafts() {
      return this.announcementDrafts.filter(
        (draft) =>
          draft.explicit &&
          draft.text.trim() &&
          draft.status !== "none" &&
          this.isContentStrategy(draft.strategyId)
      );
    },

    draftsRunMode() {
      return (
        this.validDrafts.length >= 2 &&
        this.selectedStrategyId !== "__all__" &&
        this.selectedStrategyId !== "no_response"
      );
    },

    createButtonText() {
      return this.draftsRunMode
        ? `创建并运行 ${this.validDrafts.length} 条草稿`
        : "创建会话";
    },

    compactMetricsSvg() {
      const metrics = this.metricsRows;
      const maxStep = this.session?.max_steps || 10;
      const timeline = this.timeline;
      const width = 300;
      const height = 180;
      const margin = { left: 30, right: 10, top: 16, bottom: 24 };
      const chartWidth = width - margin.left - margin.right;
      const chartHeight = height - margin.top - margin.bottom;
      const colors = { negative: "#c2413b", question: "#c57b24", accept: "#2f8f5b" };
      const steps = Array.from({ length: maxStep }, (_, index) => index + 1);
      const metricsByStep = Object.fromEntries(metrics.map((item) => [item.step, item]));
      const x = (step) =>
        margin.left + ((step - 1) / Math.max(maxStep - 1, 1)) * chartWidth;
      const y = (value) => margin.top + (1 - value) * chartHeight;

      let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="舆情指标趋势">`;

      for (let tick = 0; tick <= 4; tick += 1) {
        const value = tick / 4;
        const yy = y(value);
        svg += `<line x1="${margin.left}" x2="${width - margin.right}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="rgba(30,39,34,.09)" />`;
        if (tick % 2 === 0) {
          svg += `<text x="${margin.left - 7}" y="${(yy + 3).toFixed(1)}" text-anchor="end" fill="#8b978f" font-size="9">${Math.round(value * 100)}%</text>`;
        }
      }

      steps.forEach((step) => {
        svg += `<text x="${x(step).toFixed(1)}" y="${height - 7}" text-anchor="middle" fill="#8b978f" font-size="8.5">${step}</text>`;
      });

      if (this.session?.response_step) {
        const xx = x(this.session.response_step);
        svg += `<line x1="${xx.toFixed(1)}" x2="${xx.toFixed(1)}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#9a3412" stroke-width="1.2" stroke-dasharray="5 4" />`;
        svg += `<text x="${(xx + 4).toFixed(1)}" y="${margin.top + 7}" fill="#9a3412" font-size="9">进场</text>`;
      }

      timeline.forEach((event, index) => {
        const xx = x(event.round);
        svg += `<line x1="${xx.toFixed(1)}" x2="${xx.toFixed(1)}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#7358c7" stroke-width="1" stroke-dasharray="2 4" />`;
        svg += `<text x="${(xx + 4).toFixed(1)}" y="${margin.top + 18}" fill="#7358c7" font-size="8.5">公告${index + 1}</text>`;
      });

      [
        ["负面率", "negative", "negative_rate"],
        ["质疑率", "question", "question_rate"],
        ["接受率", "accept", "accept_rate"]
      ].forEach(([name, key, field]) => {
        const points = steps
          .map((step) => {
            const value = metricsByStep[step]?.policy_metrics?.[field];
            return value === null || value === undefined
              ? null
              : { step, value };
          })
          .filter(Boolean);
        if (!points.length) return;

        const path = points
          .map(
            (point, index) =>
              `${index ? "L" : "M"}${x(point.step).toFixed(1)},${y(point.value).toFixed(1)}`
          )
          .join("");
        svg += `<path d="${path}" fill="none" stroke="${colors[key]}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" />`;
        points.forEach((point) => {
          const text = `第${point.step}轮 ${name} ${this.percent(point.value)}`;
          svg += `<circle cx="${x(point.step).toFixed(1)}" cy="${y(point.value).toFixed(1)}" r="2.2" fill="#fff" stroke="${colors[key]}" stroke-width="1.6" data-tooltip="${this.esc(text)}"><title>${this.esc(text)}</title></circle>`;
        });
      });

      return `${svg}</svg>`;
    },
    networkCanvasStyle() {
      return {
        transform: `translate3d(${this.networkPanX}px, ${this.networkPanY}px, 0) scale(${this.networkScale})`,
        transformOrigin: "50% 50%"
      };
    },
    activeAnnouncementDraft() {
      return this.announcementDrafts.find(
        (item) => item.id === this.activeAnnouncementId
      ) || null;
    },
    customReady() {
      return Boolean(
        this.announcementState?.custom?.text?.trim() ||
        this.announcementDrafts.some(
          (draft) => draft.strategyId === "custom" && draft.text.trim()
        )
      );
    },

    snapshot() {
      return this.session?.snapshot || null;
    },

    tokenUsage() {
      const usage = this.session?.token_usage || {};
      const number = (value) => {
        const parsed = Number(value);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
      };
      return {
        prompt_tokens: number(usage.prompt_tokens),
        completion_tokens: number(usage.completion_tokens),
        total_tokens: number(usage.total_tokens),
        cached_tokens: number(usage.cached_tokens),
        request_count: number(usage.request_count)
      };
    },

    agents() {
      const realAgents = this.snapshot?.agents || [];
      const total = this.session ? 30 : this.agentPrefs.count;
      if (realAgents.length >= total) return realAgents.slice(0, total);

      const placeholders = Array.from(
        { length: total - realAgents.length },
        (_, index) => {
          const sequence = 9001 + index;
          return {
            agent_id: `preview-${sequence}`,
            current_emotion: ["neutral", "negative", "positive"][index % 3],
            last_action: index % 4 === 0 ? "comment" : "observe",
            last_comment_faction: ["观点输出派", "吃瓜派", "表态判断派"][index % 3],
            last_comment: ""
          };
        }
      );

      return [...realAgents, ...placeholders];
    },

    agentNetworkNodes() {
      const weights = new Map(
        (this.snapshot?.network?.nodes || []).map((node) => [node.agent_id, node])
      );
      const nodes = this.agents.map((agent, index) => ({
        ...agent,
        ...(weights.get(agent.agent_id) || {}),
        index
      }));
      const positions = this.layoutNetwork(nodes, this.networkGraphEdges);
      return nodes.map((node, index) => ({ ...node, ...positions[index] }));
    },

    networkGraphEdges() {
      const nodeIds = this.agents.map((agent) => agent.agent_id);
      if (nodeIds.length < 2) return [];
      const nodeIdSet = new Set(nodeIds);
      const sourceEdges = this.snapshot?.network?.edges || [];

      if (sourceEdges.length) {
        return sourceEdges
          .filter((edge) => nodeIdSet.has(edge.source) && nodeIdSet.has(edge.target))
          .map((edge, index) => {
            const normalized = Number(edge.normalized_weight);
            return {
              id: `${edge.source}-${edge.target}`,
              sourceId: edge.source,
              targetId: edge.target,
              weight: edge.weight ?? null,
              normalizedWeight: Number.isFinite(normalized) ? normalized : null,
              index
            };
          });
      }

      // 预览网络：用确定性的链式关系模拟结构，密度交给 visibleNetworkEdges 控制
      const edges = [];
      const seen = new Set();
      const addEdge = (sourceIndex, targetIndex) => {
        if (sourceIndex === targetIndex) return;
        const source = nodeIds[sourceIndex];
        const target = nodeIds[targetIndex];
        if (!source || !target) return;
        const key = `${source}-${target}`;
        if (seen.has(key)) return;
        seen.add(key);
        const seed = (sourceIndex * 31 + targetIndex * 17) % 75;
        edges.push({
          id: key,
          sourceId: source,
          targetId: target,
          weight: 0.4 + seed / 200,
          normalizedWeight: (25 + seed) / 100,
          index: edges.length
        });
      };

      nodeIds.forEach((_, index) => {
        addEdge(index, (index + 1) % nodeIds.length);
        addEdge(index, (index + 3) % nodeIds.length);
        addEdge(index, (index + 7) % nodeIds.length);
      });

      return edges;
    },

    visibleNetworkEdges() {
      const edges = this.agentNetworkEdges;
      if (!edges.length) return edges;

      const hovered = this.networkHoverId;
      if (hovered) {
        return edges.filter(
          (edge) => edge.sourceId === hovered || edge.targetId === hovered
        );
      }
      if (this.networkEdgeFilter === "all") return edges;

      const density =
        {
          low: { perNode: 1.6, maxDegree: 4 },
          medium: { perNode: 2.2, maxDegree: 4 },
          high: { perNode: 2.8, maxDegree: 5 }
        }[this.agentPrefs.density] || { perNode: 2, maxDegree: 4 };

      return this.curateEdges(edges, density);
    },

    agentNetworkEdges() {
      const nodes = this.agentNetworkNodes;
      if (nodes.length < 2) return [];
      const byId = new Map(nodes.map((node) => [node.agent_id, node]));
      return this.networkGraphEdges
        .map((edge) => {
          const from = byId.get(edge.sourceId);
          const to = byId.get(edge.targetId);
          if (!from || !to) return null;
          return { ...edge, x1: from.x, y1: from.y, x2: to.x, y2: to.y };
        })
        .filter(Boolean);
    },

    networkActive() {
      return Boolean(
        this.agents.length &&
        this.session &&
        ["baseline", "scenario"].includes(this.session.phase) &&
        !this.session.paused &&
        !this.pauseRollbackPending
      );
    },

    metricsRows() {
      return this.snapshot?.metrics_history || [];
    },

    latestMetrics() {
      return this.metricsRows.length ? this.metricsRows[this.metricsRows.length - 1] : null;
    },

    metricCards() {
      const policy = this.latestMetrics?.policy_metrics || {};
      return [
        ["负面率", policy.negative_rate],
        ["质疑率", policy.question_rate],
        ["接受率", policy.accept_rate],
        ["趋势", this.trendText(this.latestMetrics?.global_trend)]
      ];
    },

    comments() {
      const byStep = this.snapshot?.comments_by_step || {};
      if (this.poolStep !== null) return byStep[String(this.poolStep)] || [];
      return this.snapshot?.latest_comments || [];
    },

    poolRoundOptions() {
      const byStep = this.snapshot?.comments_by_step || {};
      const history = new Map(
        (this.snapshot?.comment_history || []).map((item) => [Number(item.step), item])
      );
      return Object.keys(byStep)
        .map(Number)
        .sort((left, right) => left - right)
        .map((step) => {
          const meta = history.get(step) || {};
          const comments = byStep[String(step)] || [];
          return {
            key: String(step),
            step,
            label: `第 ${step} 轮`,
            hint: step === 1 ? "初始池" : meta.quality_status && meta.quality_status !== "normal" ? meta.quality_status : "",
            count: comments.length || meta.comment_count || 0
          };
        });
    },

    poolRoundKey() {
      if (this.poolStep !== null) return String(this.poolStep);
      return String(this.snapshot?.latest_step ?? "");
    },

    poolRoundLabel() {
      const option = this.poolRoundOptions.find((item) => item.key === this.poolRoundKey);
      if (!option) return "";
      const name = option.step === 1 ? "初始池" : option.label;
      const suffix = option.hint && option.step !== 1 ? ` · ${option.hint}` : "";
      return `${name}${suffix} · ${this.comments.length} 条`;
    },

    poolRoundIndex() {
      return this.poolRoundOptions.findIndex((item) => item.key === this.poolRoundKey);
    },

    poolRoundHasPrev() {
      return this.poolRoundIndex > 0;
    },

    poolRoundHasNext() {
      return this.poolRoundIndex >= 0 && this.poolRoundIndex < this.poolRoundOptions.length - 1;
    },

    poolEmotionStats() {
      const total = Math.max(this.comments.length, 1);
      return [
        ["negative", "负面", "#c2413b"],
        ["neutral", "中性", "#c57b24"],
        ["positive", "正面", "#2f8f5b"]
      ].map(([key, label, color]) => {
        const count = this.comments.filter((item) => item.emotion === key).length;
        return { key, label, color, count, rate: count / total };
      });
    },

    poolEmotionChartSvg() {
      const stats = this.poolEmotionStats;
      const total = this.comments.length;
      const radius = 36;
      const circumference = 2 * Math.PI * radius;
      let offset = 0;
      const segments = stats.map((item) => {
        const length = item.rate * circumference;
        const remainder = Math.max(circumference - length, 0);
        const segment = `<circle cx="50" cy="50" r="${radius}" fill="none" stroke="${item.color}" stroke-width="12" stroke-dasharray="${length.toFixed(2)} ${remainder.toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 50 50)" />`;
        offset += length;
        return segment;
      }).join("");
      return `<svg viewBox="0 0 100 100" role="img" aria-label="评论情绪构成"><circle cx="50" cy="50" r="${radius}" fill="none" stroke="#edf2f0" stroke-width="12" />${segments}<text x="50" y="48" text-anchor="middle" fill="#2f7f78" font-size="18" font-weight="700">${total}</text><text x="50" y="61" text-anchor="middle" fill="#806b60" font-size="8">条评论</text></svg>`;
    },

    poolFactionStats() {
      return this.poolGroupStats("faction", (value) => value || "未分类");
    },



    timeline() {
      return this.session?.announcement_timeline || [];
    },




    phaseLine() {
      if (!this.session) return "创建会话后开始控制";
      if (this.pauseRollbackPending) return "正在回退到上一轮结束状态";
      if (this.autoRun || this.busy) return "自动运行中";
      if (this.session.paused) return "已暂停，点击“继续运行”恢复";
      return "等待运行";
    },

    currentStrategyText() {
      const session = this.session;
      if (!session) return "尚未选择策略";
      const name = this.strategyName(session.selected_strategy_id);
      const timing = session.entry_timing?.mode === "fixed_round"
        ? `固定第 ${session.entry_timing.round} 轮进场`
        : "动态进场";
      if (session.mode === "drafts") {
        const count = session.draft_count || session.drafts?.length || 0;
        return `全部草稿 · ${count} 条 · ${timing}`;
      }
      return `${session.mode === "all" ? "全部策略" : `当前策略：${name}`} · ${timing}`;
    },

    canCreateSession() {
      if (!this.eventContent.trim() || this.busy) return false;
      if (this.draftsRunMode) return this.validDrafts.length >= 2;
      return this.selectedStrategyId !== "custom" || this.customReady;
    },

    createHint() {
      if (this.busy) return this.busyText || "正在处理";
      if (!this.eventContent.trim()) return "请先填写事件正文";
      if (this.draftsRunMode) {
        return `创建后将依次运行右侧 ${this.validDrafts.length} 条公告草稿`;
      }
      if (this.selectedStrategyId === "custom" && !this.customReady) {
        return "自定义策略需要填写公告内容，或切换到内置策略";
      }
      return "创建后进入待运行状态，可在底部控制条启动推演";
    },

    metricsSvg() {
      return this.compactMetricsSvg;
    }
  },

  mounted() {
    this.initialize();
    document.body.classList.toggle(
      "hide-agent-labels",
      !this.agentPrefs.showLabels
    );
    this.onNetworkKeydown = (event) => {
      if (event.key !== "Escape") return;
      if (this.networkFullscreen) this.exitNetworkFullscreen();
      else if (this.composerOpen) this.closeComposer();
      else if (this.agentOpen) this.agentOpen = false;
      else if (this.poolOpen) this.poolOpen = false;
    };
    window.addEventListener("keydown", this.onNetworkKeydown);
  },
  beforeUnmount() {
    if (this.onNetworkKeydown) {
      window.removeEventListener("keydown", this.onNetworkKeydown);
    }
    document.body.classList.remove("hide-agent-labels");
    document.body.style.overflow = "";
  },

  methods: {
    resetPoolScroll() {
      this.$nextTick(() => {
        const drawer = this.$refs.poolDrawerBody;
        if (drawer) drawer.scrollTop = 0;
      });
    },

    ensureAnnouncementState(strategyId) {
      if (!strategyId || this.announcementState[strategyId]) return;
      const item = (this.defaults?.official_default?.content_strategies || [])
        .find((strategy) => strategy.strategy_id === strategyId);
      if (!item) return;
      this.announcementState[strategyId] = {
        text: item.official_statement || "",
        status: item.official_statement_status || "none"
      };
    },

    isContentStrategy(strategyId) {
      return this.contentStrategyIds.includes(strategyId);
    },

    draftForStrategy(strategyId) {
      const rememberedId = this.lastDraftByStrategy[strategyId];
      const remembered = rememberedId
        ? this.announcementDrafts.find((draft) => draft.id === rememberedId)
        : null;
      if (remembered && remembered.strategyId === strategyId) return remembered;
      return (
        this.announcementDrafts.find(
          (draft) => draft.strategyId === strategyId
        ) || null
      );
    },

    activateDraft(id, switchStrategy = true) {
      const draft = this.announcementDrafts.find((item) => item.id === id);
      if (!draft) return;
      this.activeAnnouncementId = id;
      this.lastDraftByStrategy[draft.strategyId] = id;
      if (
        switchStrategy &&
        this.isContentStrategy(draft.strategyId) &&
        this.selectedStrategyId !== draft.strategyId
      ) {
        this.suppressStrategySync = true;
        this.selectedStrategyId = draft.strategyId;
        this.$nextTick(() => {
          this.suppressStrategySync = false;
        });
      }
    },

    esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[ch]));
    },

    percent(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
      return `${Math.round(Number(value) * 100)}%`;
    },

    formatTokenCount(value) {
      const number = Number(value);
      if (!Number.isFinite(number) || number <= 0) return "0";
      if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
      if (number >= 1_000) return `${(number / 1_000).toFixed(1)}k`;
      return String(Math.round(number));
    },

    async initialize() {
      try {
        this.defaults = await getInputDefaults();
        const event = this.defaults.event_default || {};
        this.eventContent = event.event_content || "";
        this.eventTopic = event.event_labels?.topic || "社会事件";
        this.eventValence = event.event_labels?.event_valence || "negative";
        for (const item of this.defaults.official_default?.content_strategies || []) {
          this.announcementState[item.strategy_id] = {
            text: item.official_statement || "",
            status: item.official_statement_status || "none"
          };
        }
        const sessionId = this.sessionIdFromHash();
        if (sessionId) {
          this.session = await getSession(sessionId);
        }
        this.setLive("输入已加载", true);
      } catch (error) {
        this.setLive(error.message, false);
      }
      this.syncDraftFromStrategy();
    },

    setLive(text, ok) {
      this.liveText = text;
      this.liveOk = ok;
    },

    sessionIdFromHash() {
      const raw = location.hash.replace(/^#/, "");
      const [routePath, query = ""] = raw.split("?");
      const params = new URLSearchParams(query);
      return params.get("session") ||
        (routePath.startsWith("event_") ? routePath : "");
    },

    updateSessionHash(experimentId) {
      const raw = location.hash.replace(/^#/, "");
      const [routePath] = raw.split("?");
      const base = "/console";
      history.replaceState(
        null,
        "",
        `#${base}?session=${encodeURIComponent(experimentId)}`
      );
    },

    strategyName(strategyId) {
      if (strategyId === "__all__") return "依次运行全部策略";
      if (strategyId === "__drafts__") return "全部公告草稿";
      const item = this.strategies.find((strategy) => strategy.strategy_id === strategyId);
      return item?.strategy_name || strategyId || "—";
    },

    markActiveDraftExplicit() {
      if (this.activeAnnouncementDraft) {
        this.activeAnnouncementDraft.explicit = true;
      }
    },

    draftStatusText(value) {
      return {
        clear: "信息完整",
        incomplete: "信息不全",
        conflict: "表述冲突",
        none: "不发布"
      }[value] || value || "—";
    },



    eventInput() {
      return {
        event_content: this.eventContent.trim(),
        event_labels: {
          topic: this.eventTopic,
          event_valence: this.eventValence
        }
      };
    },


    editableContentInput() {
      const result = {};
      for (const item of this.contentStrategies) {
        const editable = this.announcementState[item.strategy_id] || {};
        result[item.strategy_id] = {
          official_statement: editable.text || "",
          official_statement_status: editable.status || "none"
        };
      }
      return result;
    },

    entryTimingInput() {
      if (this.entryMode !== "fixed_round") return { mode: "dynamic" };
      return { mode: "fixed_round", round: Number(this.entryRound) };
    },

    async previewInputs() {
      this.withBusy("正在校验输入", async () => {
        const data = await previewInputsRequest({
          web_event_input: this.eventInput(),
          official_content_input: this.editableContentInput(),
          entry_timing_input: this.entryTimingInput()
        });
        this.setLive("输入校验通过", true);
        return data;
      });
    },

    async createSession() {
      if (!this.draftsRunMode && this.selectedStrategyId === "custom" && !this.customReady) {
        this.setLive("custom 公告为空，无法创建会话", false);
        return;
      }
      const draftsPayload = this.draftsRunMode
        ? this.validDrafts.map((draft) => ({
            draft_id: draft.id,
            strategy_id: draft.strategyId,
            official_statement: draft.text.trim(),
            official_statement_status: draft.status
          }))
        : undefined;
      await this.withBusy("正在创建会话批次", async () => {
        const data = await createSessionRequest({
          web_event_input: this.eventInput(),
          official_content_input: this.editableContentInput(),
          entry_timing_input: this.entryTimingInput(),
          selected_strategy_id: this.draftsRunMode ? "custom" : this.selectedStrategyId,
          announcement_drafts_input: draftsPayload,
          // 2026/11/09 初始舆论池双来源：把设置页选定的来源随会话一起提交
          opinion_pool_config: opinionPoolRequestConfig(getSettings().opinionPool)
        });
        this.session = data;
        this.updateSessionHash(data.experiment_id);
        this.setLive("会话已创建", true);
      });
    },

    async sessionAction(action, body = {}) {
      if (!this.session || this.busy) return;
      this.busyAction = action;
      await this.withBusy(
        ["continue", "step"].includes(action) ? "推演执行中" : "请求处理中",
        async () => {
          this.session = await runSessionAction(
            this.session.experiment_id,
            action,
            body
          );
          if (this.pauseRollbackPending && ["continue", "step"].includes(action)) {
            this.pauseRollbackPending = false;
            this.session = await runSessionAction(
              this.session.experiment_id,
              "rollback",
              { steps: 1 }
            );
          }
        }
      );
      this.busyAction = null;
    },

    async withBusy(text, task) {
      this.busy = true;
      this.busyText = text;
      try {
        await task();
      } catch (error) {
        this.setLive(error.message, false);
      } finally {
        this.busy = false;
        this.busyText = "";
      }
    },

    async startRun() {
      await this.sessionAction("start");
      if (this.session && this.session.mode === "single") {
        this.autoRun = true;
        this.runAutoLoop();
      }
    },

    async continueRun() {
      if (!this.session || this.busy) return;
      this.autoRun = true;
      this.runAutoLoop();
    },

    async pauseRun() {
      this.autoRun = false;
      this.autoToken += 1;
      if (this.busy && this.busyAction === "continue") {
        this.pauseRollbackPending = true;
        this.setLive("当前轮完成后将回退到上一轮结束状态", true);
        return;
      }
      if (this.busy) return;
      if (!this.session) return;
      try {
        this.session = await runSessionAction(
          this.session.experiment_id,
          "pause"
        );
        this.setLive("已暂停", false);
      } catch (error) {
        this.setLive(error.message, false);
      }
    },

    async rollbackRun() {
      this.autoRun = false;
      this.autoToken += 1;
      await this.sessionAction("rollback", { steps: 1 });
    },

    async restartRun() {
      this.autoRun = false;
      this.autoToken += 1;
      const previousId = this.session?.experiment_id || null;
      await this.sessionAction("restart");
      if (
        this.session &&
        this.session.experiment_id &&
        this.session.experiment_id !== previousId
      ) {
        this.updateSessionHash(this.session.experiment_id);
        this.setLive("新批次已创建", true);
        if (this.session.mode === "drafts") {
          await this.runAll();
        }
      }
    },

    async runAll() {
      this.autoRun = false;
      if (!this.session) return;
      const label =
        this.session.mode === "drafts"
          ? "全部草稿依次运行中"
          : "五种策略依次运行中";
      await this.withBusy(label, async () => {
        this.session = await runSessionAction(
          this.session.experiment_id,
          "run"
        );
      });
    },

    async runAutoLoop() {
      const token = ++this.autoToken;
      while (this.autoRun && token === this.autoToken) {
        const session = this.session;
        if (!session || ["completed", "completed_no_entry", "failed", "not_run"].includes(session.status)) {
          this.autoRun = false;
          break;
        }
        if (!["baseline", "scenario"].includes(session.phase)) {
          this.autoRun = false;
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
        await this.sessionAction("continue");
      }
    },

    async addAnnouncement() {
      if (!this.session || !this.session.paused || this.busy) return;
      if (!this.timelineText.trim()) {
        this.setLive("请填写公告内容", false);
        return;
      }
      await this.withBusy("正在追加公告", async () => {
        this.session = await runSessionAction(
          this.session.experiment_id,
          "announcement",
          {
            round: Number(this.timelineRound),
            official_statement: this.timelineText.trim(),
            official_statement_status: this.timelineStatus
          }
        );
        this.timelineText = "";
        this.setLive("公告已加入时间线", true);
      });
    },

    resizeTimelineTextarea() {
      const textarea = this.$refs.timelineTextarea;
      if (!textarea) return;
      const maxHeight = 160;
      textarea.style.height = "auto";
      const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
      textarea.style.height = `${nextHeight}px`;
      textarea.style.overflowY = textarea.scrollHeight > maxHeight
        ? "auto"
        : "hidden";
    },

    canStart() {
      return Boolean(this.session && this.session.phase === "created" && !this.busy);
    },

    canContinue() {
      return Boolean(
        this.session &&
        ["baseline", "scenario"].includes(this.session.phase) &&
        !this.busy
      );
    },

    canPause() {
      return Boolean(
        this.session &&
        ["baseline", "scenario"].includes(this.session.phase) &&
        ((this.busy && this.busyAction === "continue") || this.autoRun || !this.session.paused)
      );
    },

    canRollback() {
      return Boolean(this.session && !this.busy && (this.session.completed_step_count || 0) > 0);
    },

    canAddAnnouncement() {
      return Boolean(this.session && this.session.paused && !this.busy);
    },

    openPool() {
      this.poolOpen = true;
      this.poolDetail = null;
    },


    openAgentDetail(agent) {
      this.networkHoverId = null;
      this.agentDetail = agent;
      this.agentOpen = true;
    },

    selectPoolRound(step) {
      this.poolStep = Number(step);
    },

    stepPoolRound(delta) {
      const option = this.poolRoundOptions[this.poolRoundIndex + delta];
      if (option) this.selectPoolRound(option.step);
    },

    openPoolDetail(comment) {
      this.poolDetail = comment;
      this.poolOpen = true;
    },


    poolGroupStats(field, labeler, limit = 6) {
      const total = Math.max(this.comments.length, 1);
      const counts = {};
      for (const comment of this.comments) {
        const key = comment[field] || "unknown";
        counts[key] = (counts[key] || 0) + 1;
      }
      return Object.entries(counts)
        .sort((left, right) => right[1] - left[1])
        .slice(0, limit)
        .map(([key, count]) => ({
          key,
          label: labeler(key),
          count,
          rate: count / total
        }));
    },

    setNetworkHover(agentId) {
      this.networkHoverId = agentId || null;
    },

    toggleNetworkEdgeFilter() {
      this.networkEdgeFilter = this.networkEdgeFilter === "all" ? "strong" : "all";
    },

    isNetworkEdgeActive(edge) {
      return Boolean(
        this.networkHoverId &&
        (edge.sourceId === this.networkHoverId || edge.targetId === this.networkHoverId)
      );
    },

    handleChartMove(event) {
      const circle = event.target.closest("circle[data-tooltip]");
      if (!circle) {
        this.chartTooltip = null;
        return;
      }
      const rect = event.currentTarget.getBoundingClientRect();
      this.chartTooltip = {
        text: circle.dataset.tooltip,
        left: event.clientX - rect.left + 12,
        top: event.clientY - rect.top + 10
      };
    },

    emotionText(value) {
      return { positive: "正面", neutral: "中性", negative: "负面" }[value] || "—";
    },

    stanceText(value) {
      return {
        support: "支持",
        criticism: "批评",
        questioning: "质疑",
        neutral: "观望",
        oppose: "反对",
        opposition: "反对",
        wait: "观望"
      }[value] || value || "—";
    },

    actionText(value) {
      return {
        comment: "发表评论",
        original: "原创",
        reshare: "转发",
        repost: "转发",
        quote: "引用",
        observe: "仅观察",
        reply: "回应",
        share: "转发",
        silent: "未发言",
        post: "发帖"
      }[value] || value || "—";
    },

    trendText(value) {
      if (!value) return "—";
      return {
        stable: "趋稳",
        improving: "缓和",
        worsening: "恶化",
        rising: "上升",
        falling: "下降",
        neutral: "平稳"
      }[value] || value;
    },

    orientationText(value) {
      return {
        fact: "事实信息",
        opinion: "观点表达",
        questioning: "质疑提问"
      }[value] || value || "—";
    },



    emotionColor(value) {
      if (value === "positive") return "#10b981";
      if (value === "negative") return "#e0473a";
      return "#7f8c99";
    },

    networkNodeStyle(node) {
      const raw = Number(node.normalized_influence_weight);
      const weight = Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : 0.5;
      const seed = String(node.agent_id)
        .split("")
        .reduce((total, char) => total + char.charCodeAt(0), 0);
      const angle = ((seed * 37) % 360) * (Math.PI / 180);
      const radius = 3 + ((seed * 13) % 5);
      const secondaryAngle = angle + 2.15;
      const secondaryRadius = radius * 0.72;

      return {
        left: `${Math.min(96, Math.max(4, Number(node.x) || 50))}%`,
        top: `${Math.min(94, Math.max(6, Number(node.y) || 50))}%`,
        "--node-delay": `${-((node.index % 7) * 0.19).toFixed(2)}s`,
        "--node-scale": `${(0.92 + weight * 0.26).toFixed(2)}`,
        "--drift-x": `${(Math.cos(angle) * radius).toFixed(1)}px`,
        "--drift-y": `${(Math.sin(angle) * radius).toFixed(1)}px`,
        "--drift-x-2": `${(Math.cos(secondaryAngle) * secondaryRadius).toFixed(1)}px`,
        "--drift-y-2": `${(Math.sin(secondaryAngle) * secondaryRadius).toFixed(1)}px`,
        "--drift-duration": `${(5.8 + ((seed * 7) % 34) / 10).toFixed(1)}s`,
        "--drift-delay": `-${(((seed * 11) % 65) / 10).toFixed(1)}s`
      };
    },

    networkEdgeStyle(edge) {
      const raw = Number(edge.normalizedWeight);
      const weight = Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : 0.5;
      return {
        "--flow-delay": `${-((edge.index % 11) * 0.23).toFixed(2)}s`,
        "--flow-duration": `${(2.2 + (edge.index % 5) * 0.22).toFixed(2)}s`,
        "--edge-width": `${(1.1 + weight * 0.6).toFixed(2)}`,
        "--edge-opacity": `${(0.18 + weight * 0.10).toFixed(2)}`
      };
    },



    toggleNetworkFullscreen() {
      this.networkFullscreen = !this.networkFullscreen;
      if (this.networkFullscreen) {
        this.resetNetworkZoom();
        document.body.style.overflow = "hidden";
      } else {
        document.body.style.overflow = "";
      }
    },
    exitNetworkFullscreen() {
      this.networkFullscreen = false;
      document.body.style.overflow = "";
    },
    onNetworkWheel(event) {
      const stage = event.currentTarget;
      if (!stage) return;
      const rect = stage.getBoundingClientRect();
      const anchorX = event.clientX - (rect.left + rect.width / 2);
      const anchorY = event.clientY - (rect.top + rect.height / 2);
      const factor = event.deltaY < 0 ? 1.12 : 0.89;
      const nextScale = Math.min(3, Math.max(0.55, this.networkScale * factor));
      const ratio = nextScale / this.networkScale;
      this.networkPanX = anchorX - (anchorX - this.networkPanX) * ratio;
      this.networkPanY = anchorY - (anchorY - this.networkPanY) * ratio;
      this.networkScale = Number(nextScale.toFixed(3));
    },
    resetNetworkZoom() {
      this.networkScale = 1;
      this.networkPanX = 0;
      this.networkPanY = 0;
    },

    onNetworkPointerDown(event) {
      if (event.button !== undefined && event.button !== 0) return;
      if (event.target.closest(".network-node")) return;
      this.networkDragging = true;
      this.networkDrag = {
        pointerId: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        panX: this.networkPanX,
        panY: this.networkPanY
      };
      event.currentTarget.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    },

    onNetworkPointerMove(event) {
      if (!this.networkDragging || !this.networkDrag) return;
      const dx = event.clientX - this.networkDrag.x;
      const dy = event.clientY - this.networkDrag.y;
      const stage = event.currentTarget;
      const limitX = (stage.clientWidth || 800) * 0.55;
      const limitY = (stage.clientHeight || 600) * 0.55;
      this.networkPanX = Math.max(-limitX, Math.min(limitX, this.networkDrag.panX + dx));
      this.networkPanY = Math.max(-limitY, Math.min(limitY, this.networkDrag.panY + dy));
    },

    onNetworkPointerUp(event) {
      if (!this.networkDragging) return;
      this.networkDragging = false;
      this.networkDrag = null;
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    },
    agentNodeTitle(agent) {
      const parts = [agent.agent_id, this.emotionText(agent.current_emotion)];
      const weight = Number(agent.influence_weight);
      if (Number.isFinite(weight)) parts.push(`影响力 ${weight.toFixed(2)}`);
      return parts.join(" · ");
    },
    curateEdges(edges, options = {}) {
      const perNode = options.perNode ?? 2;
      const maxDegree = options.maxDegree ?? 4;
      const minDegree = options.minDegree ?? 2;
      if (!edges.length) return edges;

      const target = Math.max(
        this.agents.length,
        Math.round(this.agents.length * perNode)
      );
      const sorted = [...edges].sort(
        (left, right) =>
          (right.normalizedWeight ?? 0) - (left.normalizedWeight ?? 0)
      );

      // 按权重优先，并限制单节点度数，避免出现“毛线球”和超级枢纽
      const degree = new Map();
      const chosen = [];
      const chosenIds = new Set();
      const addChosen = (edge) => {
        chosen.push(edge);
        chosenIds.add(edge.id);
        degree.set(edge.sourceId, (degree.get(edge.sourceId) || 0) + 1);
        degree.set(edge.targetId, (degree.get(edge.targetId) || 0) + 1);
      };

      for (const edge of sorted) {
        if (chosen.length >= target) break;
        const sourceDegree = degree.get(edge.sourceId) || 0;
        const targetDegree = degree.get(edge.targetId) || 0;
        if (sourceDegree >= maxDegree || targetDegree >= maxDegree) continue;
        addChosen(edge);
      }

      // 每个节点至少保留 minDegree 条关系，避免出现孤立的“飞点”
      for (const agent of this.agents) {
        let current = degree.get(agent.agent_id) || 0;
        while (current < minDegree) {
          const candidate = sorted.find(
            (edge) =>
              !chosenIds.has(edge.id) &&
              (edge.sourceId === agent.agent_id || edge.targetId === agent.agent_id)
          );
          if (!candidate) break;
          addChosen(candidate);
          current += 1;
        }
      }

      return chosen;
    },

    layoutNetwork(nodes, edges) {
      const count = nodes.length;
      if (!count) return [];
      if (count === 1) return [{ x: 50, y: 50 }];

      const positions = nodes.map((_, index) => {
        const angle = index * 2.399963 + 0.6;
        const radius = 38 * Math.sqrt((index + 0.8) / count);
        return {
          x: 50 + Math.cos(angle) * radius,
          y: 50 + Math.sin(angle) * radius
        };
      });

      const indexById = new Map(
        nodes.map((node, index) => [node.agent_id, index])
      );

      // 与展示使用同一套取舍规则，避免出现只连一条线却被推到画布边上的“飞点”
      const layoutEdges = this.curateEdges(edges, {
        perNode: 2.2,
        maxDegree: 4,
        minDegree: 2
      });
      const layoutLinks = layoutEdges
        .map((edge) => ({
          source: indexById.get(edge.sourceId),
          target: indexById.get(edge.targetId),
          weight: edge.normalizedWeight ?? 0.5
        }))
        .filter((link) => link.source !== undefined && link.target !== undefined);

      const ideal = Math.max(10, Math.sqrt(10000 / count) * 1.15);
      const iterations = 170;

      for (let step = 0; step < iterations; step += 1) {
        const displacement = positions.map(() => ({ x: 0, y: 0 }));

        for (let source = 0; source < count; source += 1) {
          for (let target = source + 1; target < count; target += 1) {
            let dx = positions[source].x - positions[target].x;
            let dy = positions[source].y - positions[target].y;
            let distance = Math.hypot(dx, dy) || 0.01;
            const force = (ideal * ideal) / distance;
            dx /= distance;
            dy /= distance;
            displacement[source].x += dx * force;
            displacement[source].y += dy * force;
            displacement[target].x -= dx * force;
            displacement[target].y -= dy * force;
          }
        }

        layoutLinks.forEach(({ source, target, weight }) => {
          let dx = positions[source].x - positions[target].x;
          let dy = positions[source].y - positions[target].y;
          let distance = Math.hypot(dx, dy) || 0.01;
          const force =
            ((distance * distance) / ideal) * (0.5 + weight * 0.85);
          dx /= distance;
          dy /= distance;
          displacement[source].x -= dx * force;
          displacement[source].y -= dy * force;
          displacement[target].x += dx * force;
          displacement[target].y += dy * force;
        });

        const heat = 5.5 * (1 - step / iterations) + 0.4;
        positions.forEach((position, index) => {
          displacement[index].x += (50 - position.x) * 0.03;
          displacement[index].y += (50 - position.y) * 0.03;
          const length =
            Math.hypot(displacement[index].x, displacement[index].y) || 1;
          const move = Math.min(length, heat);
          position.x += (displacement[index].x / length) * move;
          position.y += (displacement[index].y / length) * move;
        });
      }

      // 去掉迭代期的边界钳制后，按包围盒等比铺满安全区即可
      const xs = positions.map((position) => position.x);
      const ys = positions.map((position) => position.y);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      const spanX = Math.max(maxX - minX, 1);
      const spanY = Math.max(maxY - minY, 1);

      const degree = new Map();
      layoutEdges.forEach((edge) => {
        degree.set(edge.sourceId, (degree.get(edge.sourceId) || 0) + 1);
        degree.set(edge.targetId, (degree.get(edge.targetId) || 0) + 1);
      });

      return positions.map((position, index) => {
        let x = 6 + ((position.x - minX) / spanX) * 88;
        let y = 8 + ((position.y - minY) / spanY) * 84;
        // 度数低的节点轻微向中心收拢，避免贴着画布边缘的长线
        const nodeDegree = degree.get(nodes[index].agent_id) || 0;
        if (nodeDegree <= 2) {
          x = 50 + (x - 50) * 0.82;
          y = 50 + (y - 50) * 0.82;
        }
        return { x: Number(x.toFixed(2)), y: Number(y.toFixed(2)) };
      });
    },

    networkEdgePath(edge) {
      return `M${edge.x1.toFixed(2)} ${edge.y1.toFixed(2)} L${edge.x2.toFixed(2)} ${edge.y2.toFixed(2)}`;
    },

    openComposer(tab = "event") {
      this.composerTab = tab;
      this.composerOpen = true;
    },

    closeComposer() {
      this.composerOpen = false;
    },

    async submitSession() {
      if (!this.canCreateSession) return;
      const previousId = this.session?.experiment_id || null;
      await this.createSession();
      const createdId = this.session?.experiment_id;
      if (!createdId || createdId === previousId) return;
      this.composerOpen = false;
      if (this.session?.mode !== "drafts") return;
      await this.withBusy("全部草稿依次运行中", async () => {
        this.session = await runSessionAction(createdId, "run");
      });
    },

    syncDraftFromStrategy(strategyId = this.selectedStrategyId) {
      if (!this.isContentStrategy(strategyId)) return;
      const state = this.announcementState?.[strategyId];
      const draft = this.activeAnnouncementDraft;
      if (!state || !draft) return;
      const text = state.text || "";
      const status =
        state.status && state.status !== "none" ? state.status : "clear";
      if (
        draft.text === text &&
        draft.status === status &&
        draft.strategyId === strategyId
      ) {
        return;
      }
      draft.text = text;
      draft.status = status;
      draft.strategyId = strategyId;
    },
    addAnnouncementDraft(options = {}) {
      if (this.announcementDrafts.filter((draft) => draft.explicit).length >= 20) {
        this.setLive("公告草稿最多支持 20 条", false);
        return;
      }
      const explicit = options.explicit ?? !options.strategyId;
      const requestedStrategy = options.strategyId || this.selectedStrategyId;
      const strategyId = this.isContentStrategy(requestedStrategy)
        ? requestedStrategy
        : this.isContentStrategy(this.activeAnnouncementDraft?.strategyId)
        ? this.activeAnnouncementDraft.strategyId
        : "custom";
      this.ensureAnnouncementState(strategyId);
      const active = this.activeAnnouncementDraft;
      const source =
        active && active.strategyId === strategyId
          ? active
          : this.announcementState[strategyId] || {};
      this.announcementSeed += 1;
      const id = `announcement-${this.announcementSeed}`;
      this.announcementDrafts.push(
        createAnnouncementDraft(
          id,
          source.text || "",
          source.status && source.status !== "none" ? source.status : "clear",
          strategyId,
          explicit
        )
      );
      this.activeAnnouncementId = id;
      this.lastDraftByStrategy[strategyId] = id;
      if (options.select !== false) {
        this.$nextTick(() => {
          this.$refs.announcementTextarea?.focus();
        });
      }
    },
    removeActiveAnnouncementDraft() {
      const index = this.announcementDrafts.findIndex(
        (item) => item.id === this.activeAnnouncementId
      );
      if (index < 0) return;

      const [removed] = this.announcementDrafts.splice(index, 1);
      if (this.lastDraftByStrategy[removed.strategyId] === removed.id) {
        delete this.lastDraftByStrategy[removed.strategyId];
      }
      const nextItem =
        this.announcementDrafts[index] ||
        this.announcementDrafts[index - 1] ||
        null;
      this.activeAnnouncementId = nextItem?.id || null;
      if (nextItem) {
        this.lastDraftByStrategy[nextItem.strategyId] = nextItem.id;
      }
      this.$nextTick(() => {
        this.$refs.announcementTextarea?.focus();
      });
    },
    selectAnnouncementDraft(id) {
      this.activateDraft(id, true);
    }
  }
};
