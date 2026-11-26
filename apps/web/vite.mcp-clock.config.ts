import { defineConfig } from "vite";

// The answer clock of the MCP forms (ADR-014 §3): how long each question was open and visible, without pauses over
// 5 minutes, as one self-contained file inlined into the answer and simulation forms by the connector. Rebuild after
// changing answerClock.ts.
export default defineConfig({
  build: {
    outDir: "../../services/mcp/src/recallspring_mcp",
    emptyOutDir: false,
    copyPublicDir: false,
    minify: true,
    lib: { entry: "src/mcpClock.ts", formats: ["iife"], name: "RecallSpringClockBundle", fileName: () => "clock.js" },
  },
});
