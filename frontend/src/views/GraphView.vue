<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { getKnowledgeGraph } from "../api/knowledgeGraph.js";
import {
  LAYERS,
  buildClusterDetailModel,
  buildClusterModel,
  buildGraphModel,
  eventProvince,
  labelMeta,
  layoutGraph,
  searchGraphModel
} from "../core/knowledgeGraph.js";

const stageSize = ref({ width: 1200, height: 720 });
let resizeObserver = null;

const payload = ref(null);
const loading = ref(true);
const error = ref("");
const errorDetail = ref("");
const layer = ref("events");
const viewMode = ref("flat");
const activeCluster = ref("");
const clusterMinLink = ref(2);
const keyword = ref("");
const selectedId = ref("");
const hoveredId = ref("");
const tooltip = ref(null);
const layoutSeed = ref(0);

const scale = ref(1);
const panX = ref(0);
const panY = ref(0);
const dragging = ref(false);
const stageRef = ref(null);

let dragOrigin = null;

const meta = computed(() => payload.value?.meta || {});
const events = computed(() => payload.value?.events || []);
const eventLinks = computed(() => payload.value?.eventLinks || []);
const layerMeta = computed(
  () => LAYERS.find((item) => item.id === layer.value) || LAYERS[0]
);

const model = computed(() => {
  const term = keyword.value.trim();
  if (term) return searchGraphModel(payload.value, term, layer.value);
  if (layer.value !== "events") {
    return buildGraphModel(payload.value, layer.value);
  }
  if (viewMode.value === "cluster") {
    if (activeCluster.value) {
      return buildClusterDetailModel(
        payload.value,
        activeCluster.value,
        "events"
      );
    }
    return buildClusterModel(payload.value, {
      minLinkCount: clusterMinLink.value
    });
  }
  return buildGraphModel(payload.value, "events");
});

const isClusterOverview = computed(
  () =>
    layer.value === "events" &&
    viewMode.value === "cluster" &&
    !activeCluster.value &&
    !keyword.value.trim()
);

const isClusterDetail = computed(
  () =>
    layer.value === "events" &&
    viewMode.value === "cluster" &&
    Boolean(activeCluster.value) &&
    !keyword.value.trim()
);

const displayedEventCount = computed(() => model.value.stats?.events || 0);

const positions = computed(() =>
  layoutGraph(model.value.nodes, model.value.edges, {
    width: Math.max(stageSize.value.width, 320),
    height: Math.max(stageSize.value.height, 320),
    seed: layoutSeed.value
  })
);

const positionedNodes = computed(() =>
  model.value.nodes.map((node) => ({
    ...node,
    ...(positions.value.get(node.id) || {
      x: stageSize.value.width / 2,
      y: stageSize.value.height / 2
    })
  }))
);

const nodeById = computed(
  () => new Map(positionedNodes.value.map((node) => [node.id, node]))
);

const positionedEdges = computed(() =>
  model.value.edges
    .map((edge) => {
      const from = nodeById.value.get(edge.source);
      const to = nodeById.value.get(edge.target);
      if (!from || !to) return null;
      return { ...edge, ...edgeGeometry(from, to, edge) };
    })
    .filter(Boolean)
);

const statsLine = computed(() => {
  const stats = model.value.stats || {};
  if (keyword.value.trim()) {
    return `检索到 ${stats.events || 0} 个事件 · ${model.value.edges.length} 条关联`;
  }
  if (isClusterOverview.value) {
    const suffix = clusterMinLink.value === 2 ? "（≥2）" : "";
    return `${stats.events || 0} 个事件 · ${stats.clusters || 0} 个地域 · ${stats.links || 0} 条地域关联${suffix}`;
  }
  if (isClusterDetail.value) {
    return `${activeCluster.value} · ${stats.events || 0} 个事件 · ${stats.links || 0} 条内部关联`;
  }
  if (layer.value === "events") {
    return `${stats.events || 0} 个事件 · ${stats.links || 0} 条事件关联`;
  }
  if (layer.value === "bridges") {
    return `${stats.events || 0} 个事件 · ${stats.shared || 0} 个共享实体 · ${model.value.edges.length} 条关联`;
  }
  return `${stats.events || 0} 个事件 · ${stats.entities || 0} 个事件要素 · ${model.value.edges.length} 条关系`;
});

const linkLegendLabel = computed(() =>
  isClusterOverview.value ? "地域关联" : "事件关联"
);

