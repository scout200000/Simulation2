<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { getAuthSession, signOut } from "../core/auth.js";

const router = useRouter();
const canvasRef = ref(null);
const session = ref(getAuthSession());

const account = computed(() => session.value?.account || "");

let animationFrame = 0;
let resizeObserver = null;

const capabilities = [
  {
    index: "01",
    title: "事件与策略编排",
    description: "统一录入事件正文、声明状态和官方响应策略，形成可复现的实验输入。"
  },
  {
    index: "02",
    title: "多 Agent 决策",
    description: "按 Persona、情绪和可见评论约束每个 Agent 的决策与最终表达。"
  },
  {
    index: "03",
    title: "传播路径追踪",
    description: "记录邻居曝光、逐跳衰减、表达谱系以及逐轮和场景级传播指标。"
  },
  {
    index: "04",
    title: "会话级控制",
    description: "支持启动、连续推进、暂停、回滚、重启和运行中追加公告。"
  }
];

const steps = [
  ["01", "输入事件", "配置事件、公告内容和响应策略。"],
  ["02", "启动推演", "生成初始舆论环境并驱动 Agent 逐轮决策。"],
  ["03", "观察演化", "查看情绪趋势、网络传播和评论结构变化。"],
  ["04", "复盘实验", "回到历史会话继续运行或对比策略结果。"]
];

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({
    behavior: "smooth",
    block: "start"
  });
}

function setupNetwork() {
  const canvas = canvasRef.value;
  if (!canvas) return undefined;

  const context = canvas.getContext("2d");
  const reduceMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;
  let width = 0;
  let height = 0;
  let nodes = [];
  let visible = true;

  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);

    const nodeCount = Math.max(22, Math.min(42, Math.round(width / 34)));
    nodes = Array.from({ length: nodeCount }, (_, index) => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.18,
      vy: (Math.random() - 0.5) * 0.18,
      radius: index % 7 === 0 ? 4 : 2 + Math.random() * 1.5,
      tone: index % 5 === 0 ? "#177f6f" : index % 3 === 0 ? "#66b7a4" : "#cfe3db"
    }));

    draw();
  };

  const draw = () => {
    context.clearRect(0, 0, width, height);

    // 分远近两批描边：保留层次感，同时把 stroke 调用控制在两次
    const near = [];
    const far = [];
    for (let source = 0; source < nodes.length; source += 1) {
      for (let target = source + 1; target < nodes.length; target += 1) {
        const dx = nodes[source].x - nodes[target].x;
        const dy = nodes[source].y - nodes[target].y;
        const distanceSquared = dx * dx + dy * dy;
        if (distanceSquared > 190 * 190) continue;
        const bucket = distanceSquared < 120 * 120 ? near : far;
        bucket.push([
          nodes[source].x,
          nodes[source].y,
          nodes[target].x,
          nodes[target].y
        ]);
      }
    }

    const strokeEdges = (edges, alpha) => {
      if (!edges.length) return;
      context.beginPath();
      edges.forEach(([x1, y1, x2, y2]) => {
        context.moveTo(x1, y1);
        context.lineTo(x2, y2);
      });
      context.strokeStyle = `rgba(79, 152, 137, ${alpha})`;
      context.lineWidth = 0.8;
      context.stroke();
    };

    strokeEdges(far, 0.20);
    strokeEdges(near, 0.34);

    // 按颜色分组批量填充节点
    const groups = new Map();
    nodes.forEach((node) => {
      if (!groups.has(node.tone)) groups.set(node.tone, []);
      groups.get(node.tone).push(node);
    });
    groups.forEach((list, tone) => {
      context.beginPath();
      list.forEach((node) => {
        context.moveTo(node.x + node.radius, node.y);
        context.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      });
      context.fillStyle = tone;
      context.fill();
    });
  };

  const animate = () => {
    animationFrame = window.requestAnimationFrame(animate);
    if (!visible) return;

    nodes.forEach((node) => {
      node.x += node.vx;
      node.y += node.vy;

      if (node.x < 0 || node.x > width) node.vx *= -1;
      if (node.y < 0 || node.y > height) node.vy *= -1;
      node.x = Math.max(0, Math.min(width, node.x));
      node.y = Math.max(0, Math.min(height, node.y));
    });

    draw();
  };

  const start = () => {
    if (reduceMotion || animationFrame) return;
    animationFrame = window.requestAnimationFrame(animate);
  };

  const stop = () => {
    if (animationFrame) window.cancelAnimationFrame(animationFrame);
    animationFrame = 0;
  };

  // 滚出首屏后停止绘制，避免整页滚动时占用主线程
  const visibilityObserver = new IntersectionObserver(
    ([entry]) => {
      visible = entry.isIntersecting;
      if (visible) start();
      else stop();
    },
    { threshold: 0.01 }
  );

  resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(canvas);
  resize();
  visibilityObserver.observe(canvas);

  return () => {
    stop();
    resizeObserver?.disconnect();
    visibilityObserver.disconnect();
  };
}

