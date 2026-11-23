// Entry of the math script inlined into the MCP forms (npm run build:mcp-math; ADR-012).
import { renderMathText } from "./components/mathDom";

(globalThis as unknown as { RecallSpringMath: unknown }).RecallSpringMath = { render: renderMathText };