const canvasHint = computed(() => {
  if (keyword.value.trim()) return `检索“${keyword.value.trim()}”`;
  if (isClusterOverview.value) {
    return clusterMinLink.value === 2
      ? "点击地域进入 · 只显示 ≥2 条关联"
      : "点击地域进入 · 显示全部地域关联";
  }
  if (isClusterDetail.value) {
    return `${activeCluster.value} 地域内事件 · 点击“全部地域”返回`;
  }
  if (viewMode.value === "flat" && displayedEventCount.value > 24) {
    return "事件较多，建议切回“聚合”按地域查看";
  }
  return layerMeta.value.hint;
});

const extractionLabel = computed(() =>
  meta.value.extraction_mode === "llm" ? "大模型抽取" : "规则抽取"
);

const storageLabel = computed(() =>
  meta.value.storage === "neo4j" ? "Neo4j 图数据库" : "本地快照"
);

const storageTone = computed(() =>
  meta.value.storage === "neo4j" ? "neo4j" : "snapshot"
);

const selectedNode = computed(
  () => nodeById.value.get(selectedId.value) || null
);

const selectedEvent = computed(() =>
  selectedNode.value?.type === "Event" ? selectedNode.value.raw : null
);

const selectedEntity = computed(() =>
  selectedNode.value && selectedNode.value.type !== "Event"
    ? selectedNode.value.raw
    : null
);

const relatedEvents = computed(() => {
  const event = selectedEvent.value;
  if (!event) return [];
  return eventLinks.value
    .filter((link) => link.source === event.id || link.target === event.id)
    .map((link) => {
      const otherId = link.source === event.id ? link.target : link.source;
      // 用全局事件表，避免地域详情里把跨地域关联误报为“没有关联”。
      const other = eventById.value.get(otherId);
      return other ? { event: other, link } : null;
    })
    .filter(Boolean);
});

const eventNames = computed(
  () => new Map(events.value.map((event) => [event.id, event.name]))
);

const eventById = computed(
  () => new Map(events.value.map((event) => [event.id, event]))
);

const focusId = computed(() => hoveredId.value || selectedId.value || "");

const neighborIds = computed(() => {
  const ids = new Set();
  if (!focusId.value) return ids;
  ids.add(focusId.value);
  model.value.edges.forEach((edge) => {
    if (edge.source === focusId.value) ids.add(edge.target);
    if (edge.target === focusId.value) ids.add(edge.source);
  });
  return ids;
});

const searchMatches = computed(() => {
  const term = keyword.value.trim().toLowerCase();
  if (!term) return null;
  const matched = new Set();
  model.value.nodes.forEach((node) => {
    const raw = node.raw || {};
    const haystack = [
      node.label,
      node.sublabel,
      labelMeta(node.type).name,
      raw.focus,
      raw.detail,
      raw.summary,
      raw.topic,
      raw.region,
      raw.timeText,
      ...(raw.topics || []).map((item) => item.name),
      ...(raw.actors || []).map((item) => item.name),
      ...(raw.locations || []).map((item) => item.name),
      ...(raw.eventIds || []).map((id) => eventNames.value.get(id) || "")
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (haystack.includes(term)) matched.add(node.id);
  });
  return matched;
});

const legendTypes = computed(() => {
  const order = [
    "Event",
    "Cluster",
    "Topic",
    "Actor",
    "Location",
    "Cause",
    "Consequence"
  ];
  const present = new Set(model.value.nodes.map((node) => node.type));
  return order.filter((type) => present.has(type));
});

const canvasTransform = computed(() => {
  const centerX = stageSize.value.width / 2;
  const centerY = stageSize.value.height / 2;
  return `translate(${(centerX + panX.value).toFixed(2)} ${(
    centerY + panY.value
  ).toFixed(2)}) scale(${scale.value}) translate(${-centerX} ${-centerY})`;
});

function edgeGeometry(from, to, edge) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const distance = Math.hypot(dx, dy) || 1;
  const ux = dx / distance;
  const uy = dy / distance;
  const x1 = from.x + ux * (from.radius + 3);
  const y1 = from.y + uy * (from.radius + 3);
  const x2 = to.x - ux * (to.radius + 3);
  const y2 = to.y - uy * (to.radius + 3);
  const bend =
    edge.group === "EventLink" ? ((hashCode(edge.id) % 9) - 4) * 3.2 : 0;
  const labelOffset = 13;
  if (!bend) {
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    return {
      x1,
      y1,
      x2,
      y2,
      path: `M ${x1} ${y1} L ${x2} ${y2}`,
      labelX: mx - uy * labelOffset,
      labelY: my + ux * labelOffset
    };
  }
  const cx = (x1 + x2) / 2 + -uy * bend;
  const cy = (y1 + y2) / 2 + ux * bend;
  return {
    x1,
    y1,
    x2,
    y2,
    path: `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`,
    labelX: cx - uy * labelOffset,
    labelY: cy + ux * labelOffset
  };
}

