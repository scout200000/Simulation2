<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { signIn } from "../core/auth.js";

const router = useRouter();

const account = ref("");
const password = ref("");
const remember = ref(false);
const showPassword = ref(false);
const submitting = ref(false);
const error = ref("");
let submitTimer = null;
const previousTitle = document.title;

const canSubmit = computed(
  () => Boolean(account.value.trim() && password.value) && !submitting.value
);

async function submit() {
  error.value = "";

  if (!account.value.trim()) {
    error.value = "请输入账号";
    return;
  }
  if (!password.value) {
    error.value = "请输入密码";
    return;
  }
  if (account.value !== "user" || password.value !== "passward") {
    error.value = "账号或密码错误";
    return;
  }

  submitting.value = true;
  window.clearTimeout(submitTimer);
  await new Promise((resolve) => {
    submitTimer = window.setTimeout(resolve, 650);
  });

  try {
    signIn(account.value, remember.value);
    await router.replace({ name: "workspace" });
  } catch (submitError) {
    error.value = submitError.message || "登录失败，请稍后重试";
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  document.title = "登录 · 舆情推演控制台";
});

onBeforeUnmount(() => {
  window.clearTimeout(submitTimer);
  document.title = previousTitle;
});
</script>

<template>
  <main class="login-page">
    <section class="login-brief" aria-label="平台概览">
      <RouterLink class="brief-brand" to="/">
        <span class="brief-mark">舆</span>
        <span class="brief-brand-text">
          <strong>Simulation2</strong>
          <small>舆情推演控制台</small>
        </span>
      </RouterLink>

      <div class="brief-copy">
        <span class="eyebrow">SCENARIO OPERATIONS</span>
        <h1>把复杂的舆情演化，变成可观察、可控制的推演过程。</h1>
        <p>
          登录后进入本地推演工作区：录入事件与官方公告，驱动 30 个 Agent 逐轮决策，
          并在同一块屏幕上观察网络、指标与舆论池的变化。
        </p>

        <ul class="brief-points">
          <li><b>01</b><span>实验输入、策略状态与结果相互隔离，可回滚、可复现。</span></li>
          <li><b>02</b><span>官方态度与评论情绪分开计量，避免把个体和环境混为一谈。</span></li>
          <li><b>03</b><span>传播谱系完整保留，可重新计算覆盖、深度与继续传播比例。</span></li>
        </ul>
      </div>

      <footer class="brief-foot">
        <span class="status-dot"></span>
        <span>本地服务可用</span>
        <span class="brief-version">Simulation2 · Local</span>
      </footer>
    </section>

    <section class="login-panel">
      <RouterLink class="login-home" to="/">← 返回首页</RouterLink>

      <form class="login-form" @submit.prevent="submit">
        <header class="form-header">
          <span class="eyebrow">IDENTITY VERIFICATION</span>
          <h2>登录控制台</h2>
          <p>请输入账号信息以进入推演工作区。</p>
        </header>

        <label class="field">
          <span>账号</span>
          <input
            v-model.trim="account"
            name="account"
            type="text"
            autocomplete="username"
            autofocus
            placeholder="请输入账号"
          >
        </label>

        <label class="field">
          <span>密码</span>
          <span class="password-control">
            <input
              v-model="password"
              name="password"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              placeholder="请输入密码"
            >
            <button
              type="button"
              class="password-toggle"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              {{ showPassword ? "隐藏" : "显示" }}
            </button>
          </span>
        </label>

        <div class="form-options">
          <label class="remember">
            <input v-model="remember" type="checkbox">
            <span>保持登录</span>
          </label>
          <span class="demo-hint">演示账号：user / passward</span>
        </div>

        <p v-if="error" class="form-error" role="alert">{{ error }}</p>

        <button class="login-submit" type="submit" :disabled="!canSubmit">
          {{ submitting ? "正在进入…" : "进入控制台" }}
        </button>

        <footer class="form-foot">
          <span>Simulation2</span>
          <span>本地推演环境</span>
        </footer>
      </form>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  --login-ink: #15211d;
  --login-muted: #6a7a73;
  --login-line: #e8ede9;
  --login-faint: #93a19b;
  --login-green: #177f6f;
  --login-green-deep: #0f5f53;
  --login-soft: #eaf5f1;
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(0, .92fr);
  color: var(--login-ink);
  background:
    radial-gradient(1000px 620px at 92% -14%, rgba(23, 127, 111, .12), transparent 62%),
    radial-gradient(700px 480px at -10% 108%, rgba(23, 127, 111, .07), transparent 58%),
    #fff;
  font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
}

