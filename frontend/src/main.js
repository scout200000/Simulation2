import { createApp } from "vue";
import App from "./App.vue";
import router from "./router/index.js";
import "./styles/base.css";

const apiBase = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
globalThis.SIMULATION_API_BASE = apiBase;

createApp(App).use(router).mount("#app");