function hexPoints(radius) {
  return Array.from({ length: 6 }, (_, index) => {
    const angle = (Math.PI / 3) * index - Math.PI / 2;
    const x = (Math.cos(angle) * radius).toFixed(2);
    const y = (Math.sin(angle) * radius).toFixed(2);
    return `${x},${y}`;
  }).join(" ");
}

function hashCode(value) {
  let hash = 0;
  const text = String(value);
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) % 100003;
  }
  return hash;
}

function isNodeDimmed(node) {
  const matches = searchMatches.value;
  if (matches) return !matches.has(node.id);
  if (focusId.value && !neighborIds.value.has(node.id)) return true;
  return false;
}

function nodeClasses(node) {
  return {
    selected: node.id === selectedId.value,
    focused: node.id === focusId.value,
    dimmed: isNodeDimmed(node),
    matched: Boolean(searchMatches.value?.has(node.id)),
    shared: node.shared
  };
}

function edgeState(edge) {
  const matches = searchMatches.value;
  if (matches) {
    return matches.has(edge.source) || matches.has(edge.target)
      ? "active"
      : "dim";
  }
  if (focusId.value) {
    return neighborIds.value.has(edge.source) &&
      neighborIds.value.has(edge.target)
      ? "active"
      : "dim";
  }
  return "";
}

function edgeClasses(edge) {
  const state = edgeState(edge);
  return {
    active: state === "active",
    dimmed: state === "dim"
  };
}

function edgeStyle(edge) {
  const weight = Number.isFinite(edge.weight) ? edge.weight : 0.4;
  const crowded = model.value.edges.length > 120;
  const width = Math.min(3, 1 + weight * 0.45) * (crowded ? 0.55 : 1);
  return { strokeWidth: width.toFixed(2) };
}

function showEdgeLabel(edge) {
  if (edge.group === "ClusterLink") {
    return [hoveredId.value, selectedId.value].some(
      (id) => id && (edge.source === id || edge.target === id)
    );
  }
  if (edge.group !== "EventLink") return false;
  const focused = [selectedId.value, hoveredId.value].some(
    (id) => id && (edge.source === id || edge.target === id)
  );
  if (focused) return true;
  if (keyword.value.trim()) return model.value.edges.length <= 30;
  return model.value.edges.length <= 4 && scale.value >= 0.95;
}

function showEventMeta(node) {
  if (node.id === selectedId.value || node.id === hoveredId.value) return true;
  if (searchMatches.value?.has(node.id)) return true;
  if (keyword.value.trim()) return true;
  const count = displayedEventCount.value;
  if (count > 24) return scale.value >= 1.5;
  if (count > 12) return scale.value >= 1.1;
  return true;
}

function showNodeLabel(node) {
  if (node.type === "Cluster") return true;
  if (node.type === "Event") {
    if (node.id === selectedId.value || node.id === hoveredId.value) return true;
    if (searchMatches.value?.has(node.id)) return true;
    if (keyword.value.trim()) return true;
    const count = displayedEventCount.value;
    if (count > 24) return scale.value >= 1.5;
    if (count > 12) return scale.value >= 1.1;
    return true;
  }
  if (node.shared) return true;
  if (node.id === selectedId.value || node.id === hoveredId.value) return true;
  if (scale.value >= 1.25) return true;
  return Boolean(searchMatches.value?.has(node.id));
}

function percent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  return `${Math.round(Number(value) * 100)}%`;
}

function barWidth(value) {
  if (value === null || value === undefined) return "0%";
  return `${Math.min(100, Math.max(0, Number(value) * 100))}%`;
}

function originLabel(origin) {
  if (origin === "strategy_run") return "策略运行事件";
  if (origin === "legacy_corpus") return "历史语料事件";
  if (origin === "event_store") return "事件库事件";
  return "历史复现事件";
}

