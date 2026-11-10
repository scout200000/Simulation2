# -*- coding: utf-8 -*-
"""生成零依赖的交互式图谱页面（Canvas 力导向布局，可离线打开）。"""

from __future__ import annotations

import json
from pathlib import Path

from pipelines.kg.ontology import NODE_LABELS

_COLORS = {
    "Event": "#e4572e",
    "SubEvent": "#f2a541",
    "Phase": "#8fbcd4",
    "Actor": "#6a994e",
    "Location": "#b07aa1",
    "Topic": "#4c78a8",
    "Cause": "#d37295",
    "Consequence": "#9d755d",
    "Claim": "#c0392b",
    "Snapshot": "#7f7f7f",
    "Source": "#b8b8b8",
}

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; background: #f7f8fa; color: #202124; overflow: hidden; }
  #stage { position: fixed; inset: 0; }
  canvas { display: block; width: 100%; height: 100%; cursor: grab; }
  canvas.dragging { cursor: grabbing; }
  .panel { position: fixed; background: rgba(255,255,255,.94); border: 1px solid #e3e6ea; border-radius: 10px; box-shadow: 0 6px 20px rgba(20,30,50,.08); }
  #head { top: 16px; left: 16px; padding: 14px 16px; width: 300px; }
  #head h1 { font-size: 16px; margin: 0 0 6px; }
  #head .sub { font-size: 12px; color: #5f6368; line-height: 1.6; }
  #head .stat { margin-top: 8px; font-size: 12px; color: #3c4043; }
  #head .stat b { font-size: 14px; color: #202124; }
  #legend { left: 16px; bottom: 16px; padding: 10px 12px; width: 300px; max-height: 46vh; overflow: auto; }
  #legend h2 { font-size: 12px; margin: 0 0 8px; color: #5f6368; font-weight: 600; }
  .legend-item { display: flex; align-items: center; gap: 8px; padding: 3px 4px; border-radius: 6px; cursor: pointer; font-size: 12px; }
  .legend-item:hover { background: #f1f3f5; }
  .legend-item.off { opacity: .35; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .legend-item .count { margin-left: auto; color: #80868b; font-variant-numeric: tabular-nums; }
  #tools { top: 16px; right: 16px; padding: 10px; display: flex; gap: 8px; align-items: center; }
  #search { width: 180px; border: 1px solid #dfe1e5; border-radius: 8px; padding: 6px 9px; font-size: 12px; outline: none; }
  #search:focus { border-color: #4c78a8; }
  button { border: 1px solid #dfe1e5; background: #fff; border-radius: 8px; padding: 6px 10px; font-size: 12px; cursor: pointer; color: #3c4043; }
  button:hover { background: #f1f3f5; }
  #tip { position: fixed; pointer-events: none; max-width: 320px; padding: 8px 10px; border-radius: 8px; background: rgba(32,33,36,.92); color: #fff; font-size: 12px; line-height: 1.55; opacity: 0; transition: opacity .12s; z-index: 10; }
  #hint { position: fixed; bottom: 16px; right: 16px; font-size: 11px; color: #9aa0a6; }
</style>
</head>
<body>
<div id="stage"><canvas id="graph"></canvas></div>

<div id="head" class="panel">
  <h1>事件知识图谱</h1>
  <div class="sub">__SUBTITLE__</div>
  <div class="stat">事件 <b id="stat-events">0</b> · 节点 <b id="stat-nodes">0</b> · 关系 <b id="stat-edges">0</b></div>
</div>

<div id="tools" class="panel">
  <input id="search" placeholder="搜索节点名称…">
  <button id="fit">适配视图</button>
</div>

<div id="legend" class="panel">
  <h2>图例（点击可显隐）</h2>
  <div id="legend-list"></div>
</div>

<div id="tip"></div>
<div id="hint">滚轮缩放 · 拖拽平移 · 拖动节点调整局部 · 点击节点看邻居 · 来源节点默认隐藏，点图例可开</div>

<script id="graph-data" type="application/json">__DATA__</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById('graph-data').textContent);
  const COLORS = __COLORS__;
  const canvas = document.getElementById('graph');
  const ctx = canvas.getContext('2d');
  const tip = document.getElementById('tip');
  const search = document.getElementById('search');

  const nodes = DATA.nodes.map((n, i) => ({
    ...n, x: 0, y: 0, vx: 0, vy: 0, degree: 0, visible: true, index: i
  }));
  const byId = new Map(nodes.map(n => [n.id, n]));
  const links = DATA.edges.map(e => ({ ...e, source: byId.get(e.source), target: byId.get(e.target) }))
    .filter(l => l.source && l.target);
  links.forEach(l => { l.source.degree++; l.target.degree++; });
  const neighbors = new Map(nodes.map(n => [n.id, new Set()]));
  links.forEach(l => { neighbors.get(l.source.id).add(l.target.id); neighbors.get(l.target.id).add(l.source.id); });

  const radius = n => n.label === 'Event' ? 16
    : (n.label === 'Source' || n.label === 'Snapshot') ? 4
    : Math.min(12, 5 + Math.sqrt(n.degree) * 2.0);
  const labelVisible = n => n.label === 'Event' || view.scale > 1.3;

  // 事件节点按三角形/网格摆放，子节点围绕自己的事件
  const eventNodes = nodes.filter(n => n.label === 'Event');
  const anchorById = new Map();
  if (eventNodes.length === 3) {
    eventNodes.forEach((n, i) => {
      const angle = -Math.PI / 2 + (i * Math.PI * 2) / 3;
      anchorById.set(n.id, { x: Math.cos(angle) * 760, y: Math.sin(angle) * 470 });
    });
  } else {
    const gridX = 720, gridY = 430;
    eventNodes.forEach((n, i) => {
      const col = i % 2, row = Math.floor(i / 2);
      anchorById.set(n.id, { x: (col - 0.5) * gridX * 2, y: (row - 0.5) * gridY * 2 });
    });
  }
  nodes.forEach(n => {
    const eventId = n.props && n.props.event_id ? 'event:' + n.props.event_id : null;
    const anchor = anchorById.get(n.label === 'Event' ? n.id : eventId);
    if (anchor) n.anchor = anchor;
  });

  // 初始布局：有归属的节点撒在所属事件周围，其余按标签分层，避免全部堆在原点
  const groups = {};
  nodes.forEach(n => (groups[n.label] = groups[n.label] || []).push(n));
  Object.entries(groups).forEach(([label, list], gi) => {
    const ring = 120 + gi * 50;
    list.forEach((n, i) => {
      const angle = (i / list.length) * Math.PI * 2 + gi * 0.7;
      if (n.anchor) {
        const hash1 = ((n.index + 1) * 2654435761) % 1000 / 1000;
        const hash2 = ((n.index + 7) * 40503) % 1000 / 1000;
        const radius = 40 + hash2 * 150;
        n.x = n.anchor.x + Math.cos(hash1 * Math.PI * 2) * radius;
        n.y = n.anchor.y + Math.sin(hash1 * Math.PI * 2) * radius;
      } else {
        n.x = Math.cos(angle) * ring;
        n.y = Math.sin(angle) * ring;
      }
    });
  });

  const view = { x: 0, y: 0, scale: 1 };
  let dragNode = null, panning = false, pointer = { x: 0, y: 0 }, hoverNode = null, selected = null;
  let alpha = 1, running = true, fitted = false;

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function simulate() {
    if (alpha <= 0.05) return;
    const strength = 0.3 + 0.7 * alpha;
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      if (!a.visible || a.label === 'Event') continue;
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        if (!b.visible || b.label === 'Event') continue;
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = 1; }
        if (d2 > 250000) continue;
        const f = (40000 * strength) / d2;
        const d = Math.sqrt(d2);
        a.vx += (dx / d) * f; a.vy += (dy / d) * f;
        b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
      }
    }
    links.forEach(l => {
      if (!l.source.visible || !l.target.visible) return;
      if (l.source.label === 'Event' && l.target.label === 'Event') return;
      const sameCluster = l.source.anchor && l.source.anchor === l.target.anchor;
      const dx = l.target.x - l.source.x, dy = l.target.y - l.source.y;
      const d = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const rest = sameCluster ? 140 : 320;
      const f = (d - rest) * (sameCluster ? 0.01 : 0.0008) * strength;
      l.source.vx += (dx / d) * f;
      l.source.vy += (dy / d) * f;
      l.target.vx -= (dx / d) * f;
      l.target.vy -= (dy / d) * f;
    });
    nodes.forEach(n => {
      if (!n.visible) return;
      if (n.label === 'Event') {
        n.x = n.anchor.x; n.y = n.anchor.y; n.vx = 0; n.vy = 0;
        return;
      }
      if (n.anchor) {
        n.vx += (n.anchor.x - n.x) * 0.01 * strength;
        n.vy += (n.anchor.y - n.y) * 0.01 * strength;
      }
      if (n !== dragNode) {
        n.x += Math.max(-8, Math.min(8, n.vx));
        n.y += Math.max(-8, Math.min(8, n.vy));
      }
      n.vx *= 0.78; n.vy *= 0.78;
    });
    alpha *= 0.99;
    if (alpha < 0.05) alpha = 0.05;
  }

  function toScreen(x, y) {
    return [x * view.scale + view.x, y * view.scale + view.y];
  }
  function toWorld(x, y) {
    return [(x - view.x) / view.scale, (y - view.y) / view.scale];
  }

  function draw() {
    const w = window.innerWidth, h = window.innerHeight;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#f7f8fa';
    ctx.fillRect(0, 0, w, h);

    const focusSet = selected ? new Set([selected.id, ...neighbors.get(selected.id)]) : null;

    // 事件聚类光环，帮助区分四个事件的子图
    eventNodes.forEach(n => {
      const [x, y] = toScreen(n.anchor.x, n.anchor.y);
      ctx.beginPath();
      ctx.arc(x, y, 340 * view.scale, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(228,87,46,.035)';
      ctx.fill();
      ctx.setLineDash([4, 6]);
      ctx.lineWidth = 1;
      ctx.strokeStyle = 'rgba(228,87,46,.18)';
      ctx.stroke();
      ctx.setLineDash([]);
    });

    ctx.lineWidth = 1;
    links.forEach(l => {
      if (!l.source.visible || !l.target.visible) return;
      const active = focusSet && (focusSet.has(l.source.id) && focusSet.has(l.target.id));
      let [x1, y1] = toScreen(l.source.x, l.source.y);
      let [x2, y2] = toScreen(l.target.x, l.target.y);
      ctx.strokeStyle = active ? 'rgba(60,64,67,.75)'
        : (focusSet ? 'rgba(154,160,166,.08)' : 'rgba(154,160,166,.28)');
      ctx.lineWidth = active ? 1.6 : 1;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    });

    nodes.forEach(n => {
      if (!n.visible) return;
      const [x, y] = toScreen(n.x, n.y);
      const r = radius(n) * Math.min(1.6, Math.max(.7, view.scale));
      const dim = focusSet && !focusSet.has(n.id);
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = COLORS[n.label] || '#888';
      ctx.globalAlpha = dim ? 0.22 : 0.95;
      ctx.fill();
      if (n === selected) {
        ctx.globalAlpha = 1;
        ctx.lineWidth = 2.5; ctx.strokeStyle = '#202124'; ctx.stroke();
      } else {
        ctx.globalAlpha = dim ? 0.2 : 0.9;
        ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.stroke();
      }
      ctx.globalAlpha = 1;

      const showLabel = labelVisible(n) || n === hoverNode || n === selected;
      if (showLabel && !dim) {
        const isEvent = n.label === 'Event';
        const text = n.name.length > 18 ? n.name.slice(0, 18) + '…' : n.name;
        ctx.font = (isEvent ? '600 13px' : '11px') + ' "Microsoft YaHei", system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = isEvent ? 'bottom' : 'top';
        const labelY = isEvent ? y - r - 5 : y + r + 3;
        ctx.lineWidth = 3.5; ctx.strokeStyle = 'rgba(247,248,250,.95)';
        ctx.strokeText(text, x, labelY);
        ctx.fillStyle = isEvent ? '#b03a1a' : (n.label === 'Source' ? '#80868b' : '#3c4043');
        ctx.fillText(text, x, labelY);
      }
    });
  }

  function loop() {
    if (running) {
      simulate();
      draw();
      if (!fitted && alpha <= 0.031) { fitted = true; fit(); }
    }
    requestAnimationFrame(loop);
  }

  function fit() {
    const list = nodes.filter(n => n.visible);
    if (!list.length) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    list.forEach(n => {
      minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
      minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
    });
    const w = window.innerWidth, h = window.innerHeight;
    const padLeft = 360, padRight = 90, padTop = 200, padBottom = 100;
    const availW = Math.max(200, w - padLeft - padRight);
    const availH = Math.max(200, h - padTop - padBottom);
    const scale = Math.min(
      availW / Math.max(1, maxX - minX),
      availH / Math.max(1, maxY - minY)
    );
    view.scale = Math.max(0.15, Math.min(2.2, scale));
    view.x = padLeft + (availW - (maxX - minX) * view.scale) / 2 - minX * view.scale;
    view.y = padTop + (availH - (maxY - minY) * view.scale) / 2 - minY * view.scale;
    draw();
  }

  function pick(mx, my) {
    let best = null, bestDist = Infinity;
    nodes.forEach(n => {
      if (!n.visible) return;
      const [x, y] = toScreen(n.x, n.y);
      const d = Math.hypot(mx - x, my - y);
      const r = Math.max(8, radius(n) * view.scale);
      if (d < r && d < bestDist) { best = n; bestDist = d; }
    });
    return best;
  }

  function tooltip(node, mx, my) {
    if (!node) { tip.style.opacity = 0; return; }
    const label = (DATA.labels && DATA.labels[node.label]) || node.label;
    const props = Object.entries(node.props || {}).slice(0, 5)
      .map(([k, v]) => '<div style="color:#bdc1c6">' + k + ': ' + String(v).slice(0, 60) + '</div>').join('');
    tip.innerHTML = '<div style="font-weight:600;margin-bottom:3px">' + label + ' · ' + node.name + '</div>' + props;
    tip.style.left = Math.min(mx + 14, window.innerWidth - 340) + 'px';
    tip.style.top = Math.min(my + 14, window.innerHeight - 160) + 'px';
    tip.style.opacity = 1;
  }

  canvas.addEventListener('pointerdown', e => {
    const hit = pick(e.clientX, e.clientY);
    if (hit) {
      dragNode = hit; selected = hit; alpha = Math.max(alpha, 0.35);
      canvas.setPointerCapture(e.pointerId);
    } else {
      panning = true; selected = null;
      canvas.setPointerCapture(e.pointerId);
    }
    pointer = { x: e.clientX, y: e.clientY };
    draw();
  });

  canvas.addEventListener('pointermove', e => {
    const [wx, wy] = toWorld(e.clientX, e.clientY);
    if (dragNode) {
      dragNode.x = wx; dragNode.y = wy; dragNode.vx = 0; dragNode.vy = 0;
      alpha = Math.max(alpha, 0.2); draw();
    } else if (panning) {
      view.x += e.clientX - pointer.x;
      view.y += e.clientY - pointer.y;
      pointer = { x: e.clientX, y: e.clientY };
      draw();
    } else {
      hoverNode = pick(e.clientX, e.clientY);
      tooltip(hoverNode, e.clientX, e.clientY);
      canvas.style.cursor = hoverNode ? 'pointer' : 'grab';
      if (hoverNode) draw();
    }
  });

  canvas.addEventListener('pointerup', () => { dragNode = null; panning = false; });

  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const [wx, wy] = toWorld(e.clientX, e.clientY);
    const factor = Math.exp(-e.deltaY * 0.001);
    view.scale = Math.max(0.15, Math.min(3.5, view.scale * factor));
    view.x = e.clientX - wx * view.scale;
    view.y = e.clientY - wy * view.scale;
    draw();
  }, { passive: false });

  document.getElementById('fit').addEventListener('click', fit);

  search.addEventListener('input', () => {
    const q = search.value.trim();
    if (!q) { selected = null; draw(); return; }
    const hit = nodes.find(n => n.name.includes(q)) ||
      nodes.find(n => (n.props && JSON.stringify(n.props).includes(q)));
    if (hit) { selected = hit; alpha = Math.max(alpha, 0.2); draw(); }
  });
  search.addEventListener('keydown', e => { if (e.key === 'Escape') { search.value = ''; selected = null; draw(); } });

  // 图例
  const legend = document.getElementById('legend-list');
  const counts = {};
  nodes.forEach(n => { counts[n.label] = (counts[n.label] || 0) + 1; });
  const hidden = new Set(['Source']);
  Object.keys(COLORS).forEach(label => {
    if (!counts[label]) return;
    const row = document.createElement('div');
    row.className = 'legend-item' + (hidden.has(label) ? ' off' : '');
    if (hidden.has(label)) nodes.forEach(n => { if (n.label === label) n.visible = false; });
    row.innerHTML = '<span class="dot" style="background:' + COLORS[label] + '"></span>' +
      '<span>' + ((DATA.labels && DATA.labels[label]) || label) + ' <span style="color:#9aa0a6">' + label + '</span></span>' +
      '<span class="count">' + counts[label] + '</span>';
    row.addEventListener('click', () => {
      if (hidden.has(label)) { hidden.delete(label); row.classList.remove('off'); }
      else { hidden.add(label); row.classList.add('off'); }
      nodes.forEach(n => { if (n.label === label) n.visible = !hidden.has(label); });
      draw();
      updateStats();
    });
    legend.appendChild(row);
  });

  function updateStats() {
    const visible = nodes.filter(n => n.visible).length;
    const ve = links.filter(l => l.source.visible && l.target.visible).length;
    document.getElementById('stat-nodes').textContent = visible;
    document.getElementById('stat-edges').textContent = ve;
    document.getElementById('stat-events').textContent = DATA.meta.events;
  }
  updateStats();

  window.addEventListener('resize', resize);
  resize();
  setTimeout(fit, 700);
  setTimeout(fit, 1600);
  loop();
})();
</script>
</body>
</html>
"""


def write_html(payload: dict, path: Path, title: str = "事件知识图谱") -> None:
    data = json.dumps(
        {**payload, "labels": NODE_LABELS},
        ensure_ascii=False,
    ).replace("</", "<\\/")
    meta = payload["meta"]
    subtitle = (
        f"{meta.get('event_scope', '现有实验事件')} · 抽取模式 {meta.get('extraction_mode', '-')}"
        f"<br>生成于 {meta.get('generated_at', '')}"
    )
    html = (
        _TEMPLATE.replace("__TITLE__", title)
        .replace("__SUBTITLE__", subtitle)
        .replace("__DATA__", data)
        .replace("__COLORS__", json.dumps(_COLORS, ensure_ascii=False))
    )
    path.write_text(html, encoding="utf-8")
