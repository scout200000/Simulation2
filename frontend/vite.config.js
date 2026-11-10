import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_BACKEND_PROXY || "http://127.0.0.1:8770";
  const proxy = {
    "/api": {
      target: backend,
      changeOrigin: true
    }
  };

  return {
    base: "./",
    plugins: [vue()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      proxy
    },
    preview: {
      host: "127.0.0.1",
      port: 4173,
      proxy
    }
  };
});