let stopNetwork = null;
let revealObserver = null;

function setupReveal() {
  const targets = document.querySelectorAll(".reveal");
  if (!targets.length) return;
  const reduceMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;
  if (reduceMotion) {
    targets.forEach((target) => target.classList.add("is-visible"));
    return;
  }
  document.querySelector(".home-page")?.classList.add("reveal-enabled");
  if (!("IntersectionObserver" in window)) {
    targets.forEach((target) => target.classList.add("is-visible"));
    return;
  }
  revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      });
    },
    { threshold: 0.02, rootMargin: "0px 0px -3% 0px" }
  );
  targets.forEach((target) => revealObserver.observe(target));
}

const SNAP_QUERY = "(min-width: 980px) and (min-height: 720px)";
let wheelAccum = 0;
let wheelLocked = false;
let wheelResetTimer = 0;
let wheelUnlockTimer = 0;

function snapTargets() {
  const page = document.querySelector(".home-page");
  const footer = document.querySelector(".home-footer");
  if (!page) return [];
  const targets = [...document.querySelectorAll(".snap-section")].map(
    (section) => section.offsetTop - 75
  );
  if (footer) {
    targets.push(
      Math.min(
        footer.offsetTop + footer.offsetHeight - page.clientHeight,
        page.scrollHeight - page.clientHeight
      )
    );
  }
  return [...new Set(targets.filter((top) => top >= 0))].sort(
    (a, b) => a - b
  );
}

function goToPage(direction) {
  const page = document.querySelector(".home-page");
  if (!page) return;
  const targets = snapTargets();
  if (!targets.length) return;

  let index = 0;
  let nearest = Infinity;
  targets.forEach((top, position) => {
    const distance = Math.abs(top - page.scrollTop);
    if (distance < nearest) {
      nearest = distance;
      index = position;
    }
  });

  const next = Math.min(
    targets.length - 1,
    Math.max(0, index + direction)
  );
  if (next === index) return;

  const reduceMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;
  page.scrollTo({
    top: targets[next],
    behavior: reduceMotion ? "auto" : "smooth"
  });
}

function onWheel(event) {
  if (!window.matchMedia(SNAP_QUERY).matches || event.ctrlKey) return;
  event.preventDefault();
  if (wheelLocked) return;

  const page = document.querySelector(".home-page");
  const delta =
    event.deltaMode === 1
      ? event.deltaY * 16
      : event.deltaMode === 2
        ? event.deltaY * (page?.clientHeight || 800)
        : event.deltaY;
  wheelAccum += delta;
  window.clearTimeout(wheelResetTimer);
  wheelResetTimer = window.setTimeout(() => {
    wheelAccum = 0;
  }, 220);

  if (Math.abs(wheelAccum) < 40) return;
  const direction = wheelAccum > 0 ? 1 : -1;
  wheelAccum = 0;
  wheelLocked = true;
  goToPage(direction);

  window.clearTimeout(wheelUnlockTimer);
  wheelUnlockTimer = window.setTimeout(() => {
    wheelLocked = false;
  }, 780);
}

