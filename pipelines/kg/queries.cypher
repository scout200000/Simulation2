// ============================================================
// 事件知识图谱 · 常用查询
// 在 Neo4j Browser（http://localhost:7474）里逐条执行。
// 图模型见 kg/README.md，数据由 kg/pipeline.py 生成。
// ============================================================

// 0. 导库后自检：节点与关系规模
MATCH (n)
RETURN labels(n)[0] AS 标签, count(*) AS 数量
ORDER BY 数量 DESC;

MATCH ()-[r]->()
RETURN type(r) AS 关系, count(*) AS 数量
ORDER BY 数量 DESC;

// 1. 事件总览
MATCH (e:Event)
OPTIONAL MATCH (e)-[:HAS_SUBEVENT]->(s:SubEvent)
OPTIONAL MATCH (e)-[:HAS_TOPIC]->(t:Topic)
RETURN e.name AS 事件, e.time_text AS 时间, e.region AS 地区,
       count(DISTINCT s) AS 子事件数, count(DISTINCT t) AS 议题数
ORDER BY 子事件数 DESC;

// 2. 单个事件的时间线：阶段 → 关键进展 → 舆情趋势
MATCH (e:Event {event_id: 'event_huxinyu_2022_001'})-[:HAS_PHASE]->(p:Phase)
OPTIONAL MATCH (p)<-[:IN_PHASE]-(s:SubEvent)
OPTIONAL MATCH (p)-[:HAS_SNAPSHOT]->(sn:Snapshot)
RETURN p.step AS 步, p.phase_name AS 阶段,
       collect(DISTINCT s.summary)[0..3] AS 关键进展,
       sn.trend AS 趋势, sn.negative_rate AS 负面率
ORDER BY 步;

// 3. 官方通报落在哪个阶段、对应哪条进展
MATCH (e:Event)-[:HAS_PHASE]->(p:Phase)
OPTIONAL MATCH (cl:Claim)-[:ABOUT]->(s:SubEvent)-[:IN_PHASE]->(p)
WHERE s.event_id = e.event_id
RETURN e.name AS 事件, p.step AS 步, p.phase_name AS 阶段,
       collect(DISTINCT cl.publisher) AS 发布方,
       collect(DISTINCT cl.status) AS 通报状态
ORDER BY 事件, 步;

// 4. 跨事件共享议题（≥2 个事件）
MATCH (t:Topic)<-[:HAS_TOPIC]-(e:Event)
WITH t, collect(DISTINCT e.name) AS 事件
WHERE size(事件) >= 2
RETURN t.name AS 议题, size(事件) AS 覆盖事件数, 事件
ORDER BY 覆盖事件数 DESC, 议题;

// 5. 同一主体出现在哪些事件（跨事件线索）
MATCH (a:Actor)<-[:INVOLVES]-(:SubEvent)<-[:HAS_SUBEVENT]-(e:Event)
RETURN a.name AS 主体, a.actor_type AS 类型,
       count(DISTINCT e) AS 事件数, collect(DISTINCT e.name) AS 事件
ORDER BY 事件数 DESC, 主体;

// 6. 因果链：事件 → 进展 → 原因 / 后果
MATCH (e:Event)-[:HAS_SUBEVENT]->(s:SubEvent)-[:CAUSED_BY]->(c:Cause)
OPTIONAL MATCH (s)-[:LED_TO]->(o:Consequence)
RETURN e.name AS 事件, s.summary AS 进展,
       c.text AS 原因, collect(DISTINCT o.text) AS 后果;

// 7. 官方说法与来源回溯
MATCH (cl:Claim)-[:SUPPORTED_BY]->(src:Source)
OPTIONAL MATCH (cl)-[:ABOUT]->(s:SubEvent)
RETURN cl.publisher AS 发布方, cl.published_at AS 时间, cl.status AS 状态,
       s.summary AS 对应进展, src.ref AS 来源
ORDER BY 时间;

// 8. 阶段舆情快照（来自 metrics_history.jsonl）
MATCH (e:Event)-[:HAS_PHASE]->(p:Phase)-[:HAS_SNAPSHOT]->(sn:Snapshot)
RETURN e.name AS 事件, p.step AS 步, p.phase_name AS 阶段,
       sn.trend AS 趋势, sn.negative_rate AS 负面率,
       sn.question_rate AS 质疑率, sn.accept_rate AS 接受率
ORDER BY 事件, 步;

// 9. 两个事件之间的关联路径（通过共享议题/主体相连）
MATCH (a:Event {event_id: 'event_baoding_driving_school_crash_20261006_001'}),
      (b:Event {event_id: 'event_huxinyu_2022_001'})
MATCH p = shortestPath((a)-[*..8]-(b))
RETURN [n IN nodes(p) | n.name] AS 路径节点,
       [r IN relationships(p) | type(r)] AS 关系;

// 10. 节点度排行：哪些议题/主体最“中心”
MATCH (n)-[r]-()
WHERE n:Topic OR n:Actor
RETURN labels(n)[0] AS 类型, n.name AS 名称, count(r) AS 度
ORDER BY 度 DESC
LIMIT 15;

// 11. 只保留数据、清空整张图（谨慎执行）
// MATCH (n) DETACH DELETE n;
