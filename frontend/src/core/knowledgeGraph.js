/**
 * 历史事件知识图谱的数据层。
 *
 * 数据来自后端 `GET /api/knowledge-graph`：后端读取 kg 管线产物
 * （Simulation2-main/kg/out/graph.json），按共享 Topic / Actor / Location /
 * Cause / Consequence 推导事件—事件关联。本模块只负责把事件视图组装成
 * 画布模型，并提供确定性的布局；不发起请求、不做抽取。
 */

export const LABEL_META = {
  Event: { name: "事件", color: "#e85d2a", shape: "circle" },
  Cluster: { name: "地域", color: "#1d746b", shape: "circle" },
  Topic: { name: "议题", color: "#4f6fa8", shape: "circle" },
  Actor: { name: "主体", color: "#1d746b", shape: "square" },
  Location: { name: "地点", color: "#b5813f", shape: "diamond" },
  Cause: { name: "成因", color: "#7b5fa6", shape: "hex" },
  Consequence: { name: "后果", color: "#c05952", shape: "square" }
};

export const LAYERS = [
  {
    id: "events",
    name: "事件关系",
    hint: "按地域聚合查看；点击地域进入局部事件关系"
  },
  {
    id: "bridges",
    name: "关联实体",
    hint: "展开把不同事件连起来的共享实体"
  },
  {
    id: "elements",
    name: "事件要素",
    hint: "展开每个事件的议题、主体、地点与成因（放大或悬停查看名称）"
  }
];

const PROVINCES = [
  "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
  "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
  "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
  "甘肃", "青海", "内蒙古", "广西", "西藏", "宁夏", "新疆",
  "香港", "澳门", "台湾"
];

const CITY_PROVINCE = {
  武汉: "湖北", 保定: "河北", 上饶: "江西", 北京: "北京", 上海: "上海",
  天津: "天津", 重庆: "重庆", 广州: "广东", 深圳: "广东", 南京: "江苏",
  杭州: "浙江", 成都: "四川", 西安: "陕西", 长沙: "湖南", 郑州: "河南",
  济南: "山东", 合肥: "安徽", 福州: "福建", 昆明: "云南", 贵阳: "贵州",
  苏州: "江苏", 青岛: "山东", 大连: "辽宁", 厦门: "福建", 宁波: "浙江",
  无锡: "江苏", 佛山: "广东", 东莞: "广东", 南通: "江苏", 三河: "河北"
};

export function eventProvince(event) {
  const text = `${event?.region || ""} ${event?.location || ""}`.trim();
  if (!text) return "未标注地域";
  const province = PROVINCES.find((name) => text.includes(name));
  if (province) return province;
  const city = Object.keys(CITY_PROVINCE).find((name) => text.includes(name));
  if (city) return CITY_PROVINCE[city];
  const region = String(event?.region || "")
    .replace(/(省|市|自治区|特别行政区|自治州|地区|县)$/u, "")
    .trim();
  return region || "未标注地域";
}

/**
 * 事件数量较多时的地域聚合视图。
 * 只显示地域节点和地域之间的关联数量，避免 60+ 事件和数百条边挤在一起。
 */
