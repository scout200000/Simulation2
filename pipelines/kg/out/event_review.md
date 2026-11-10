# 66 个事件入库检查

- 检查范围：MongoDB `events` 集合 6 个事件 + 「data/legacy_corpus/event.xlsx」60 个历史语料事件。
- 判定口径：正文是否完整可抽取；是否有事件名/时间/地点或来源；是否为测试占位。
- 入库结果：**65 个事件 / 743 节点 / 1459 关系**（Neo4j Aura，另有本地快照同源）。

## 汇总

| 判定 | 数量 | 说明 |
| --- | ---: | --- |
| 已入图（历史复现） | 3 | 原有事件，本次未重建 |
| 已入图（策略运行） | 1 | 高阳事件，保留原节点 |
| 新增（历史语料） | 60 | 单阶段背景事件，无通报/趋势 |
| 新增（事件库） | 1 | 武汉万圣节网约车事件 |
| 拒绝（测试占位） | 1 | `event_test_draft_001` |
| **合计** | **66** | **入库 65** |

## 逐个检查

| # | event_id | 名称 | 来源 | 判定 | 议题 / 依据 |
| ---: | --- | --- | --- | --- | --- |
| 1 | `event_baoding_driving_school_crash_20261006_001` | 保定驾校车辆碰撞事件 | 历史复现事件库（data/historical_replay/events） | 已入图 | 5 文件齐全 + 7 阶段时间线 + 复现批次指标；本次跳过重建；议题：事故原因、事故过程、人员伤亡 |
| 2 | `event_beiguo_xiantianxia_crash_20260920_002` | 北国先天下广场车辆冲入商场事件 | 历史复现事件库（data/historical_replay/events） | 已入图 | 5 文件齐全 + 3 阶段时间线 + 复现批次指标；本次跳过重建；议题：事件性质、事发地点、事发时间 |
| 3 | `event_huxinyu_2022_001` | 胡某宇失联事件 | 历史复现事件库（data/historical_replay/events） | 已入图 | 5 文件齐全 + 8 阶段时间线 + 复现批次指标；本次跳过重建；议题：失联原因、失联者去向、家属行动 |
| 4 | `event_gaoyang_assault_001` | 河北省保定市高阳县一商场门口殴打他人事件 | MongoDB events（策略会话） | 已入图 | 策略运行事件，已有子图；本次保留原节点；议题：依法处置、公共场所安全、公共场所治安管理 |
| 5 | `event_wuhan_halloween_rideshare_20261101` | 武汉万圣节网约车被困事件 | MongoDB events（采集事件） | 新增 | 正文完整（含时间、地点、处置结果）；无官方通报时间线，单阶段 |
| 6 | `event_test_draft_001` | 测试事件正文。 | MongoDB events（测试草稿） | 拒绝 | 正文仅“测试事件正文。”，无实体信息，不入图 |
| 7 | `legacy_corpus_001` | 男子发12字评论被行拘 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：执法与权力监督；正文 487 字 |
| 8 | `legacy_corpus_002` | 燕冬萍离婚案 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：婚姻家庭与情感；正文 321 字 |
| 9 | `legacy_corpus_003` | 黄杨钿甜天价耳环事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：公职人员行为；正文 557 字 |
| 10 | `legacy_corpus_004` | 零负债人群引发热议 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：社会心态；正文 432 字 |
| 11 | `legacy_corpus_005` | 小吃店少拿500元可多休10天 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：劳动权益；正文 320 字 |
| 12 | `legacy_corpus_006` | 女子逆行剐蹭骑车小伙 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：交通事故与出行安全、执法与权力监督；正文 396 字 |
| 13 | `legacy_corpus_007` | 男子私凿奥特曼石窟将被拆除 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：城市治理；正文 401 字 |
| 14 | `legacy_corpus_008` | 武汉网红桥下进入需交押金 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：消费维权；正文 488 字 |
| 15 | `legacy_corpus_009` | 南通文旅账号评论事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：公职人员行为、网络空间治理；正文 659 字 |
| 16 | `legacy_corpus_010` | 小米SU7高速碰撞爆燃致3死 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：交通事故与出行安全；正文 448 字 |
| 17 | `legacy_corpus_011` | 河北三河市红蓝黑招牌禁令事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：城市治理、执法与权力监督；正文 449 字 |
| 18 | `legacy_corpus_012` | 小区高层住户想加装电梯 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：城市治理；正文 703 字 |
| 19 | `legacy_corpus_013` | 云南85后干部拟获提拔 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：公职人员行为；正文 495 字 |
| 20 | `legacy_corpus_014` | 68岁潘长江演短剧10天斩获2亿播放量 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：文娱与广告；正文 368 字 |
| 21 | `legacy_corpus_015` | 婚礼大屏出现不雅图片 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：婚姻家庭与情感、消费维权；正文 419 字 |
| 22 | `legacy_corpus_016` | 商家挂密码锁防穿完就退 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：消费维权；正文 545 字 |
| 23 | `legacy_corpus_017` | 女生被曝长期发表极端言论 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：公职人员行为、网络空间治理；正文 425 字 |
| 24 | `legacy_corpus_018` | 广东19岁纹面男孩已拿到新身份证 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：未成年人保护；正文 448 字 |
| 25 | `legacy_corpus_019` | 武陵山天池不锈钢池底 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：城市治理、消费维权；正文 407 字 |
| 26 | `legacy_corpus_020` | 贵州男子罗某为看黄色视频在百人群分享黄链获刑 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：网络空间治理；正文 406 字 |
| 27 | `legacy_corpus_021` | 员工休息3分钟被开除 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：劳动权益；正文 552 字 |
| 28 | `legacy_corpus_022` | 高校要求毕业生删摆摊视频 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：校园与教育、网络空间治理；正文 457 字 |
| 29 | `legacy_corpus_023` | 留英博士性侵多人被判终身监禁 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：涉外与历史、社会治安；正文 609 字 |
| 30 | `legacy_corpus_024` | 万达集团被恢复执行17亿 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：就业与企业经营；正文 469 字 |
| 31 | `legacy_corpus_025` | 国家统计局：青年人失业率连续三个月下降 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：就业与企业经营；正文 596 字 |
| 32 | `legacy_corpus_026` | 女孩打暑假工被血站抽血浆 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：医疗与公共卫生、未成年人保护；正文 312 字 |
| 33 | `legacy_corpus_027` | 罗帅宇湘雅二院坠亡 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：医疗与公共卫生、社会治安；正文 433 字 |
| 34 | `legacy_corpus_028` | 男子让儿子签名替父背债 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：婚姻家庭与情感；正文 455 字 |
| 35 | `legacy_corpus_029` | 新郎新娘结婚前一天先后坠楼，官方通报 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：婚姻家庭与情感、社会治安；正文 325 字 |
| 36 | `legacy_corpus_030` | 沈阳学校被曝集体退货 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：校园与教育、消费维权；正文 451 字 |
| 37 | `legacy_corpus_031` | 华中农大11名学生举报导师 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：学术诚信、校园与教育；正文 382 字 |
| 38 | `legacy_corpus_032` | 江西提灯定损事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：城市治理、消费维权；正文 413 字 |
| 39 | `legacy_corpus_033` | 胖猫事件（全） | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：婚姻家庭与情感、网络空间治理；正文 451 字 |
| 40 | `legacy_corpus_034` | 职业关店人帮商家跑路 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：就业与企业经营、消费维权；正文 480 字 |
| 41 | `legacy_corpus_035` | 叫花鸡里没有鸡 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：食品安全；正文 340 字 |
| 42 | `legacy_corpus_036` | 姜萍事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：校园与教育、网络空间治理；正文 418 字 |
| 43 | `legacy_corpus_037` | 打假博主海鲜市场遭围殴 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：消费维权、社会治安；正文 468 字 |
| 44 | `legacy_corpus_038` | 女企业家追讨工程款被刑拘 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：就业与企业经营、执法与权力监督；正文 721 字 |
| 45 | `legacy_corpus_039` | 河北邯郸初中生杀害同学并埋尸案 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：未成年人保护、校园与教育；正文 417 字 |
| 46 | `legacy_corpus_040` | 南京大学复试一考生因虐猫视频被拒绝录取 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：动物保护、校园与教育；正文 457 字 |
| 47 | `legacy_corpus_041` | 日本靖国神社涂鸦并小便事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：涉外与历史；正文 557 字 |
| 48 | `legacy_corpus_042` | 复旦大学法学院毕业典礼学生挥拳打老师事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：校园与教育、社会治安；正文 307 字 |
| 49 | `legacy_corpus_043` | 派出所所长实名举报公安局长 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：公职人员行为、执法与权力监督；正文 270 字 |
| 50 | `legacy_corpus_044` | 三名初中生砸车后车辆被烧毁 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：未成年人保护、社会治安；正文 266 字 |
| 51 | `legacy_corpus_045` | 淄博学校急救事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：医疗与公共卫生、校园与教育；正文 373 字 |
| 52 | `legacy_corpus_046` | 广州医学院教师上课迟到被罚事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：校园与教育；正文 330 字 |
| 53 | `legacy_corpus_047` | 开鲁阻拦农民春耕事件 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：基层治理；正文 373 字 |
| 54 | `legacy_corpus_048` | 上海女律师擦边直播 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：文娱与广告、网络空间治理；正文 401 字 |
| 55 | `legacy_corpus_049` | 民警菜市场宣传防盗 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：执法与权力监督、社会治安；正文 359 字 |
| 56 | `legacy_corpus_050` | 废弃校区信箱发现举报信 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：未成年人保护、校园与教育；正文 338 字 |
| 57 | `legacy_corpus_051` | 小孩被独留路中央遭碾压 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：交通事故与出行安全、未成年人保护；正文 248 字 |
| 58 | `legacy_corpus_052` | 新郎接亲途中恳求去钓鱼 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：婚姻家庭与情感；正文 218 字 |
| 59 | `legacy_corpus_053` | 济南大学超市泡面挤走食堂 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：校园与教育、消费维权；正文 312 字 |
| 60 | `legacy_corpus_054` | 椰树直播被罚款 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：文娱与广告、网络空间治理；正文 231 字 |
| 61 | `legacy_corpus_055` | 江苏师大男生挥拳打倒女生 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：校园与教育、社会治安；正文 323 字 |
| 62 | `legacy_corpus_056` | 叶县领导带人强拆创业果园 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：基层治理、执法与权力监督；正文 344 字 |
| 63 | `legacy_corpus_057` | 男子欲拔死去藏羚羊羊角被制止 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：动物保护；正文 337 字 |
| 64 | `legacy_corpus_058` | 315晚会淀粉肠 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：食品安全；正文 852 字 |
| 65 | `legacy_corpus_059` | 99年女干部破格提拔副镇长 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：公职人员行为；正文 342 字 |
| 66 | `legacy_corpus_060` | 网友质疑彩票店刮走有奖彩票 | data/legacy_corpus/event.xlsx | 新增 | 标题+正文完整，含 B 站/抖音视频 ID；无官方通报与真实趋势，按单阶段背景事件入库；议题：消费维权；正文 337 字 |

## 入库边界

- 60 个历史语料事件只有标题、二手叙述正文和平台视频 ID：可建 Event / SubEvent（单阶段）/ Topic / Location / Source，**不生成 Claim 与 Snapshot**。
- 语料事件统一 `origin=legacy_corpus`，事件库事件 `origin=event_store`，在页面详情里与「历史复现事件」「策略运行事件」区分。
- 未经证实的内容（质疑、传闻、举报）子事件标为 `discourse / unconfirmed`，不写成官方结论。
- 这 60 个事件不进入历史复现实验：没有阶段时间线、官方通报和真实趋势，无法作为复现输入。