function enterCluster(node) {
  activeCluster.value = node.raw?.province || node.label;
  selectedId.value = "";
  hoveredId.value = "";
  tooltip.value = null;
  resetView();
}

function selectNode(node) {
  if (!node) return;
  if (node.type === "Cluster") {
    enterCluster(node);
    return;
  }
  selectedId.value = selectedId.value === node.id ? "" : node.id;
}

function toggleClusterLinks() {
  clusterMinLink.value = clusterMinLink.value === 2 ? 1 : 2;
  clearSelection();
}

function setViewMode(mode) {
  if (viewMode.value === mode) return;
  viewMode.value = mode;
  activeCluster.value = "";
  clearSelection();
  resetView();
}

function backToClusters() {
  activeCluster.value = "";
  clearSelection();
  resetView();
}

function selectNodeById(id) {
  if (nodeById.value.has(id)) selectedId.value = id;
}

function selectRelatedEvent(id) {
  const event = eventById.value.get(id);
  if (!event) return;
  keyword.value = "";
  if (layer.value === "events" && viewMode.value === "cluster") {
    activeCluster.value = eventProvince(event);
  }
  selectedId.value = id;
  resetView();
}

function clearSelection() {
  selectedId.value = "";
  hoveredId.value = "";
  tooltip.value = null;
}

function eventName(id) {
  return eventNames.value.get(id) || id;
}

function onNodeEnter(node, event) {
  hoveredId.value = node.id;
  showTooltip(node, event);
}

function onNodeFocus(node) {
  hoveredId.value = node.id;
  tooltip.value = null;
}

function onNodeLeave() {
  hoveredId.value = "";
  tooltip.value = null;
}

function showTooltip(node, event) {
  const stage = stageRef.value;
  if (!stage || !event) return;
  const rect = stage.getBoundingClientRect();
  tooltip.value = {
    node,
    x: Math.min(Math.max(event.clientX - rect.left + 16, 12), rect.width - 220),
    y: Math.min(Math.max(event.clientY - rect.top + 14, 12), rect.height - 96)
  };
}

function moveTooltip(event) {
  if (!tooltip.value || !event) return;
  const stage = stageRef.value;
  if (!stage) return;
  const rect = stage.getBoundingClientRect();
  tooltip.value = {
    ...tooltip.value,
    x: Math.min(Math.max(event.clientX - rect.left + 16, 12), rect.width - 220),
    y: Math.min(Math.max(event.clientY - rect.top + 14, 12), rect.height - 96)
  };
}

function stageScale() {
  return 1;
}

function zoomBy(factor, anchor) {
  const next = Math.min(2.6, Math.max(0.5, scale.value * factor));
  const ratio = next / scale.value;
  if (anchor) {
    const centerX = stageSize.value.width / 2;
    const centerY = stageSize.value.height / 2;
    panX.value = anchor.x - centerX - (anchor.x - centerX - panX.value) * ratio;
    panY.value = anchor.y - centerY - (anchor.y - centerY - panY.value) * ratio;
  }
  scale.value = Number(next.toFixed(3));
}

function onWheel(event) {
  const stage = stageRef.value;
  if (!stage) return;
  const rect = stage.getBoundingClientRect();
  const anchor = {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top
  };
  zoomBy(event.deltaY < 0 ? 1.12 : 0.89, anchor);
}

function resetView() {
  scale.value = 1;
  panX.value = 0;
  panY.value = 0;
}

function relayout() {
  layoutSeed.value = (layoutSeed.value + 1) % 12;
  resetView();
}

function onStagePointerDown(event) {
  if (event.button !== 0) return;
  if (event.target?.closest?.(".graph-node, button, a, .graph-inspector")) {
    return;
  }
  dragging.value = true;
  event.preventDefault();
  dragOrigin = {
    x: event.clientX,
    y: event.clientY,
    panX: panX.value,
    panY: panY.value,
    moved: false
  };
  try {
    stageRef.value?.setPointerCapture?.(event.pointerId);
  } catch {
    // 指针已失效时忽略捕获失败，拖拽仍由 pointermove 驱动。
  }
}

function onStagePointerMove(event) {
  if (!dragging.value || !dragOrigin) return;
  const dx = event.clientX - dragOrigin.x;
  const dy = event.clientY - dragOrigin.y;
  if (!dragOrigin.moved && Math.hypot(dx, dy) > 4) {
    dragOrigin.moved = true;
  }
  if (!dragOrigin.moved) return;
  panX.value = dragOrigin.panX + dx;
  panY.value = dragOrigin.panY + dy;
}