.login-page * { box-sizing: border-box; }
.login-page a { color: inherit; }

.eyebrow {
  display: block;
  color: var(--login-green);
  font-size: 9.5px;
  font-weight: 800;
  letter-spacing: .16em;
}

/* ── 左侧说明 ───────────────────────────────────────────── */
.login-brief {
  display: flex;
  flex-direction: column;
  gap: 32px;
  padding: clamp(28px, 5vw, 64px);
  border-right: 1px solid var(--login-line);
}

.brief-brand { display: inline-flex; align-items: center; gap: 11px; text-decoration: none; }

.brief-mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: #fff;
  background: linear-gradient(140deg, #1c937f, #0f6659);
  font-size: 14px;
  font-weight: 900;
  box-shadow: 0 7px 18px rgba(23, 127, 111, .22);
}

.brief-brand-text strong,
.brief-brand-text small { display: block; line-height: 1.25; }
.brief-brand-text strong { font-size: 13.5px; }
.brief-brand-text small { color: var(--login-muted); font-size: 9px; }

.brief-copy { margin-top: auto; max-width: 560px; }

.brief-copy h1 {
  margin: 14px 0 0;
  font-size: clamp(32px, 3.8vw, 48px);
  font-weight: 800;
  line-height: 1.16;
  letter-spacing: -.025em;
}

.brief-copy > p {
  margin: 18px 0 0;
  color: var(--login-muted);
  font-size: 13px;
  line-height: 1.85;
}

.brief-points {
  margin: 30px 0 0;
  padding: 0;
  display: grid;
  gap: 12px;
  list-style: none;
}

.brief-points li {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 12px 14px;
  border: 1px solid var(--login-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, .7);
}

.brief-points b {
  color: var(--login-green);
  font-size: 9.5px;
  font-weight: 800;
  letter-spacing: .08em;
}

.brief-points span {
  color: var(--login-muted);
  font-size: 11.5px;
  line-height: 1.7;
}

.brief-foot {
  margin-top: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--login-muted);
  font-size: 10px;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #2f9d78;
  box-shadow: 0 0 0 4px rgba(47, 157, 120, .14);
}

.brief-version { margin-left: auto; }

/* ── 右侧表单 ───────────────────────────────────────────── */
.login-panel {
  position: relative;
  display: grid;
  align-content: center;
  justify-items: center;
  padding: clamp(28px, 4vw, 56px);
}

.login-home {
  position: absolute;
  top: 26px;
  left: 32px;
  color: var(--login-muted);
  font-size: 10.5px;
  font-weight: 700;
  text-decoration: none;
}

.login-home:hover { color: var(--login-green-deep); }

.login-form {
  width: min(392px, 100%);
  display: grid;
  gap: 16px;
  padding: 30px 28px;
  border: 1px solid var(--login-line);
  border-radius: 18px;
  background: rgba(255, 255, 255, .9);
  box-shadow: 0 24px 60px rgba(21, 33, 29, .08);
  backdrop-filter: blur(10px);
}

.form-header { display: grid; gap: 6px; margin-bottom: 4px; }
.form-header h2 { margin: 0; font-size: 26px; font-weight: 800; letter-spacing: -.02em; }
.form-header p { margin: 0; color: var(--login-muted); font-size: 11px; }

.field {
  display: grid;
  gap: 7px;
  color: var(--login-muted);
  font-size: 10.5px;
  font-weight: 600;
}

.field input {
  width: 100%;
  height: 46px;
  padding: 0 14px;
  border: 1px solid #dfe7e2;
  border-radius: 10px;
  outline: none;
  color: var(--login-ink);
  background: #fbfdfc;
  font-size: 12.5px;
  transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
}

.field input:focus {
  border-color: var(--login-green);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(23, 127, 111, .10);
}

.field input::placeholder { color: #a7b3ae; }

.password-control { position: relative; display: block; }
.password-control input { padding-right: 68px; }

.password-toggle {
  position: absolute;
  top: 50%;
  right: 6px;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 52px;
  height: 34px;
  padding: 0 10px;
  border: 0;
  border-radius: 8px;
  color: var(--login-green);
  background: transparent;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
}

.password-toggle:hover { background: var(--login-soft); }

.form-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--login-muted);
  font-size: 10.5px;
}