export function buildClusterModel(payload, options = {}) {
  const events = Array.isArray(payload?.events) ? payload.events : [];
  const minLinkCount = Math.max(1, Number(options.minLinkCount) || 1);
  const links = Array.isArray(payload?.eventLinks) ? payload.eventLinks : [];
  const groups = new Map();
  events.forEach((event) => {
    const province = eventProvince(event);
    if (!groups.has(province)) groups.set(province, []);
    groups.get(province).push(event);
  });

  const ordered = [...groups.entries()]
    .map(([province, list]) => ({ province, events: list }))
    .sort(
      (left, right) =>
        right.events.length - left.events.length ||
        left.province.localeCompare(right.province, "zh")
    );

  const nodes = ordered.map((group) => ({
    id: `cluster:${group.province}`,
    type: "Cluster",
    label: group.province,
    sublabel: `${group.events.length} 个事件`,
    count: group.events.length,
    color: "#1d746b",
    shape: "circle",
    radius: Math.min(48, 22 + Math.sqrt(group.events.length) * 4.2),
    weight: group.events.length,
    shared: false,
    raw: { province: group.province, events: group.events }
  }));

  const provinceByEvent = new Map(
    events.map((event) => [event.id, eventProvince(event)])
  );
  const groupedLinks = new Map();
  links.forEach((link) => {
    const left = provinceByEvent.get(link.source);
    const right = provinceByEvent.get(link.target);
    if (!left || !right || left === right) return;
    const [first, second] = [left, right].sort((a, b) => a.localeCompare(b, "zh"));
    const key = `${first}|${second}`;
    if (!groupedLinks.has(key)) {
      groupedLinks.set(key, {
        id: `cluster-link:${key}`,
        source: `cluster:${first}`,
        target: `cluster:${second}`,
        group: "ClusterLink",
        label: "",
        count: 0,
        weight: 0,
        shared: true,
        raw: []
      });
    }
    const item = groupedLinks.get(key);
    item.count += 1;
    item.weight += Number(link.weight) || 1;
    item.raw.push(link);
  });
  const edges = [...groupedLinks.values()]
    .filter((edge) => edge.count >= minLinkCount)
    .map((edge) => ({
      ...edge,
      label: `${edge.count} 条关联`
    }));

  return {
    nodes,
    edges,
    stats: {
      events: events.length,
      clusters: nodes.length,
      entities: 0,
      shared: 0,
      links: edges.length
    }
  };
}

/** 进入某个地域后，只保留该地域的事件与内部关联。 */
export function buildClusterDetailModel(payload, province, layer = "events") {
  const events = (payload?.events || []).filter(
    (event) => eventProvince(event) === province
  );
  const ids = new Set(events.map((event) => event.id));
  const eventLinks = (payload?.eventLinks || []).filter(
    (link) => ids.has(link.source) && ids.has(link.target)
  );
  const entities = (payload?.entities || []).filter((entity) =>
    (entity.eventIds || []).some((id) => ids.has(id))
  );
  return buildGraphModel(
    { ...payload, events, eventLinks, entities },
    layer
  );
}

