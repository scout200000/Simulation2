# -*- coding: utf-8 -*-
"""把「data/legacy_corpus/event.xlsx」的历史语料接入事件知识图谱。

原始文件来自 2026-10-15 交付包的「其他历史数据/event.xlsx」，仓库内副本见
``data/legacy_corpus/``（同目录 README 说明来源与口径）。

这份语料只有「标题 + 二手叙述正文 + 平台视频 ID + 评论文本」，没有
官方通报时间线、公众语境时间线和真实趋势，因此：

* 只生成 Event / SubEvent(单阶段) / Topic / Location / Source；
* 不生成 Claim（无通报原文）、Snapshot（无复现指标）、多阶段 Phase；
* 事件统一标记 ``origin=legacy_corpus``，与历史复现事件、策略运行事件区分；
* 抽取用确定性规则（短标题、议题词表、省份白名单、引号安全切句），
  不依赖大模型，避免把噪声写进共享图数据库。

调用入口在 ``pipelines/kg/pipeline.py --legacy-corpus <event.xlsx>``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipelines.kg.extract import Bundle
from pipelines.kg.ontology import validate_extraction

ORIGIN = "legacy_corpus"
PHASE = "事件背景（语料）"
MAX_SUB_EVENTS = 4

# ---------------------------------------------------------------------------
# 地理与议题词表
# ---------------------------------------------------------------------------

_PROVINCES: tuple[tuple[str, str], ...] = (
    ("黑龙江", "黑龙江省"),
    ("内蒙古", "内蒙古自治区"),
    ("新疆", "新疆维吾尔自治区"),
    ("西藏", "西藏自治区"),
    ("宁夏", "宁夏回族自治区"),
    ("广西", "广西壮族自治区"),
    ("北京", "北京市"),
    ("天津", "天津市"),
    ("上海", "上海市"),
    ("重庆", "重庆市"),
    ("河北", "河北省"),
    ("山西", "山西省"),
    ("辽宁", "辽宁省"),
    ("吉林", "吉林省"),
    ("江苏", "江苏省"),
    ("浙江", "浙江省"),
    ("安徽", "安徽省"),
    ("福建", "福建省"),
    ("江西", "江西省"),
    ("山东", "山东省"),
    ("河南", "河南省"),
    ("湖北", "湖北省"),
    ("湖南", "湖南省"),
    ("广东", "广东省"),
    ("海南", "海南省"),
    ("四川", "四川省"),
    ("贵州", "贵州省"),
    ("云南", "云南省"),
    ("陕西", "陕西省"),
    ("甘肃", "甘肃省"),
    ("青海", "青海省"),
    ("台湾", "台湾省"),
    ("香港", "香港特别行政区"),
    ("澳门", "澳门特别行政区"),
)

# 顺序即优先级：先匹配到的议题优先，每个事件最多取 2 个。
_TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("食品安全", ("淀粉肠", "叫花鸡", "食品安全", "吃出", "过期", "变质", "后厨")),
    ("未成年人保护", ("未成年", "初中生", "小学生", "小孩", "儿童", "少年", "体罚", "霸凌")),
    ("校园与教育", ("学校", "高校", "大学", "中学", "小学", "校园", "学生", "教师", "老师", "导师", "考生", "招生", "复试", "录取", "毕业", "学术", "论文", "食堂", "联名举报")),
    ("婚姻家庭与情感", ("离婚", "结婚", "婚礼", "新郎", "新娘", "彩礼", "相亲", "情感", "恋爱", "胖猫", "背债", "父亲", "儿子")),
    ("医疗与公共卫生", ("医院", "医生", "护士", "血浆", "急救", "医疗", "卫健", "献血", "坠亡")),
    ("劳动权益", ("工资", "员工", "开除", "劳动", "加班", "休假", "打工", "欠薪", "裁员")),
    ("交通事故与出行安全", ("车祸", "碰撞", "剐蹭", "追尾", "碾压", "车辆", "司机", "高速", "爆燃", "网约车", "骑行", "交通")),
    ("消费维权", ("退货", "退款", "消费者", "商家", "押金", "门票", "景区", "赔偿", "质量问题", "彩票", "刮奖", "下单", "起诉", "法院")),
    ("社会治安", ("殴打", "围殴", "打人", "砸", "烧毁", "盗窃", "防盗", "性侵", "猥亵", "斗殴", "持刀", "刑拘")),
    ("执法与权力监督", ("公安", "警方", "民警", "派出所", "拘留", "执法", "城管", "市监", "强拆", "举报", "所长", "局长", "纪委", "寻衅滋事", "立案")),
    ("公职人员行为", ("干部", "公职", "免职", "处分", "纪检", "提拔", "破格", "副镇长")),
    ("城市治理", ("招牌", "电梯", "小区", "商户", "城市", "拆除", "施工", "违建", "市容")),
    ("基层治理", ("春耕", "果园", "镇政府", "村委会", "阻拦", "承包", "土地", "强拆")),
    ("就业与企业经营", ("失业率", "就业", "企业", "债务", "被执行", "万达", "经营", "倒闭", "公司")),
    ("网络空间治理", ("直播", "短视频", "网红", "账号", "网暴", "谣言", "擦边", "热搜", "评论", "流量")),
    ("文娱与广告", ("短剧", "演员", "明星", "广告", "代言", "综艺", "票房", "演出")),
    ("动物保护", ("虐猫", "藏羚羊", "动物", "流浪猫", "流浪狗", "虐待")),
    ("涉外与历史", ("靖国神社", "日本", "留英", "海外", "境外", "外交")),
    ("社会心态", ("零负债", "热议", "观点", "心态")),
)

# 人工校对后的标题短名（未列出的按标点截断规则生成）。
_NAME_OVERRIDES: dict[int, str] = {
    1: "男子发12字评论被行拘",
    3: "黄杨钿甜天价耳环事件",
    4: "零负债人群引发热议",
    5: "小吃店少拿500元可多休10天",
    6: "女子逆行剐蹭骑车小伙",
    7: "男子私凿奥特曼石窟将被拆除",
    9: "南通文旅账号评论事件",
    10: "小米SU7高速碰撞爆燃致3死",
    13: "云南85后干部拟获提拔",
    15: "婚礼大屏出现不雅图片",
    16: "商家挂密码锁防穿完就退",
    17: "女生被曝长期发表极端言论",
    19: "武陵山天池不锈钢池底",
    21: "员工休息3分钟被开除",
    22: "高校要求毕业生删摆摊视频",
    23: "留英博士性侵多人被判终身监禁",
    24: "万达集团被恢复执行17亿",
    27: "罗帅宇湘雅二院坠亡",
    28: "男子让儿子签名替父背债",
    30: "沈阳学校被曝集体退货",
    31: "华中农大11名学生举报导师",
    38: "女企业家追讨工程款被刑拘",
    43: "派出所所长实名举报公安局长",
    44: "三名初中生砸车后车辆被烧毁",
    49: "民警菜市场宣传防盗",
    51: "小孩被独留路中央遭碾压",
    52: "新郎接亲途中恳求去钓鱼",
    53: "济南大学超市泡面挤走食堂",
    55: "江苏师大男生挥拳打倒女生",
    56: "叶县领导带人强拆创业果园",
    59: "99年女干部破格提拔副镇长",
    60: "网友质疑彩票店刮走有奖彩票",
}

# 规则容易误判的省份（城市与省份跨省提及）。
_REGION_OVERRIDES: dict[int, str] = {
    8: "湖北省",
    24: "",
    30: "辽宁省",
    31: "湖北省",
    40: "江苏省",
    46: "广东省",
    53: "山东省",
}

# 正文首个日期未必是事件节点日期，个别事件人工校准。
_TIME_OVERRIDES: dict[int, str] = {
    1: "2025年",
    13: "2025年5月",
    21: "2024年9月",
    59: "2024年3月",
}

# 人工校对后的议题（少量规则难判的事件直接指定）。
_TOPIC_OVERRIDES: dict[int, tuple[str, ...]] = {
    1: ("执法与权力监督",),
    2: ("婚姻家庭与情感",),
    3: ("公职人员行为",),
    4: ("社会心态",),
    5: ("劳动权益",),
    6: ("交通事故与出行安全", "执法与权力监督"),
    7: ("城市治理",),
    8: ("消费维权",),
    10: ("交通事故与出行安全",),
    9: ("网络空间治理", "公职人员行为"),
    12: ("城市治理",),
    13: ("公职人员行为",),
    14: ("文娱与广告",),
    15: ("消费维权", "婚姻家庭与情感"),
    11: ("城市治理", "执法与权力监督"),
    16: ("消费维权",),
    17: ("公职人员行为", "网络空间治理"),
    18: ("未成年人保护",),
    19: ("消费维权", "城市治理"),
    20: ("网络空间治理",),
    22: ("校园与教育", "网络空间治理"),
    23: ("社会治安", "涉外与历史"),
    24: ("就业与企业经营",),
    25: ("就业与企业经营",),
    26: ("医疗与公共卫生", "未成年人保护"),
    27: ("医疗与公共卫生", "社会治安"),
    28: ("婚姻家庭与情感",),
    21: ("劳动权益",),
    29: ("婚姻家庭与情感", "社会治安"),
    31: ("校园与教育", "学术诚信"),
    32: ("消费维权", "城市治理"),
    33: ("婚姻家庭与情感", "网络空间治理"),
    34: ("消费维权", "就业与企业经营"),
    35: ("食品安全",),
    36: ("校园与教育", "网络空间治理"),
    37: ("社会治安", "消费维权"),
    38: ("执法与权力监督", "就业与企业经营"),
    39: ("未成年人保护", "校园与教育"),
    40: ("动物保护", "校园与教育"),
    41: ("涉外与历史",),
    42: ("校园与教育", "社会治安"),
    43: ("执法与权力监督", "公职人员行为"),
    44: ("社会治安", "未成年人保护"),
    45: ("校园与教育", "医疗与公共卫生"),
    46: ("校园与教育",),
    47: ("基层治理",),
    48: ("网络空间治理", "文娱与广告"),
    50: ("校园与教育", "未成年人保护"),
    51: ("交通事故与出行安全", "未成年人保护"),
    52: ("婚姻家庭与情感",),
    53: ("校园与教育", "消费维权"),
    54: ("文娱与广告", "网络空间治理"),
    55: ("校园与教育", "社会治安"),
    56: ("基层治理", "执法与权力监督"),
    57: ("动物保护",),
    58: ("食品安全",),
    59: ("公职人员行为",),
    60: ("消费维权",),
}

# 明确的地点短语（未列出的只用省份，避免“城市/市场”这类误抽）。
_LOCATION_OVERRIDES: dict[int, str] = {
    1: "湘阴县",
    8: "武汉网红桥",
    11: "三河市",
    19: "武陵山天池",
    31: "华中农业大学",
    39: "河北邯郸",
    43: "河北兴隆",
    47: "开鲁县",
    50: "废弃校区",
    56: "河南叶县",
    59: "吉安县",
    30: "沈阳辽美中等职业学校",
    40: "南京大学",
    46: "南方医科大学",
    53: "济南大学",
}

_NEUTRAL_ROWS = {4, 14, 49, 52}

_DISCUSSION_MARKERS = ("质疑", "传闻", "网传", "被曝", "举报", "讨论", "争议", "谣言", "猜测", "不满")


@dataclass
class LegacyEvent:
    row: int
    title: str
    content: str
    year: str
    bilibili: str
    douyin: str


def load_legacy_events(path: str | Path) -> list[LegacyEvent]:
    """读取 event.xlsx（Sheet1：Title/Content/Year/Bilibili/Douyin）。"""

    from openpyxl import load_workbook

    workbook = load_workbook(Path(path), read_only=True, data_only=True)
    sheet = workbook["Sheet1"]
    rows = sheet.iter_rows(values_only=True)
    next(rows, None)
    events: list[LegacyEvent] = []
    for offset, row in enumerate(rows, start=2):
        title = str(row[0] or "").strip()
        content = str(row[1] or "").strip()
        if not title or not content:
            continue
        events.append(
            LegacyEvent(
                row=offset - 1,
                title=title,
                content=content,
                year=str(row[2] or "").strip(),
                bilibili=str(row[3] or "").strip(),
                douyin=str(row[4] or "").strip(),
            )
        )
    workbook.close()
    return events


def _event_id(event: LegacyEvent) -> str:
    return f"legacy_corpus_{event.row:03d}"


def build_bundles(events: list[LegacyEvent]) -> list[Bundle]:
    bundles: list[Bundle] = []
    for event in events:
        bundles.append(
            Bundle(
                event_id=_event_id(event),
                directory=Path("legacy_corpus"),
                event_input={
                    "event_id": _event_id(event),
                    "event_content": event.content,
                    "event_labels": {
                        "topic": "社会事件",
                        "event_valence": "neutral" if event.row in _NEUTRAL_ROWS else "negative",
                    },
                },
                manifest={
                    "title": event.title,
                    "source": "其他历史数据/event.xlsx",
                    "row": event.row,
                    "year": event.year,
                    "bilibili": event.bilibili,
                    "douyin": event.douyin,
                },
                origin=ORIGIN,
            )
        )
    return bundles


# ---------------------------------------------------------------------------
# 规则抽取
# ---------------------------------------------------------------------------


def _shorten(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip("，。；：、") + "…"


def _short_name(title: str, row: int) -> str:
    if row in _NAME_OVERRIDES:
        return _NAME_OVERRIDES[row]
    text = re.sub(r"[“”\"「」『』]", "", title.strip())
    for separator in ("。", "？", "！", "：", "?", "!", ":"):
        index = text.find(separator)
        if 6 <= index <= 30:
            text = text[:index]
            break
    else:
        index = text.find("，")
        if 6 <= index <= 30:
            text = text[:index]
    text = text.strip("，。；：、?？!！ ")
    return _shorten(text, 30)


def _event_region(title: str, content: str) -> str:
    for short, full in _PROVINCES:
        if short in title:
            return full
    for short, full in _PROVINCES:
        if short in content:
            return full
    return ""


def _event_time(title: str, content: str, year: str) -> str:
    match = re.search(r"(20\d{2})年(\d{1,2})月(?:(\d{1,2})日)?", title + " " + content)
    if match:
        return match.group(0)
    return year or ""


def _split_sentences(text: str) -> list[str]:
    """按句号/分号切句，但跳过引号内部，避免把引语切成两半。"""

    sentences: list[str] = []
    buffer: list[str] = []
    depth = 0
    for char in text:
        buffer.append(char)
        if char in "“「『(":
            depth += 1
        elif char in "”」』)":
            depth = max(0, depth - 1)
        elif char in "。；！？!?;" and depth == 0:
            sentence = "".join(buffer).strip()
            buffer = []
            if len(sentence) >= 10:
                sentences.append(sentence)
    tail = "".join(buffer).strip()
    if len(tail) >= 10:
        sentences.append(tail)
    return sentences


def _trim_sentence(sentence: str, limit: int = 110) -> str:
    sentence = sentence.strip()
    if len(sentence) <= limit:
        return sentence
    cut = sentence[:limit]
    for mark in ("。", "；", "，", "、"):
        index = cut.rfind(mark)
        if index >= limit * 0.5:
            return cut[: index + 1]
    return cut.rstrip() + "…"


def _assign_topics(title: str, content: str, row: int) -> list[dict[str, str]]:
    if row in _TOPIC_OVERRIDES:
        return [{"name": name, "focus": ""} for name in _TOPIC_OVERRIDES[row]]

    picked: list[str] = []
    for name, keywords in _TOPIC_RULES:
        if any(keyword in title for keyword in keywords):
            picked.append(name)
        if len(picked) >= 2:
            break
    if len(picked) < 2:
        for name, keywords in _TOPIC_RULES:
            if name in picked:
                continue
            if any(keyword in content for keyword in keywords):
                picked.append(name)
            if len(picked) >= 2:
                break
    if not picked:
        picked = ["社会事件"]
    return [{"name": name, "focus": ""} for name in picked]


def _sources(event: LegacyEvent) -> list[str]:
    refs = [f"其他历史数据/event.xlsx:Sheet1:row{event.row + 1}"]
    if event.bilibili:
        refs.append(f"https://www.bilibili.com/video/{event.bilibili}")
    if event.douyin:
        refs.append(f"https://www.douyin.com/video/{event.douyin}")
    return refs


def curated_extract(bundle: Bundle) -> dict[str, Any]:
    """确定性地把一条历史语料转成图谱要素（单阶段、无通报、无快照）。"""

    manifest = bundle.manifest or {}
    row = int(manifest.get("row") or 0)
    event = LegacyEvent(
        row=row,
        title=str(manifest.get("title") or ""),
        content=bundle.content,
        year=str(manifest.get("year") or ""),
        bilibili=str(manifest.get("bilibili") or ""),
        douyin=str(manifest.get("douyin") or ""),
    )

    name = _short_name(event.title, row)
    if row in _REGION_OVERRIDES:
        region = _REGION_OVERRIDES[row]
    else:
        region = _event_region(event.title, event.content)
    location = _LOCATION_OVERRIDES.get(row, "")
    topics = _assign_topics(event.title, event.content, row)
    sources = _sources(event)
    time_text = _TIME_OVERRIDES.get(row) or _event_time(event.title, event.content, event.year)

    sentences = _split_sentences(event.content)[:MAX_SUB_EVENTS]
    if not sentences:
        sentences = [_shorten(event.content, 100)]

    sub_events: list[dict[str, Any]] = []
    for index, sentence in enumerate(sentences, start=1):
        summary = _trim_sentence(sentence)
        kind = "discourse" if any(marker in summary for marker in _DISCUSSION_MARKERS) else "verified"
        sub_events.append(
            {
                "id": f"se_{index}",
                "summary": summary,
                "step": 1,
                "time_text": _event_time("", summary, ""),
                "phase": PHASE,
                "kind": kind,
                "status": "unconfirmed",
                "actors": [],
                "location": "",
                "causes": [],
                "consequences": [],
                "sources": sources if index == 1 else [f"其他历史数据/event.xlsx:Sheet1:row{row + 1}"],
            }
        )

    data = {
        "event": {
            "name": name,
            "summary": _shorten(event.content, 120),
            "topic": topics[0]["name"],
            "valence": "neutral" if row in _NEUTRAL_ROWS else "negative",
            "time_text": time_text,
            "region": region,
            "location": location,
        },
        "phases": [{"step": 1, "period": "", "phase": PHASE}],
        "sub_events": sub_events,
        "actors": [],
        "locations": [item for item in (region, location) if item],
        "topics": topics,
        "claims": [],
        "extraction_mode": "curated",
    }
    payload, _ = validate_extraction(data, bundle.event_id)
    payload["warnings"] = []
    return payload