function onStagePointerUp(event) {
  if (!dragging.value) return;
  const moved = Boolean(dragOrigin?.moved);
  dragging.value = false;
  dragOrigin = null;
  try {
    stageRef.value?.releasePointerCapture?.(event.pointerId);
  } catch {
    // 指针已被系统释放时忽略。
  }
  if (!moved) clearSelection();
}

function onStageDoubleClick(event) {
  if (event.target?.closest?.(".graph-node, button, a, .graph-inspector")) {
    return;
  }
  resetView();
}

async function loadGraph() {
  loading.value = true;
  error.value = "";
  errorDetail.value = "";
  try {
    const data = await getKnowledgeGraph();
    if (!Array.isArray(data?.events) || !data.events.length) {
      throw new Error("图谱中没有可展示的历史事件。");
    }
    payload.value = data;
    const clusterStats = buildClusterModel(data).stats;
    viewMode.value =
      data.events.length > 20 && clusterStats.clusters >= 3
        ? "cluster"
        : "flat";
    activeCluster.value = "";
    clearSelection();
    resetView();
  } catch (loadError) {
    payload.value = null;
    const detail = String(loadError?.message || "未知错误");
    const unavailable = /json|fetch|network|failed|HTTP 4|HTTP 5|timeout/i.test(detail);
    error.value = unavailable
      ? "无法连接知识图谱"
      : detail;
    errorDetail.value = unavailable ? detail : "";
  } finally {
    loading.value = false;
  }
}

watch(layer, () => {
  activeCluster.value = "";
  clearSelection();
  resetView();
  layoutSeed.value = 0;
});

onMounted(() => {
  loadGraph();
  const stage = stageRef.value;
  if (!stage) return;
  const updateSize = () => {
    const rect = stage.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      stageSize.value = {
        width: Math.round(rect.width),
        height: Math.round(rect.height)
      };
    }
  };
  updateSize();
  resizeObserver = new ResizeObserver(updateSize);
  resizeObserver.observe(stage);
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
});
</script>

