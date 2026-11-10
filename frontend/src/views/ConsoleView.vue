<template>
  <div class="console-app">
    <header class="topbar">
      <div class="topbar-left">
        <RouterLink class="back-link" to="/workspace">← 工作台</RouterLink>
        <RouterLink class="brand" to="/workspace">
          <span class="brand-mark">舆</span>
          <span class="brand-text">
            <strong>Simulation2</strong>
            <small>舆情推演控制台</small>
          </span>
        </RouterLink>
      </div>

      <div class="topbar-session">
        <span class="eyebrow">NETWORK-LED SIMULATION</span>
        <strong>{{ session?.experiment_id || "新建推演批次" }}</strong>
      </div>

      <div class="topbar-actions">
        <span class="live"><i :class="{ off: !liveOk }"></i>{{ liveText }}</span>
        <button class="btn btn-primary" type="button" @click="openComposer('event')">＋ 新建推演</button>
        <RouterLink class="report-link" to="/graph">知识图谱 ↗</RouterLink>
        <RouterLink class="report-link" :to="{ path: '/report', query: session ? { session: session.experiment_id } : {} }">报告 ↗</RouterLink>
      </div>
    </header>

    <main class="board">
      <section class="network-card">
        <header class="network-head">
          <div class="network-title">
            <span class="eyebrow">PRIMARY CANVAS</span>
            <h1>Agent 关系网络</h1>
            <p>{{ agents.length }} 个 Agent · {{ visibleNetworkEdges.length }} 条关系 · 滚轮缩放 / 双击复位</p>
          </div>
          <div class="network-tools">
            <div class="segmented" role="group" aria-label="连线范围">
              <button type="button" :class="{ active: networkEdgeFilter !== 'all' }" @click="networkEdgeFilter = 'strong'">精简</button>
              <button type="button" :class="{ active: networkEdgeFilter === 'all' }" @click="networkEdgeFilter = 'all'">全部</button>
            </div>
            <button class="btn btn-ghost" type="button" @click="toggleNetworkFullscreen">
              {{ networkFullscreen ? "退出全屏" : "全屏" }}
            </button>
          </div>
        </header>

        <div
          class="network-stage"
          :class="{ 'is-live': networkActive, 'has-focus': networkHoverId, 'is-fullscreen': networkFullscreen, dragging: networkDragging }"
          @wheel.prevent="onNetworkWheel"
          @dblclick="resetNetworkZoom"
          @pointerdown="onNetworkPointerDown"
          @pointermove="onNetworkPointerMove"
          @pointerup="onNetworkPointerUp"
          @pointercancel="onNetworkPointerUp"
        >
          <div class="network-canvas" :style="networkCanvasStyle">
            <svg class="network-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <path
                v-for="edge in visibleNetworkEdges"
                :key="`base-${edge.id}`"
                class="edge-base"
                :d="networkEdgePath(edge)"
                vector-effect="non-scaling-stroke"
                :style="networkEdgeStyle(edge)"
              />
              <path
                v-for="edge in visibleNetworkEdges"
                :key="`flow-${edge.id}`"
                class="edge-flow"
                :class="{ active: isNetworkEdgeActive(edge) }"
                :d="networkEdgePath(edge)"
                vector-effect="non-scaling-stroke"
                :style="networkEdgeStyle(edge)"
              />
            </svg>

            <button
              v-for="agent in agentNetworkNodes"
              :key="agent.agent_id"
              type="button"
              class="network-node"
              :class="{ commenting: agent.last_action === 'comment', dimmed: networkHoverId && networkHoverId !== agent.agent_id }"
              :style="networkNodeStyle(agent)"
              :title="agentNodeTitle(agent)"
              @mouseenter="setNetworkHover(agent.agent_id)"
              @mouseleave="setNetworkHover(null)"
              @focus="setNetworkHover(agent.agent_id)"
              @blur="setNetworkHover(null)"
              @click="openAgentDetail(agent)"
            >
              <span class="node-orb" :style="{ '--orb': emotionColor(agent.current_emotion) }">{{ agent.agent_id.slice(-3) }}</span>
            </button>
          </div>

          <div v-if="!agents.length" class="canvas-empty">等待 Agent 初始化</div>

          <div class="canvas-legend">
            <span><i style="background:#e0473a"></i>负面</span>
            <span><i style="background:#7f8c99"></i>中性</span>
            <span><i style="background:#10b981"></i>正面</span>
            <span class="legend-note">节点大小 = 影响力</span>
          </div>

          <span class="zoom-badge">{{ Math.round(networkScale * 100) }}%</span>

          <button v-if="networkFullscreen" class="btn btn-ghost exit-fullscreen" type="button" @click.stop="toggleNetworkFullscreen">
            退出全屏 · Esc
          </button>
        </div>
      </section>

      <aside class="rail">
        <section class="rail-card">
          <header class="rail-head">
            <div class="rail-tabs" role="tablist" aria-label="观测面板">
              <button
                type="button"
                role="tab"
                :aria-selected="railTab === 'metrics'"
                :class="{ active: railTab === 'metrics' }"
                @click="railTab = 'metrics'"
              >指标</button>
              <button
                type="button"
                role="tab"
                :aria-selected="railTab === 'pool'"
                :class="{ active: railTab === 'pool' }"
                @click="railTab = 'pool'"
              >舆论池</button>
            </div>
            <span class="rail-meta">{{ railTab === "metrics" ? `${metricsRows.length} 轮` : `${comments.length} 条` }}</span>
          </header>

          <div v-if="railTab === 'metrics'" class="rail-body">
            <template v-if="session">
              <div class="kpi-grid">
                <div v-for="card in metricCards" :key="card[0]" class="kpi">
                  <strong>{{ card[1] === null || card[1] === undefined ? '—' : (typeof card[1] === 'number' ? percent(card[1]) : card[1]) }}</strong>
                  <span>{{ card[0] }}</span>
                </div>
              </div>

              <div class="spark-group">
                <div class="spark" @mousemove="handleChartMove" @mouseleave="chartTooltip = null">
                  <div v-html="metricsSvg"></div>
                  <span v-if="chartTooltip" class="spark-tip" :style="{ left: chartTooltip.left + 'px', top: chartTooltip.top + 'px' }">{{ chartTooltip.text }}</span>
                  <p v-if="!metricsRows.length" class="spark-empty">暂无轮次数据</p>
                </div>

                <div class="spark-legend">
                  <span><i style="background:#c05952"></i>负面率</span>
                  <span><i style="background:#b98a4b"></i>质疑率</span>
                  <span><i style="background:#3f8f6a"></i>接受率</span>
                </div>
              </div>

              <div class="rail-list">
                <div><span>官方进场</span><b>{{ session.response_step ? `第 ${session.response_step} 轮` : "未进场" }}</b></div>
                <div><span>已完成</span><b>{{ session.completed_step_count || 0 }} / {{ session.max_steps || 10 }} 轮</b></div>
                <div><span>追加公告</span><b>{{ timeline.length }} 条</b></div>
                <div><span>当前策略</span><b>{{ strategyName(session.selected_strategy_id) }}</b></div>
              </div>

              <div v-if="showTokenStats" class="token-usage">
                <div class="token-head">
                  <span>Token 用量</span>
                  <b>{{ tokenUsage.total_tokens ? formatTokenCount(tokenUsage.total_tokens) : "—" }}</b>
                </div>
                <p v-if="tokenUsage.total_tokens">
                  输入 {{ formatTokenCount(tokenUsage.prompt_tokens) }} · 输出 {{ formatTokenCount(tokenUsage.completion_tokens) }} · {{ tokenUsage.request_count }} 次调用
                </p>
                <p v-else>本会话暂无 Token 记录</p>
              </div>
            </template>

            <div v-else class="rail-empty">
              <strong>还没有运行数据</strong>
              <p>创建推演批次后，这里会持续显示负面率、质疑率与接受率的趋势；点击右上角「＋ 新建推演」开始。</p>
            </div>
          </div>

          <div v-else class="rail-body pool-body" @click="openPool">
            <div v-if="poolRoundOptions.length > 1" class="pool-pager" @click.stop>
              <button
                type="button"
                class="pool-pager-btn"
                aria-label="上一轮"
                :disabled="!poolRoundHasPrev"
                @click="stepPoolRound(-1)"
              >‹</button>
              <span class="pool-pager-label">{{ poolRoundLabel }}</span>
              <button
                type="button"
                class="pool-pager-btn"
                aria-label="下一轮"
                :disabled="!poolRoundHasNext"
                @click="stepPoolRound(1)"
              >›</button>
            </div>

            <template v-if="comments.length">
              <div class="pool-summary">
                <div class="pool-donut" v-html="poolEmotionChartSvg"></div>
                <div class="pool-legend">
                  <div v-for="item in poolEmotionStats" :key="item.key">
                    <i :style="{ background: item.color }"></i>
                    <span>{{ item.label }}</span>
                    <b>{{ item.count }}</b>
                    <small>{{ percent(item.rate) }}</small>
                  </div>
                </div>
              </div>

              <div class="pool-bars">
                <div v-for="item in poolFactionStats.slice(0, 4)" :key="item.key">
                  <span>{{ item.label }}</span>
                  <i><b :style="{ width: percent(item.rate) }"></b></i>
                  <strong>{{ item.count }}</strong>
                </div>
                <p v-if="!poolFactionStats.length">暂无派系数据</p>
              </div>

              <div class="recent">
                <span class="recent-head">最新评论</span>
                <button
                  v-for="(comment, index) in comments.slice(0, 3)"
                  :key="comment.comment_id || index"
                  type="button"
                  @click.stop="openPoolDetail(comment)"
                >
                  <p>{{ comment.text }}</p>
                  <small>{{ emotionText(comment.emotion) }} · {{ comment.faction || "未分类" }}</small>
                </button>
              </div>

              <span class="pool-link">查看全部评论 →</span>
            </template>

            <div v-else class="rail-empty">
              <strong>还没有评论</strong>
              <p>推演开始后，这里会汇总舆论池中的情绪结构与派系分布；点击右上角「＋ 新建推演」开始。</p>
            </div>
          </div>
        </section>
      </aside>
    </main>

    <footer class="runbar">
      <div class="run-progress">
        <div class="progress-line">
          <i
            v-for="n in (session?.max_steps || 10)"
            :key="n"
            :class="{ done: n <= (session?.completed_step_count || 0), entry: session?.response_step === n }"
          ></i>
        </div>
        <span>{{ busy ? busyText : phaseLine }}</span>
      </div>

      <div class="run-actions">
        <button v-if="session?.mode === 'single'" class="btn btn-primary" :disabled="!canStart()" @click="startRun">启动</button>
        <button v-if="session?.mode === 'all'" class="btn btn-primary" :disabled="busy || !['created','ready'].includes(session?.phase)" @click="runAll">运行全部策略</button>
        <button v-if="session?.mode === 'drafts'" class="btn btn-primary" :disabled="busy || !['created','ready'].includes(session?.phase)" @click="runAll">运行全部草稿</button>
        <button class="btn btn-ghost" :disabled="!canContinue()" @click="continueRun">继续</button>
        <button class="btn btn-ghost" :disabled="!canPause()" @click="pauseRun">暂停</button>
        <button class="btn btn-ghost" :disabled="!canRollback()" @click="rollbackRun">回滚</button>
        <button class="btn btn-ghost btn-danger" :disabled="busy || !session" @click="restartRun">重启</button>
      </div>

      <span class="run-meta">{{ currentStrategyText }}</span>
    </footer>

    <div v-if="composerOpen" class="modal-backdrop" @click.self="closeComposer">
      <section class="dialog" role="dialog" aria-modal="true" aria-label="新建推演批次">
        <header class="dialog-head">
          <div>
            <span class="eyebrow">NEW SIMULATION</span>
            <h2>新建推演批次</h2>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭" @click="closeComposer">×</button>
        </header>

        <nav class="dialog-tabs" aria-label="输入步骤">
          <button type="button" :class="{ active: composerTab === 'event' }" @click="composerTab = 'event'">01 事件输入</button>
          <button type="button" :class="{ active: composerTab === 'announcement' }" @click="composerTab = 'announcement'">02 官方公告</button>
          <button type="button" :class="{ active: composerTab === 'timeline' }" @click="composerTab = 'timeline'">03 进场与时间线</button>
        </nav>

        <div class="dialog-body">
          <section v-show="composerTab === 'event'" class="pane">
            <label class="field field-grow">事件正文
              <textarea v-model="eventContent" maxlength="5000" placeholder="输入需要推演的事件正文"></textarea>
            </label>
            <div class="field-row">
              <label class="field">主题
                <select v-model="eventTopic">
                  <option>社会事件</option>
                  <option>新闻时事</option>
                  <option>娱乐</option>
                  <option>其他</option>
                </select>
              </label>
              <label class="field">情绪
                <select v-model="eventValence">
                  <option value="negative">负面</option>
                  <option value="neutral">中性</option>
                  <option value="positive">正面</option>
                </select>
              </label>
            </div>
          </section>

          <section v-show="composerTab === 'announcement'" class="pane pane-split">
            <div class="editor">
              <div class="field-row">
                <label class="field">回应策略
                  <select v-model="selectedStrategyId">
                    <option v-for="row in strategyOverview" :key="row.strategy_id" :value="row.strategy_id">{{ row.strategy_name }}</option>
                  </select>
                </label>
                <label v-if="activeAnnouncementDraft" class="field">公告状态
                  <select v-model="activeAnnouncementDraft.status" @change="markActiveDraftExplicit">
                    <option value="clear">clear · 信息完整</option>
                    <option value="incomplete">incomplete · 信息不全</option>
                    <option value="conflict">conflict · 表述冲突</option>
                    <option value="none">none · 不发布</option>
                  </select>
                </label>
              </div>
              <label class="field field-grow">公告内容
                <textarea
                  v-if="activeAnnouncementDraft"
                  ref="announcementTextarea"
                  v-model="activeAnnouncementDraft.text"
                  maxlength="5000"
                  @input="markActiveDraftExplicit"
                  placeholder="写下本次官方公告，或切换到内置策略直接使用预置公告"
                ></textarea>
              </label>
            </div>

            <aside class="drafts">
              <div class="drafts-head">
                <span>公告草稿 · {{ announcementDrafts.length }}</span>
                <div>
                  <button type="button" title="新增公告草稿" @click="addAnnouncementDraft()">＋</button>
                  <button type="button" title="删除当前草稿" :disabled="!activeAnnouncementDraft" @click="removeActiveAnnouncementDraft">−</button>
                </div>
              </div>
              <button
                v-for="(item, index) in announcementDrafts"
                :key="item.id"
                type="button"
                class="draft"
                :class="{ active: item.id === activeAnnouncementId }"
                @click="selectAnnouncementDraft(item.id)"
              >
                <b>{{ index + 1 }}</b>
                <span class="draft-copy">
                  <span>{{ item.text.trim() || '未填写公告' }}</span>
                  <small>{{ strategyName(item.strategyId) }} · {{ item.explicit ? draftStatusText(item.status) : "未加入批次" }}</small>
                </span>
              </button>
              <p v-if="draftsRunMode" class="drafts-run-hint">
                创建后将依次运行以上 {{ validDrafts.length }} 条草稿
              </p>
            </aside>
          </section>

          <section v-show="composerTab === 'timeline'" class="pane">
            <div class="field-row">
              <label class="field">进场模式
                <select v-model="entryMode">
                  <option value="dynamic">动态进场</option>
                  <option value="fixed_round">固定轮次</option>
                </select>
              </label>
              <label class="field">进场轮次
                <select v-model.number="entryRound" :disabled="entryMode !== 'fixed_round'">
                  <option v-for="n in 9" :key="n" :value="n + 1">第 {{ n + 1 }} 轮</option>
                </select>
              </label>
            </div>

            <label class="field field-grow">暂停后追加公告
              <textarea
                ref="timelineTextarea"
                v-model="timelineText"
                maxlength="5000"
                placeholder="暂停推演后可在此追加公告"
                @input="resizeTimelineTextarea"
              ></textarea>
            </label>

            <div class="timeline-add">
              <select v-model.number="timelineRound">
                <option v-for="n in 9" :key="n" :value="n + 1">第 {{ n + 1 }} 轮</option>
              </select>
              <button class="btn btn-ghost" type="button" :disabled="!canAddAnnouncement()" @click="addAnnouncement">加入时间线</button>
            </div>
          </section>
        </div>

        <footer class="dialog-foot">
          <span class="dialog-hint">{{ createHint }}</span>
          <div class="dialog-actions">
            <button class="btn btn-ghost" type="button" :disabled="busy" @click="previewInputs">预览输入</button>
            <button class="btn btn-primary" type="button" :disabled="!canCreateSession" @click="submitSession">{{ createButtonText }}</button>
          </div>
        </footer>
      </section>
    </div>

    <div v-if="poolOpen" class="modal-backdrop drawer-backdrop" @click.self="poolOpen = false">
      <aside class="drawer">
        <header class="drawer-head">
          <div><span class="eyebrow">COMMENT INSPECTOR</span><h2>舆论池详情</h2></div>
          <button class="icon-btn" type="button" aria-label="关闭" @click="poolOpen = false">×</button>
        </header>
        <div v-if="poolDetail" class="comment-detail">
          <button type="button" @click="poolDetail = null">← 返回评论</button>
          <p>{{ poolDetail.text }}</p>
          <div class="chips">
            <span>{{ poolDetail.faction || '—' }}</span>
            <span>{{ orientationText(poolDetail.orientation) }}</span>
            <span>{{ stanceText(poolDetail.stance) }}</span>
          </div>
        </div>
        <div v-else class="comment-list">
          <button v-for="(comment, index) in comments" :key="comment.comment_id || index" type="button" @click="openPoolDetail(comment)">
            <span>{{ emotionText(comment.emotion) }}</span>
            <p>{{ comment.text }}</p>
            <small>{{ comment.faction || '未分类' }}</small>
          </button>
        </div>
      </aside>
    </div>

    <div v-if="agentOpen" class="modal-backdrop drawer-backdrop" @click.self="agentOpen = false">
      <aside class="drawer">
        <header class="drawer-head">
          <div><span class="eyebrow">AGENT INSPECTOR</span><h2>Agent 详情</h2></div>
          <button class="icon-btn" type="button" aria-label="关闭" @click="agentOpen = false">×</button>
        </header>
        <div v-if="agentDetail" class="agent-panel">
          <span class="agent-orb" :style="{ '--orb': emotionColor(agentDetail.current_emotion) }">{{ agentDetail.agent_id.slice(-4) }}</span>
          <strong>{{ agentDetail.agent_id }}</strong>
          <small>{{ emotionText(agentDetail.current_emotion) }} · {{ actionText(agentDetail.last_action) }}</small>
          <div class="chips">
            <span>{{ agentDetail.last_comment_faction || '未分类' }}</span>
            <span>{{ ['comment', 'original', 'reshare', 'repost', 'quote', 'reply'].includes(agentDetail.last_action) ? '本轮已发言' : '本轮未发言' }}</span>
            <span v-if="agentDetail.influence_weight !== null && agentDetail.influence_weight !== undefined">影响力 {{ Number(agentDetail.influence_weight).toFixed(2) }}</span>
            <span>累计评论 {{ (agentDetail.comments || []).length }} 条</span>
          </div>

          <div class="agent-comments">
            <header class="agent-comments-head">
              <span>本次事件评论</span>
              <b>{{ (agentDetail.comments || []).length }} 条</b>
            </header>
            <ol v-if="agentDetail.comments?.length">
              <li
                v-for="(comment, index) in agentDetail.comments"
                :key="comment.comment_id || `${comment.step}-${index}`"
              >
                <header>
                  <span class="comment-round">第 {{ comment.step }} 轮</span>
                  <span class="comment-emotion" :class="'emotion-' + comment.emotion">
                    {{ emotionText(comment.emotion) }}
                  </span>
                  <small>{{ comment.faction || '未分类' }}</small>
                  <em v-if="comment.action && comment.action !== 'comment'">
                    {{ actionText(comment.action) }}
                  </em>
                </header>
                <p>{{ comment.text }}</p>
              </li>
            </ol>
            <p v-else class="agent-comments-empty">
              {{ agentDetail.last_comment || '本次事件尚未发表评论' }}
            </p>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script>
import consoleOptions from "../core/console.js";

export default {
  ...consoleOptions,
  name: "ConsoleView"
};
</script>

<style src="../styles/console.css"></style>