function eventSearchText(event) {
  return [
    event?.name,
    event?.summary,
    event?.topic,
    event?.region,
    event?.timeText,
    ...(event?.topics || []).map((item) => item.name),
    ...(event?.actors || []).map((item) => item.name),
    ...(event?.locations || []).map((item) => item.name)
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

/** 搜索结果直接平铺为事件节点，避免聚合视图里搜不到具体事件。 */
export function searchGraphModel(payload, term, layer = "events") {
  const needle = String(term || "").trim().toLowerCase();
  if (!needle) return buildGraphModel(payload, layer);
  const events = (payload?.events || []).filter((event) =>
    eventSearchText(event).includes(needle)
  );
  const ids = new Set(events.map((event) => event.id));
  const eventLinks = (payload?.eventLinks || []).filter(
    (link) => ids.has(link.source) && ids.has(link.target)
  );
  const entities = (payload?.entities || []).filter((entity) =>
    (entity.eventIds || []).some((id) => ids.has(id))
  );
  return buildGraphModel(
    { ...payload, events, eventLinks, entities },
    layer
  );
}

const TYPE_RADIUS = {
  Event: 32,
  Topic: 16,
  Actor: 15,
  Location: 14,
  Cause: 15,
  Consequence: 15
};

export function truncate(value, max = 86) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (text.length <= max) return text || "—";
  return `${text.slice(0, max)}…`;
}

export function eventColor(event) {
  const valence = event?.valence;
  if (valence === "positive") return "#3f8f6a";
  if (valence === "neutral") return "#b5813f";
  return "#e85d2a";
}

export function labelMeta(label) {
  return LABEL_META[label] || { name: label || "实体", color: "#7d8c85", shape: "circle" };
}

/**
 * 组装画布模型。
 *
 * @param {object|null} payload 后端事件图谱视图。
 * @param {"events"|"bridges"|"elements"} layer 当前图层。
 */
export function buildGraphModel(payload, layer = "events") {
  const events = Array.isArray(payload?.events) ? payload.events : [];
  const entities = Array.isArray(payload?.entities) ? payload.entities : [];
  const links = Array.isArray(payload?.eventLinks) ? payload.eventLinks : [];
  const eventIds = new Set(events.map((event) => event.id));
  const nodes = [];
  const edges = [];

  events.forEach((event) => {
    const meta = labelMeta("Event");
    const eventRadius =
      layer === "events"
        ? events.length > 30
          ? 22
          : events.length > 12
            ? 28
            : 42
        : 34;
    nodes.push({
      id: event.id,
      type: "Event",
      label: event.name,
      sublabel: [event.timeText, event.region].filter(Boolean).join(" · "),
      color: eventColor(event),
      shape: meta.shape,
      radius: eventRadius,
      weight: 1,
      shared: false,
      raw: event
    });
  });

  const showEntities = layer !== "events";
  const visibleEntities = showEntities
    ? layer === "bridges"
      ? entities.filter((entity) => entity.shared)
      : entities
    : [];

  if (showEntities) {
    visibleEntities.forEach((entity) => {
      const meta = labelMeta(entity.label);
      nodes.push({
        id: entity.id,
        type: entity.label,
        label: truncate(entity.name, 10),
        sublabel: entity.detail || meta.name,
        color: entity.color || meta.color,
        shape: meta.shape,
        radius: TYPE_RADIUS[entity.label] || 13,
        weight: entity.shared ? 0.9 : 0.5,
        shared: Boolean(entity.shared),
        raw: entity
      });
    });

    visibleEntities.forEach((entity) => {
      (entity.eventIds || []).forEach((eventId) => {
        if (!eventIds.has(eventId)) return;
        edges.push({
          id: `rel:${eventId}|${entity.id}`,
          source: eventId,
          target: entity.id,
          group: entity.label,
          label: entity.typeName,
          weight: entity.shared ? 1 : 0.5,
          shared: Boolean(entity.shared),
          raw: entity
        });
      });
    });
  } else {
    links.forEach((link) => {
      if (!eventIds.has(link.source) || !eventIds.has(link.target)) return;
      edges.push({
        id: `link:${link.source}|${link.target}`,
        source: link.source,
        target: link.target,
        group: "EventLink",
        label: link.label,
        weight: link.weight,
        shared: true,
        raw: link
      });
    });
  }

  return {
    nodes,
    edges,
    stats: {
      events: events.length,
      entities: visibleEntities.length,
      shared: visibleEntities.filter((entity) => entity.shared).length,
      links: showEntities ? 0 : edges.length
    }
  };
}

/**
 * 确定性布局。
 *
 * 事件层：事件按圆周排布，直接展示事件之间的连线；
 * 实体层：事件固定为锚点，实体围绕所属事件初始化，共享实体落在相关事件之间，
 * 再用 Fruchterman-Reingold 力模型收敛并铺满画布。
 */
export function layoutGraph(nodes, edges, options = {}) {
  const width = Number(options.width) || 1000;
  const height = Number(options.height) || 680;
  const seed = Number(options.seed) || 0;
  const result = new Map();
  if (!nodes.length) return result;

  const centerX = width / 2;
  const centerY = height / 2;
  const seedOffset = (seed % 12) * 0.08;
  const list = nodes.map((node) => ({ ...node }));
  const byId = new Map(list.map((node) => [node.id, node]));
  const events = list.filter((node) => node.type === "Event");
  const entities = list.filter((node) => node.type !== "Event");
  const anchors = new Map();

  // 地域聚合视图：20 个左右的格子比圆环更容易读标签。
  if (list.length && list.every((node) => node.type === "Cluster")) {
    const count = list.length;
    const columns = Math.min(
      count,
      Math.max(
        3,
        Math.ceil(
          Math.sqrt((count * width) / Math.max(height, 1)) * 1.2
        )
      )
    );
    const rows = Math.ceil(count / columns);
    const marginX = Math.min(140, width * 0.12);
    const marginY = Math.min(100, height * 0.12);
    const left = marginX;
    const right = Math.max(left + 40, width - marginX);
    const top = marginY;
    const bottom = Math.max(top + 40, height - Math.min(170, height * 0.2));
    list.forEach((node, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      const x =
        columns === 1
          ? width / 2
          : left + (column / (columns - 1)) * (right - left);
      const y =
        rows === 1
          ? height / 2
          : top + (row / (rows - 1)) * (bottom - top);
      result.set(node.id, {
        x: Number(x.toFixed(2)),
        y: Number(y.toFixed(2))
      });
    });
    return result;
  }

  if (events.length === 1) {
    anchors.set(events[0].id, { x: centerX, y: centerY });
  } else if (height > width * 1.2) {
    // 竖屏：事件纵向排布，避免横版三角在窄屏里缩成一条线。
    events.forEach((node, index) => {
      const t = 0.12 + (index / Math.max(events.length - 1, 1)) * 0.76;
      anchors.set(node.id, {
        x: centerX,
        y: 64 + t * (height - 64 - 86)
      });
    });
  } else {
    const radiusX = Math.min(width * 0.3, height * 0.78);
    const radiusY = Math.min(height * 0.3, width * 0.4);
    events.forEach((node, index) => {
      const angle =
        -Math.PI / 2 + (index / Math.max(events.length, 1)) * Math.PI * 2 + seedOffset;
      anchors.set(node.id, {
        x: centerX + Math.cos(angle) * radiusX,
        y: centerY + Math.sin(angle) * radiusY
      });
    });
  }

  list.forEach((node) => {
    if (node.type === "Event") {
      const anchor = anchors.get(node.id) || { x: centerX, y: centerY };
      node.x = anchor.x;
      node.y = anchor.y;
      return;
    }
    const eventIds = node.raw?.eventIds || [];
    const eventAnchors = eventIds
      .map((eventId) => anchors.get(eventId))
      .filter(Boolean);
    const anchor = eventAnchors.length
      ? {
          x: eventAnchors.reduce((sum, item) => sum + item.x, 0) / eventAnchors.length,
          y: eventAnchors.reduce((sum, item) => sum + item.y, 0) / eventAnchors.length
        }
      : { x: centerX, y: centerY };
    let angle = hashText(node.id) * Math.PI * 2 + seedOffset;
    // 事件名称在节点正下方，实体从上方和两侧起步。
    if (Math.sin(angle) > 0.55) {
      angle += Math.cos(angle) >= 0 ? -1.9 : 1.9;
    }
    const distance = 92 + (hashText(`${node.id}:d`) % 5) * 18;
    node.x = anchor.x + Math.cos(angle) * distance;
    node.y = anchor.y + Math.sin(angle) * distance * 0.86;
  });

  if (entities.length) {
    const indexById = new Map(list.map((node, index) => [node.id, index]));
    const links = edges
      .map((edge) => ({
        source: indexById.get(edge.source),
        target: indexById.get(edge.target),
        weight: Number.isFinite(edge.weight) ? edge.weight : 0.5,
        shared: Boolean(edge.shared)
      }))
      .filter(
        (link) =>
          link.source !== undefined &&
          link.target !== undefined &&
          link.source !== link.target
      );

    const k = Math.sqrt((width * height) / Math.max(list.length, 1));
    const iterations = 320;
    for (let step = 0; step < iterations; step += 1) {
      const displacement = list.map(() => ({ x: 0, y: 0 }));

      for (let source = 0; source < list.length; source += 1) {
        for (let target = source + 1; target < list.length; target += 1) {
          let dx = list[source].x - list[target].x;
          let dy = list[source].y - list[target].y;
          const distance = Math.hypot(dx, dy) || 0.01;
          const force =
            ((k * k) / distance) *
            (0.85 + (list[source].radius + list[target].radius) / 140);
          dx /= distance;
          dy /= distance;
          displacement[source].x += dx * force;
          displacement[source].y += dy * force;
          displacement[target].x -= dx * force;
          displacement[target].y -= dy * force;
        }
      }

      links.forEach((link) => {
        const source = list[link.source];
        const target = list[link.target];
        let dx = source.x - target.x;
        let dy = source.y - target.y;
        const distance = Math.hypot(dx, dy) || 0.01;
        const force =
          ((distance * distance) / k) *
          (0.52 + link.weight * 0.5) *
          (link.shared ? 1.15 : 1);
        dx /= distance;
        dy /= distance;
        displacement[link.source].x -= dx * force;
        displacement[link.source].y -= dy * force;
        displacement[link.target].x += dx * force;
        displacement[link.target].y += dy * force;
      });

      const heat = 26 * (1 - step / iterations) + 1;
      const labelEvents = list.filter((item) => item.type === "Event");
      list.forEach((item) => {
        if (item.type === "Event") return;
        labelEvents.forEach((eventItem) => {
          const halfWidth = Math.min(
            190,
            Math.max(52, (String(eventItem.label || "").length * 11.5) / 2 + 10)
          );
          const top = eventItem.y + eventItem.radius + 4;
          const bottom = top + 62;
          const insideX =
            item.x + item.radius > eventItem.x - halfWidth &&
            item.x - item.radius < eventItem.x + halfWidth;
          const insideY =
            item.y + item.radius > top && item.y - item.radius < bottom;
          if (!insideX || !insideY) return;
          const pushUp = item.y + item.radius - top;
          const pushDown = bottom - (item.y - item.radius);
          if (pushUp <= pushDown) {
            item.y -= Math.min(7, Math.max(1.2, pushUp));
          } else {
            item.y += Math.min(7, Math.max(1.2, pushDown));
          }
        });
      });
      list.forEach((item, index) => {
        // 事件节点固定在锚点，实体围绕事件收敛，保证事件三角稳定。
        if (item.type === "Event") {
          const anchor = anchors.get(item.id) || { x: centerX, y: centerY };
          item.x = anchor.x;
          item.y = anchor.y;
          return;
        }
        displacement[index].x += (centerX - item.x) * 0.012;
        displacement[index].y += (centerY - item.y) * 0.012;
        const length =
          Math.hypot(displacement[index].x, displacement[index].y) || 1;
        const move = Math.min(length, heat);
        item.x += (displacement[index].x / length) * move;
        item.y += (displacement[index].y / length) * move;
      });
    }
  }

  fitToBox(list, width, height);

  // 节点半径与标签占位的碰撞消解，避免文字互相压住。
  for (let pass = 0; pass < 42; pass += 1) {
    for (let source = 0; source < list.length; source += 1) {
      for (let target = source + 1; target < list.length; target += 1) {
        const touchingEvent =
          list[source].type === "Event" || list[target].type === "Event";
        const minDistance =
          list[source].radius +
          list[target].radius +
          (touchingEvent ? 52 : 34);
        let dx = list[source].x - list[target].x;
        let dy = list[source].y - list[target].y;
        const distance = Math.hypot(dx, dy) || 0.01;
        if (distance >= minDistance) continue;
        const push = (minDistance - distance) / 2;
        dx /= distance;
        dy /= distance;
        list[source].x += dx * push;
        list[source].y += dy * push;
        list[target].x -= dx * push;
        list[target].y -= dy * push;
      }
    }
    list.forEach((item) => {
      item.x = clamp(item.x, item.radius + 26, width - item.radius - 26);
      item.y = clamp(item.y, item.radius + 34, height - item.radius - 72);
    });
  }

  list.forEach((item) => {
    result.set(item.id, {
      x: Number(item.x.toFixed(2)),
      y: Number(item.y.toFixed(2))
    });
  });
  return result;
}

function fitToBox(list, width, height) {
  if (!list.length) return;
  const paddingX = Math.min(120, Math.max(48, width * 0.075));
  const paddingTop = 74;
  const paddingBottom = 168;
  const xs = list.map((item) => item.x);
  const ys = list.map((item) => item.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const availableWidth = Math.max(width - paddingX * 2, 1);
  const availableHeight = Math.max(height - paddingTop - paddingBottom, 1);
  const scale = Math.min(1.8, availableWidth / spanX, availableHeight / spanY);
  const offsetX = paddingX + (availableWidth - spanX * scale) / 2;
  const offsetY = paddingTop + (availableHeight - spanY * scale) / 2;

  list.forEach((item) => {
    item.x = offsetX + (item.x - minX) * scale;
    item.y = offsetY + (item.y - minY) * scale;
  });
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function hashText(value) {
  let hash = 0;
  const text = String(value);
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) % 100003;
  }
  return (hash % 997) / 997;
}
