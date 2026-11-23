import { defineConfig } from "vite";

// The math script of the MCP forms (ADR-012): RecallSpring's own TeX parser and DOM renderer as one
// self-contained file, inlined into each form by the connector. Rebuild after changing mathParse.ts or mathDom.ts.
export default defineConfig({
  build: {
    outDir: "../../services/mcp/src/recallspring_mcp",
    emptyOutDir: false,
    copyPublicDir: false,
    minify: true,
    lib: { entry: "src/mcpMath.ts", formats: ["iife"], name: "RecallSpringMathBundle", fileName: () => "math.js" },
  },
});
