<script setup>
import { computed, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { getAuthSession, signOut } from "../core/auth.js";
import {
  DEFAULT_AGENTS,
  DEFAULT_MODEL,
  clearSettings,
  getSettings,
  normalizeOpinionPool,
  saveSettings
} from "../core/settings.js";

const router = useRouter();
const account = computed(() => getAuthSession()?.account || "用户");
const current = getSettings();

const apiKey = ref(current.apiKey);
const model = ref(current.model || DEFAULT_MODEL);
const agents = ref({ ...current.agents });
const ui = ref({ ...current.ui });
const opinionPool = ref(normalizeOpinionPool(current.opinionPool));
const showKey = ref(false);
const saved = ref(false);
const changed = ref(false);

const models = [
  {
    value: "deepseek-v4-flash",
    label: "DeepSeek V4 Flash",
    description: "低延迟文本生成，适合高频评论与 Agent 决策。"
  },
  {
    value: "deepseek-chat",
    label: "DeepSeek Chat",
    description: "通用对话与内容生成模型。"
  },
  {
    value: "deepseek-reasoner",
    label: "DeepSeek Reasoner",
    description: "更强的推理能力，适合复杂策略与判断任务。"
  }
];

const densities = [
  {
    value: "low",
    label: "稀疏",
    description: "只保留最强的约 18% 关注关系，网络更清爽。"
  },
  {
    value: "medium",
    label: "标准",
    description: "默认保留约 30% 的关注关系。"
  },
  {
    value: "high",
    label: "密集",
    description: "保留约 55% 的关注关系，更容易看出传播链路。"
  }
];

const activeModel = computed(
  () => models.find((item) => item.value === model.value) || models[0]
);

const poolSources = [
  {
    value: "generate",
    label: "生成式",
    description: "大模型按事件角度与人物类型合成评论，可控、可配比，但不代表真实舆论。"
  },
  {
    value: "harvest",
    label: "采集式",
    description: "从 B 站公开评论区抓取真实评论，并在采集时一次性完成议题与情绪标注。"
  }
];

const activePoolSource = computed(
  () => poolSources.find((item) => item.value === opinionPool.value.source) || poolSources[0]
);

function setPoolSource(value) {
  opinionPool.value.source = value;
  markChanged();
}

const activeDensity = computed(
  () => densities.find((item) => item.value === agents.value.density) || densities[1]
);

function markChanged() {
  changed.value = true;
  saved.value = false;
}

function setDensity(value) {
  agents.value.density = value;
  markChanged();
}

function setZoom(event) {
  agents.value.zoom = Number(event.target.value) / 100;
  markChanged();
}

function resetAgents() {
  agents.value = { ...DEFAULT_AGENTS };
  markChanged();
}

function save() {
  saveSettings({
    apiKey: apiKey.value,
    model: model.value,
    agents: agents.value,
    ui: ui.value,
    opinionPool: opinionPool.value
  });
  changed.value = false;
  saved.value = true;
}

function resetKey() {
  apiKey.value = "";
  clearSettings();
  saveSettings({
    apiKey: "",
    model: model.value,
    agents: agents.value,
    ui: ui.value,
    opinionPool: opinionPool.value
  });
  changed.value = false;
  saved.value = true;
}

function logout() {
  signOut();
  router.replace({ name: "portal" });
}
</script>

<template>
  <main class="settings-page">
    <header class="settings-header">
      <RouterLink class="settings-back" to="/workspace">
        <span aria-hidden="true">←</span>
        返回工作台
      </RouterLink>

      <div class="settings-account">
        <span>PERSONAL SETTINGS</span>
        <strong>{{ account }}</strong>
        <button type="button" @click="logout">退出</button>
      </div>
    </header>

    <section class="settings-intro">
      <p>MODEL ACCESS &amp; AGENTS</p>
      <h1>个人设置</h1>
      <span>配置当前会话使用的模型访问信息，以及控制台中 Agent 网络的默认呈现方式。</span>
    </section>

    <form class="settings-form" @submit.prevent="save">
      <section class="settings-panel">
        <div class="settings-panel-head">
          <div>
            <h2>模型服务</h2>
            <p>设置只会保存在当前浏览器会话中。</p>
          </div>
          <span class="settings-session-badge"><i></i>当前会话</span>
        </div>

        <div class="settings-fields">
          <label class="settings-field">
            <span>API 密钥</span>
            <div class="settings-key-control">
              <input
                v-model="apiKey"
                :type="showKey ? 'text' : 'password'"
                name="api-key"
                autocomplete="off"
                spellcheck="false"
                placeholder="sk-..."
                @input="markChanged"
              >
              <button
                type="button"
                :aria-label="showKey ? '隐藏密钥' : '显示密钥'"
                @click="showKey = !showKey"
              >
                {{ showKey ? "隐藏" : "显示" }}
              </button>
            </div>
          </label>

          <label class="settings-field">
            <span>模型</span>
            <select v-model="model" name="model" @change="markChanged">
              <option v-for="item in models" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
            <small>{{ activeModel.description }}</small>
          </label>
        </div>
      </section>

      <section class="settings-panel">
        <div class="settings-panel-head">
          <div>
            <h2>Agents</h2>
            <p>调整关系网络的规模、连线密度与节点标注，保存后对新打开的控制台生效。</p>
          </div>
          <button class="settings-reset-inline" type="button" @click="resetAgents">
            恢复默认
          </button>
        </div>

        <div class="settings-fields settings-agents">
          <label class="settings-field">
            <span class="settings-field-head">
              Agent 数量
              <b>{{ agents.count }} 个</b>
            </span>
            <input
              v-model.number="agents.count"
              type="range"
              min="10"
              max="60"
              step="5"
              aria-label="预览 Agent 数量"
              @input="markChanged"
            >
            <small>用于未绑定会话时的预览网络；已创建会话以服务端返回的名册为准。</small>
          </label>

          <div class="settings-field">
            <span class="settings-field-head">关系连线密度</span>
            <div class="settings-segmented" role="group" aria-label="关系连线密度">
              <button
                v-for="option in densities"
                :key="option.value"
                type="button"
                :class="{ active: agents.density === option.value }"
                :aria-pressed="agents.density === option.value"
                @click="setDensity(option.value)"
              >
                {{ option.label }}
              </button>
            </div>
            <small>{{ activeDensity.description }}</small>
          </div>

          <label class="settings-field">
            <span class="settings-field-head">
              网络初始缩放
              <b>{{ Math.round(agents.zoom * 100) }}%</b>
            </span>
            <input
              :value="Math.round(agents.zoom * 100)"
              type="range"
              min="80"
              max="130"
              step="5"
              aria-label="网络初始缩放"
              @input="setZoom"
            >
            <small>打开控制台时的默认缩放；进入后仍可用滚轮缩放、双击复位。</small>
          </label>

          <label class="settings-field settings-switch">
            <span class="settings-field-head">
              节点编号标签
              <input
                v-model="agents.showLabels"
                type="checkbox"
                role="switch"
                aria-label="显示节点编号标签"
                @change="markChanged"
              >
            </span>
            <small>在节点上显示 Agent 编号；关闭后仅保留颜色圆点，悬停仍可查看详情。</small>
          </label>
        </div>
      </section>

      <section class="settings-panel">
        <div class="settings-panel-head">
          <div>
            <h2>初始舆论池</h2>
            <p>第一轮评论从哪里来。创建会话时生效，并写入该批次的 control 记录。</p>
          </div>
          <span class="settings-session-badge"><i></i>{{ activePoolSource.label }}</span>
        </div>

        <div class="settings-fields settings-agents">
          <div class="settings-field">
            <span class="settings-field-head">来源</span>
            <div class="settings-segmented" role="group" aria-label="初始舆论池来源">
              <button
                v-for="option in poolSources"
                :key="option.value"
                type="button"
                :class="{ active: opinionPool.source === option.value }"
                :aria-pressed="opinionPool.source === option.value"
                @click="setPoolSource(option.value)"
              >
                {{ option.label }}
              </button>
            </div>
            <small>{{ activePoolSource.description }}</small>
          </div>

          <label v-if="opinionPool.source === 'generate'" class="settings-field">
            <span class="settings-field-head">
              评论条数
              <b>{{ opinionPool.generateCount }} 条</b>
            </span>
            <input
              v-model.number="opinionPool.generateCount"
              type="range"
              min="30"
              max="120"
              step="10"
              aria-label="生成评论条数"
              @input="markChanged"
            >
            <small>合成六十条约一次 50~65 秒、0.045 元；条数受五派系各至少 5 条的下限约束。</small>
          </label>

          <template v-else>
            <label class="settings-field">
              <span class="settings-field-head">
                采集条数
                <b>{{ opinionPool.harvestCount }} 条</b>
              </span>
              <input
                v-model.number="opinionPool.harvestCount"
                type="range"
                min="20"
                max="120"
                step="10"
                aria-label="采集评论条数"
                @input="markChanged"
              >
              <small>条数直接决定标注成本：40 条约 0.005 元，100 条约 0.012 元。</small>
            </label>

            <label class="settings-field">
              <span class="settings-field-head">
                帖子数
                <b>{{ opinionPool.harvestVideos }} 个</b>
              </span>
              <input
                v-model.number="opinionPool.harvestVideos"
                type="range"
                min="1"
                max="5"
                step="1"
                aria-label="采集帖子数"
                @input="markChanged"
              >
              <small>抓取按 1.5 倍冗余并提前停止；帖子越多样本越分散、耗时越长。目前仅支持 B 站公开评论区。</small>
            </label>
          </template>
        </div>
      </section>

      <section class="settings-panel">
        <div class="settings-panel-head">
          <div>
            <h2>显示与统计</h2>
            <p>控制控制台中的运行统计展示，保存后对新打开的控制台生效。</p>
          </div>
        </div>

        <div class="settings-fields">
          <label class="settings-field settings-switch">
            <span class="settings-field-head">
              Token 统计
              <input
                v-model="ui.showTokenStats"
                type="checkbox"
                role="switch"
                aria-label="显示 Token 统计"
                @change="markChanged"
              >
            </span>
            <small>在控制台右栏显示当前会话累计 Token 用量、输入/输出拆分与调用次数；关闭后仅隐藏展示，统计仍会记录在实验产物中。</small>
          </label>
        </div>
      </section>

      <div class="settings-savebar">
        <div class="settings-feedback" aria-live="polite">
          <span v-if="saved" class="settings-success">设置已保存到当前会话</span>
          <span v-else-if="changed" class="settings-pending">有未保存的更改</span>
          <span v-else>
            当前模型：{{ activeModel.label }} · {{ agents.count }} 个 Agent · {{ activeDensity.label }}连线
          </span>
        </div>
        <div class="settings-actions">
          <button class="settings-clear" type="button" :disabled="!apiKey" @click="resetKey">
            清除密钥
          </button>
          <button class="settings-save" type="submit">保存设置</button>
        </div>
      </div>
    </form>

    <footer class="settings-footer">
      <span>Simulation2 · 舆情推演控制台</span>
      <span>本地会话配置</span>
    </footer>
  </main>
</template>

<style src="../styles/settings.css"></style>