<template>
  <main class="graph-page">
    <header class="graph-header">
      <div class="graph-heading">
        <RouterLink class="graph-back" to="/workspace">← 工作台</RouterLink>
        <div class="graph-title">
          <p>KNOWLEDGE GRAPH</p>
          <h1>事件知识图谱</h1>
        </div>
      </div>

      <div class="graph-header-side">
        <div class="graph-meta-chips">
          <span><b>{{ meta.eventCount || 0 }}</b> 个事件</span>
          <span><b>{{ meta.eventLinkCount || 0 }}</b> 条事件关联</span>
          <span><b>{{ meta.sharedEntityCount || 0 }}</b> 个共享实体</span>
          <span class="storage-chip" :class="storageTone">
            <i></i>{{ storageLabel }}
          </span>
          <span class="muted">
            {{ meta.nodeCount || 0 }} 节点 / {{ meta.edgeCount || 0 }} 边 ·
            {{ extractionLabel }}
          </span>
        </div>
        <button
          class="graph-button"
          type="button"
          :disabled="loading"
          @click="loadGraph"
        >
          {{ loading ? "加载中" : "刷新" }}
        </button>
      </div>
    </header>

    <section class="graph-body">
      <div class="graph-toolbar">
        <div class="graph-layers" role="group" aria-label="图谱图层">
          <button
            v-for="item in LAYERS"
            :key="item.id"
            type="button"
            :class="{ active: layer === item.id }"
            :aria-pressed="layer === item.id"
            @click="layer = item.id"
          >
            {{ item.name }}
          </button>
        </div>

        <div
          v-if="layer === 'events'"
          class="graph-viewmode"
          role="group"
          aria-label="事件视图"
        >
          <button
            type="button"
            :class="{ active: viewMode === 'cluster' }"
            :aria-pressed="viewMode === 'cluster'"
            @click="setViewMode('cluster')"
          >
            聚合
          </button>
          <button
            type="button"
            :class="{ active: viewMode === 'flat' }"
            :aria-pressed="viewMode === 'flat'"
            @click="setViewMode('flat')"
          >
            平铺
          </button>
        </div>

        <button
          v-if="isClusterOverview"
          type="button"
          class="graph-link-filter"
          :class="{ active: clusterMinLink === 2 }"
          :aria-pressed="clusterMinLink === 2"
          @click="toggleClusterLinks"
        >
          {{ clusterMinLink === 2 ? "≥2 关联" : "全部关联" }}
        </button>

        <span v-if="activeCluster && !keyword.trim()" class="graph-breadcrumb">
          <button type="button" @click="backToClusters">全部地域</button>
          <b>/</b>
          <em>{{ activeCluster }}</em>
        </span>
        <span v-else class="graph-toolbar-hint">{{ layerMeta.hint }}</span>

        <label class="graph-search">
          <span>检索</span>
          <input
            v-model="keyword"
            type="search"
            placeholder="搜索事件、议题或主体"
          >
        </label>

        <div class="graph-zoom">
          <button type="button" title="缩小" aria-label="缩小" @click="zoomBy(0.86)">−</button>
          <span>{{ Math.round(scale * 100) }}%</span>
          <button type="button" title="放大" aria-label="放大" @click="zoomBy(1.16)">+</button>
          <button type="button" title="复位视图" @click="resetView">复位</button>
          <button type="button" title="重新布局" @click="relayout">重排</button>
        </div>
      </div>

      <div
        ref="stageRef"
        class="graph-stage"
        :class="{ dragging, focused: focusId }"
        @wheel.prevent="onWheel"
        @dblclick="onStageDoubleClick"
        @pointerdown="onStagePointerDown"
        @pointermove="onStagePointerMove"
        @pointerup="onStagePointerUp"
        @pointercancel="onStagePointerUp"
        @pointerleave="onStagePointerUp"
      >
        <svg
          v-if="payload && !error"
          class="graph-svg"
          :viewBox="`0 0 ${stageSize.width} ${stageSize.height}`"
          preserveAspectRatio="xMidYMid meet"
          role="img"
          :aria-label="`历史事件知识图谱：${positionedNodes.length} 个节点，${positionedEdges.length} 条关系`"
        >
          <g :transform="canvasTransform">
            <g class="graph-edges" aria-hidden="true">
              <path
                v-for="edge in positionedEdges"
                :key="edge.id"
                class="graph-edge"
                :class="[`edge-${edge.group}`, edgeClasses(edge)]"
                :d="edge.path"
                :style="edgeStyle(edge)"
              />
              <text
                v-for="edge in positionedEdges"
                v-show="showEdgeLabel(edge)"
                :key="`label-${edge.id}`"
                class="graph-edge-label"
                :x="edge.labelX"
                :y="edge.labelY - 6"
                text-anchor="middle"
              >
                {{ edge.label }}
              </text>
            </g>

            <g class="graph-nodes">
              <g
                v-for="node in positionedNodes"
                :key="node.id"
                class="graph-node"
                :class="[`node-${node.type}`, nodeClasses(node)]"
                :style="{ transform: `translate(${node.x}px, ${node.y}px)` }"
                role="button"
                tabindex="0"
                :aria-label="`${labelMeta(node.type).name}：${node.label}`"
                @mouseenter="onNodeEnter(node, $event)"
                @mousemove="moveTooltip"
                @mouseleave="onNodeLeave"
                @focus="onNodeFocus(node)"
                @blur="onNodeLeave"
                @click.stop="selectNode(node)"
                @keydown.enter.prevent="selectNode(node)"
                @keydown.space.prevent="selectNode(node)"
              >
                <circle
                  v-if="node.id === selectedId"
                  class="node-selection"
                  :r="node.radius + 10"
                />
                <circle
                  v-if="node.type === 'Event'"
                  class="node-halo"
                  :r="node.radius + 11"
                  :fill="node.color"
                />
                <circle
                  v-if="node.type === 'Event' || node.shape === 'circle'"
                  class="node-body"
                  :r="node.radius"
                  :fill="node.color"
                />
                <rect
                  v-else-if="node.shape === 'square'"
                  class="node-body"
                  :x="-node.radius"
                  :y="-node.radius"
                  :width="node.radius * 2"
                  :height="node.radius * 2"
                  :rx="node.type === 'Actor' ? 6 : 3"
                  :fill="node.color"
                />
                <polygon
                  v-else-if="node.shape === 'diamond'"
                  class="node-body"
                  :points="`0,${-node.radius * 1.25} ${node.radius * 1.25},0 0,${node.radius * 1.25} ${-node.radius * 1.25},0`"
                  :fill="node.color"
                />
                <polygon
                  v-else
                  class="node-body"
                  :points="hexPoints(node.radius)"
                  :fill="node.color"
                />

                <circle
                  v-if="node.shared"
                  class="node-shared-ring"
                  :r="node.radius + 5"
                />

                <text
                  v-if="node.type === 'Event'"
                  class="node-core-text event-core"
                  text-anchor="middle"
                  dy="4.6"
                >
                  事件
                </text>
                <text
                  v-else-if="node.type === 'Cluster'"
                  class="node-core-text cluster-core"
                  text-anchor="middle"
                  dy="6"
                >
                  {{ node.count }}
                </text>

                <text
                  v-if="showNodeLabel(node)"
                  class="node-label"
                  :class="{ 'event-label': node.type === 'Event' }"
                  text-anchor="middle"
                  :y="node.radius + (node.type === 'Event' ? 22 : node.type === 'Cluster' ? 24 : 14)"
                >
                  {{ node.label }}
                </text>
                <text
                  v-if="node.type === 'Event' && node.sublabel && showEventMeta(node)"
                  class="node-sub-label"
                  text-anchor="middle"
                  :y="node.radius + 37"
                >
                  {{ node.sublabel }}
                </text>
                <text
                  v-if="node.type === 'Event' && node.raw?.counts && showEventMeta(node)"
                  class="node-sub-label"
                  text-anchor="middle"
                  :y="node.radius + 51"
                >
                  {{ node.raw.counts.phases }} 阶段 · {{ node.raw.counts.subEvents }} 子事件 ·
                  {{ node.raw.counts.claims }} 通报
                </text>
                <text
                  v-if="node.type === 'Cluster'"
                  class="node-sub-label cluster-sub-label"
                  text-anchor="middle"
                  :y="node.radius + 40"
                >
                  {{ node.sublabel }}
                </text>
              </g>
            </g>
          </g>
        </svg>

        <div v-if="loading" class="graph-overlay">
          <strong>正在读取知识图谱…</strong>
        </div>

        <div v-else-if="error" class="graph-overlay error">
          <span>KNOWLEDGE GRAPH UNAVAILABLE</span>
          <strong>知识图谱加载失败</strong>
          <p>{{ error }}</p>
          <small v-if="errorDetail" class="graph-error-detail">{{ errorDetail }}</small>
          <div>
            <button class="graph-button primary" type="button" @click="loadGraph">
              重新加载
            </button>
          </div>
        </div>

        <template v-else-if="payload">
          <div class="graph-canvas-meta">
            <strong>{{ statsLine }}</strong>
            <span>{{ canvasHint }}</span>
          </div>

          <div v-if="!model.nodes.length" class="graph-overlay empty">
            <strong>没有匹配的事件</strong>
            <p>换个关键词，或清空检索查看全部事件。</p>
          </div>

          <div class="graph-legend" aria-label="图例">
            <div class="legend-group">
              <span
                v-for="type in legendTypes"
                :key="type"
                class="legend-item"
              >
                <i
                  :class="`legend-shape shape-${labelMeta(type).shape}`"
                  :style="{ background: labelMeta(type).color }"
                ></i>
                {{ labelMeta(type).name }}
              </span>
            </div>
            <div class="legend-group">
              <span v-if="layer === 'events'" class="legend-item">
                <i
                  class="legend-line"
                  :class="isClusterOverview ? 'cluster-link' : 'event-link'"
                ></i>
                {{ linkLegendLabel }}
              </span>
              <span v-else class="legend-item">
                <i class="legend-line element-link"></i>
                事件—要素
              </span>
              <span v-if="layer !== 'events'" class="legend-item">
                <i class="legend-ring"></i>
                跨事件共享
              </span>
            </div>
          </div>

          <span class="graph-canvas-hint">
            滚轮缩放 · 拖拽平移 · 双击复位
            <template v-if="isClusterOverview"> · 点击地域进入</template>
          </span>

          <div
            v-if="tooltip"
            class="graph-tooltip"
            :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }"
          >
            <span :style="{ color: tooltip.node.color }">
              {{ labelMeta(tooltip.node.type).name }}
            </span>
            <strong>{{ tooltip.node.label }}</strong>
            <small>{{ tooltip.node.sublabel }}</small>
          </div>

          <aside v-if="selectedNode" class="graph-inspector">
            <header class="inspector-head">
              <div>
                <span
                  class="inspector-type"
                  :style="{ color: selectedNode.color }"
                >
                  {{ labelMeta(selectedNode.type).name }}
                </span>
                <h2>{{ selectedNode.label }}</h2>
              </div>
              <button
                class="inspector-close"
                type="button"
                aria-label="关闭详情"
                @click="clearSelection"
              >
                ×
              </button>
            </header>

            <template v-if="selectedEvent">
              <p class="inspector-meta">
                {{ selectedEvent.timeText || "时间未知" }} ·
                {{ selectedEvent.region || "地域未知" }}
              </p>
              <p class="inspector-summary">{{ selectedEvent.summary || "暂无事件摘要。" }}</p>

              <div class="inspector-facts">
                <span>{{ selectedEvent.counts.phases }} 阶段</span>
                <span>{{ selectedEvent.counts.subEvents }} 子事件</span>
                <span>{{ selectedEvent.counts.claims }} 条通报</span>
                <span>{{ selectedEvent.topic || "未标注主题" }}</span>
                <span>
                  {{ originLabel(selectedEvent.origin) }}
                </span>
              </div>

              <div class="inspector-block">
                <span>初始舆情</span>
                <div class="opinion-row">
                  <span>负面</span>
                  <i><b :style="{ width: barWidth(selectedEvent.initialOpinion.negative) }"></b></i>
                  <small>{{ percent(selectedEvent.initialOpinion.negative) }}</small>
                </div>
                <div class="opinion-row">
                  <span>中性</span>
                  <i><b :style="{ width: barWidth(selectedEvent.initialOpinion.neutral) }"></b></i>
                  <small>{{ percent(selectedEvent.initialOpinion.neutral) }}</small>
                </div>
                <div class="opinion-row">
                  <span>正面</span>
                  <i><b :style="{ width: barWidth(selectedEvent.initialOpinion.positive) }"></b></i>
                  <small>{{ percent(selectedEvent.initialOpinion.positive) }}</small>
                </div>
              </div>

              <div class="inspector-block">
                <span>关联事件 · {{ relatedEvents.length }}</span>
                <div v-if="relatedEvents.length" class="related-list">
                  <button
                    v-for="row in relatedEvents"
                    :key="row.event.id"
                    type="button"
                    @click="selectRelatedEvent(row.event.id)"
                  >
                    <strong>{{ row.event.name }}</strong>
                    <small>{{ row.event.region || "地域未知" }} · {{ row.link.label }}</small>
                    <div class="shared-chips">
                      <em v-for="entity in row.link.shared" :key="entity.id">
                        {{ entity.name }}
                      </em>
                    </div>
                  </button>
                </div>
                <p v-else class="inspector-empty">
                  该事件暂未与其它事件共享议题、主体或地域。
                </p>
              </div>

              <div class="inspector-block">
                <span>关键议题</span>
                <div class="inspector-chips">
                  <em v-for="topic in selectedEvent.topics" :key="topic.id">
                    {{ topic.name }}
                  </em>
                </div>
              </div>

              <div class="inspector-block">
                <span>相关主体</span>
                <div class="inspector-chips">
                  <em v-for="actor in selectedEvent.actors" :key="actor.id">
                    {{ actor.name }}
                  </em>
                </div>
              </div>
            </template>

            <template v-else-if="selectedEntity">
              <p class="inspector-summary">
                {{ selectedEntity.detail || "该实体没有补充说明。" }}
              </p>
              <div class="inspector-facts">
                <span>{{ selectedEntity.typeName }}</span>
                <span>
                  {{
                    selectedEntity.shared
                      ? `被 ${selectedEntity.eventIds.length} 个事件共享`
                      : "仅属于单个事件"
                  }}
                </span>
              </div>

              <div class="inspector-block">
                <span>涉及事件 · {{ selectedEntity.eventIds.length }}</span>
                <div class="related-list">
                  <button
                    v-for="id in selectedEntity.eventIds"
                    :key="id"
                    type="button"
                    @click="selectNodeById(id)"
                  >
                    <strong>{{ eventName(id) }}</strong>
                    <small>查看事件详情</small>
                  </button>
                </div>
              </div>
            </template>
          </aside>
        </template>
      </div>
    </section>
  </main>
</template>

<style src="../styles/graph.css"></style>