function onKeydown(event) {
  if (!window.matchMedia(SNAP_QUERY).matches) return;
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  const tag = (event.target?.tagName || "").toLowerCase();
  if (["input", "textarea", "select"].includes(tag)) return;

  let direction = 0;
  if (["ArrowDown", "PageDown"].includes(event.key)) direction = 1;
  if (["ArrowUp", "PageUp"].includes(event.key)) direction = -1;
  if (event.key === "Home") {
    event.preventDefault();
    document.querySelector(".home-page")?.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  if (event.key === "End") {
    const page = document.querySelector(".home-page");
    if (page) {
      event.preventDefault();
      const targets = snapTargets();
      page.scrollTo({
        top: targets[targets.length - 1] || 0,
        behavior: "smooth"
      });
    }
    return;
  }
  if (!direction) return;

  event.preventDefault();
  if (wheelLocked) return;
  wheelLocked = true;
  goToPage(direction);
  window.clearTimeout(wheelUnlockTimer);
  wheelUnlockTimer = window.setTimeout(() => {
    wheelLocked = false;
  }, 780);
}

onMounted(() => {
  stopNetwork = setupNetwork();
  setupReveal();
  window.addEventListener("wheel", onWheel, { passive: false });
  window.addEventListener("keydown", onKeydown);
});

onBeforeUnmount(() => {
  stopNetwork?.();
  revealObserver?.disconnect();
  window.removeEventListener("wheel", onWheel);
  window.removeEventListener("keydown", onKeydown);
  window.clearTimeout(wheelResetTimer);
  window.clearTimeout(wheelUnlockTimer);
});

function logout() {
  signOut();
  session.value = null;
  router.replace({ name: "portal" });
}
</script>

<template>
  <main class="home-page">
    <header class="home-header">
      <RouterLink class="home-brand" to="/">
        <span class="brand-mark">舆</span>
        <span class="brand-text">
          <strong>Simulation2</strong>
          <small>舆情推演控制台</small>
        </span>
      </RouterLink>

      <nav class="home-nav" aria-label="主页导航">
        <button type="button" @click="scrollToSection('capabilities')">核心能力</button>
        <button type="button" @click="scrollToSection('workflow')">推演流程</button>
        <button type="button" @click="scrollToSection('system')">系统定位</button>
      </nav>

      <div class="home-actions">
        <template v-if="account">
          <span class="account-chip">{{ account }}</span>
          <RouterLink class="btn btn-primary" to="/workspace">进入工作台</RouterLink>
          <button class="btn btn-ghost" type="button" @click="logout">退出</button>
        </template>
        <RouterLink v-else class="btn btn-primary" to="/login">登录</RouterLink>
      </div>
    </header>

    <section id="overview" class="home-hero snap-section">
      <div class="hero-copy">
        <span class="eyebrow">SOCIAL SIMULATION PLATFORM</span>
        <h1>把复杂的舆情演化，变成可观察、可控制的推演过程。</h1>
        <p class="hero-lead">
          面向社会舆情研究的多 Agent 模拟平台。事件输入、官方响应、个体决策与社交传播，
          被组织在同一套可回滚、可复核的实验流程里。
        </p>

        <div class="hero-actions">
          <RouterLink class="btn btn-primary btn-lg" :to="account ? '/workspace' : '/login'">
            {{ account ? "进入工作台" : "登录并开始推演" }}
          </RouterLink>
          <button class="btn btn-ghost btn-lg" type="button" @click="scrollToSection('workflow')">
            查看运行流程
          </button>
        </div>

        <dl class="hero-stats">
          <div><dt>Agent 参与者</dt><dd>30</dd></div>
          <div><dt>推演轮次</dt><dd>10</dd></div>
          <div><dt>官方响应策略</dt><dd>5</dd></div>
        </dl>
      </div>

      <div class="hero-visual" aria-label="控制台预览">
        <div class="preview-card">
          <header class="preview-head">
            <span class="preview-dot"></span>
            <strong>实时推演预览</strong>
            <small>NETWORK-LED SIMULATION</small>
          </header>
          <div class="preview-canvas">
            <canvas ref="canvasRef" class="home-network" aria-hidden="true"></canvas>
          </div>
          <footer class="preview-foot">
            <span>负面率 <b>57%</b></span>
            <span>活跃关系 <b>58</b></span>
            <span>已完成 <b>10 / 10</b></span>
          </footer>
        </div>
      </div>
    </section>

    <section id="capabilities" class="home-section capabilities-section snap-section">
      <div class="section-heading reveal">
        <span class="eyebrow">CAPABILITIES</span>
        <h2>从事件输入到传播结果，全过程可见。</h2>
      </div>

      <div class="capability-grid">
        <article v-for="item in capabilities" :key="item.index" class="reveal">
          <span class="capability-index">{{ item.index }}</span>
          <h3>{{ item.title }}</h3>
          <p>{{ item.description }}</p>
        </article>
      </div>
    </section>

    <section id="workflow" class="workflow-section snap-section">
      <div class="workflow-inner">
        <div class="section-heading reveal">
          <span class="eyebrow">WORKFLOW</span>
          <h2>一次推演，四个清晰阶段。</h2>
        </div>

        <div class="workflow-list">
          <article v-for="step in steps" :key="step[0]" class="reveal">
            <span class="step-index">{{ step[0] }}</span>
            <h3>{{ step[1] }}</h3>
            <p>{{ step[2] }}</p>
          </article>
        </div>
      </div>
    </section>

    <section id="system" class="home-section system-section snap-section">
      <div class="system-copy">
        <span class="eyebrow">SYSTEM POSITION</span>
        <h2>不是预测黑箱，而是可复核的舆情实验环境。</h2>
      </div>
      <div class="system-points reveal">
        <p>实验输入、策略状态和结果文件相互隔离，支持回滚、重启与历史复现。</p>
        <p>Agent 指标与评论池指标分开呈现，避免把个体状态和舆论环境混为一谈。</p>
        <p>传播记录保留完整谱系，可重新计算覆盖、深度、衰减与继续传播比例。</p>
      </div>
    </section>

    <footer class="home-footer">
      <span>Simulation2 · 舆情推演控制台</span>
      <span>Research simulation workspace</span>
    </footer>
  </main>
</template>

<style src="../styles/portal.css"></style>