.remember { display: inline-flex; align-items: center; gap: 7px; cursor: pointer; }

.remember input {
  width: 15px;
  height: 15px;
  accent-color: var(--login-green);
}

.demo-hint { color: var(--login-faint); }

.form-error {
  margin: 0;
  padding: 9px 11px;
  border-radius: 8px;
  color: #a7473c;
  background: #fdf1ef;
  font-size: 10.5px;
}

.login-submit {
  height: 44px;
  border: 0;
  border-radius: 10px;
  color: #fff;
  background: var(--login-green);
  font-size: 12.5px;
  font-weight: 800;
  letter-spacing: .01em;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(23, 127, 111, .20);
  transition: background .16s ease, box-shadow .16s ease;
}

.login-submit:hover:not(:disabled) { background: var(--login-green-deep); }

.login-submit:disabled {
  cursor: not-allowed;
  opacity: .45;
  box-shadow: none;
}

.form-foot {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px solid var(--login-line);
  color: var(--login-faint);
  font-size: 9.5px;
}

@media (max-width: 900px) {
  .login-page { grid-template-columns: minmax(0, 1fr); }
  .login-brief {
    gap: 22px;
    padding: 28px 24px 24px;
    border-right: 0;
    border-bottom: 1px solid var(--login-line);
  }
  .brief-copy { margin-top: 0; }
  .brief-copy h1 { font-size: clamp(26px, 7vw, 34px); }
  .brief-copy > p { font-size: 12px; }
  .brief-points { display: none; }
  .brief-foot { margin-top: 4px; }
  .login-panel { padding: 44px 20px 48px; }
  .login-home { position: static; justify-self: start; margin-bottom: 14px; }
}

@media (max-width: 520px) {
  .login-form { padding: 24px 18px; }
  .form-header h2 { font-size: 23px; }
  .form-options { flex-direction: column; align-items: flex-start; gap: 6px; }
}

/* ── 登录动效 ───────────────────────────────────────────── */
@keyframes login-rise {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: none; }
}

@keyframes login-float {
  from { transform: translate3d(0, 0, 0) scale(1); }
  to { transform: translate3d(-42px, 26px, 0) scale(1.08); }
}

.login-page {
  position: relative;
  overflow-x: hidden;
}

.login-page::before,
.login-page::after {
  position: absolute;
  border-radius: 50%;
  content: "";
  pointer-events: none;
}

.login-page::before {
  top: -260px;
  right: -180px;
  width: 720px;
  height: 720px;
  background: radial-gradient(circle, rgba(23, 127, 111, .16), transparent 66%);
  animation: login-float 16s ease-in-out infinite alternate;
}

.login-page::after {
  bottom: -300px;
  left: -220px;
  width: 640px;
  height: 640px;
  background: radial-gradient(circle, rgba(23, 127, 111, .08), transparent 68%);
  animation: login-float 20s ease-in-out infinite alternate-reverse;
}

.login-brief,
.login-panel { position: relative; z-index: 1; }

.brief-brand { animation: login-rise .65s .05s both; }
.brief-copy .eyebrow { animation: login-rise .65s .12s both; }
.brief-copy h1 { animation: login-rise .75s .2s both; }
.brief-copy > p { animation: login-rise .75s .3s both; }
.brief-points li:nth-child(1) { animation: login-rise .7s .38s both; }
.brief-points li:nth-child(2) { animation: login-rise .7s .46s both; }
.brief-points li:nth-child(3) { animation: login-rise .7s .54s both; }
.brief-foot { animation: login-rise .7s .62s both; }

.login-home { animation: login-rise .6s .1s both; }
.login-form { animation: login-rise .8s .18s both; }

.login-form {
  transition: box-shadow .25s ease, transform .25s ease;
}

.login-form:focus-within {
  box-shadow: 0 28px 70px rgba(21, 33, 29, .12);
}

@media (prefers-reduced-motion: reduce) {
  .login-page::before,
  .login-page::after,
  .brief-brand,
  .brief-copy .eyebrow,
  .brief-copy h1,
  .brief-copy > p,
  .brief-points li,
  .brief-foot,
  .login-home,
  .login-form {
    animation: none;
  }
}
</style>
