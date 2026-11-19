import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Development: the web app runs on 127.0.0.1:4317 and proxies the API (127.0.0.1:4318), so cookies stay
// same-origin. Production: `npm run build` writes dist/, which the API serves itself.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 4317,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:4318", changeOrigin: false } },
  },
  build: { sourcemap: false, assetsInlineLimit: 0 },
  test: { environment: "jsdom", include: ["src/**/*.test.{ts,tsx}"] },
});
