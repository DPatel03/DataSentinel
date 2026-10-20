import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiPort = env.DASHBOARD_API_PORT || "8888";
  const devPort = Number(env.DASHBOARD_DEV_PORT || "3000");

  return {
    plugins: [react()],
    server: {
      port: devPort,
      proxy: {
        "/api": {
          target: `http://localhost:${apiPort}`,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
    },
  };
});
