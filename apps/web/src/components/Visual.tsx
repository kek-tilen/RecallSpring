import { useId, useState, type ReactNode } from "react";

/**
 * RecallSpring's own drawings for the allowlisted visual blocks (packages/contracts/schemas/visual-block.schema.json),
 * checked on the server first (services/visual_blocks.py). Only data comes from the model; every shape, colour and
 * formula is defined here, and no model-written markup or code is ever run.
 */

interface GraphData {
  nodes: { id: string; label: string }[];
  edges: { from: string; to: string }[];
}
interface ComparisonData {
  columns: string[];
  rows: { criterion: string; values: string[] }[];
}
interface TimelineData {
  events: { label: string; description: string }[];
}
interface ChartData {
  chart: "line" | "bar" | "scatter";
  x_label: string;
  y_label: string;
  points: { x: string | number; y: number }[];
}
interface ParameterData {
  parameter: string;
  minimum: number;
  maximum: number;
  step: number;
  initial: number;
  preset: "linear_growth" | "exponential_decay" | "quadratic_curve" | "unit_circle";
}

export type VisualBlock =
  | { type: "process_flow" | "concept_map"; title: string; alt_text: string; illustrative?: boolean; data: GraphData }
  | { type: "comparison"; title: string; alt_text: string; illustrative?: boolean; data: ComparisonData }
  | { type: "timeline"; title: string; alt_text: string; illustrative?: boolean; data: TimelineData }
  | { type: "data_chart"; title: string; alt_text: string; illustrative?: boolean; data: ChartData }
  | { type: "interactive_parameter"; title: string; alt_text: string; illustrative?: boolean; data: ParameterData };

export type VisualResult = { ok: true; block: VisualBlock } | { ok: false; error: string };

const num = (n: number) => (Number.isInteger(n) ? n.toLocaleString("en-GB") : n.toLocaleString("en-GB", { maximumFractionDigits: 3 }));

/** Break a label into at most `max` lines of about `width` characters. */
export function wrap(text: string, width = 20, max = 3): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const w of words) {
    const word = w.length > width ? `${w.slice(0, width - 1)}…` : w;
    if (!line) line = word;
    else if (line.length + 1 + word.length <= width) line += ` ${word}`;
    else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  if (lines.length > max) {
    const kept = lines.slice(0, max);
    kept[max - 1] = `${kept[max - 1]!.slice(0, width - 1)}…`;
    return kept;
  }
  return lines.length ? lines : [""];
}

function Label({ x, y, lines, anchor = "middle" }: { x: number; y: number; lines: string[]; anchor?: "middle" | "start" | "end" }) {
  const top = y - ((lines.length - 1) * 16) / 2;
  return (
    <text className="viz-label" x={x} y={top} textAnchor={anchor} dominantBaseline="middle">
      {lines.map((l, i) => (
        <tspan key={i} x={x} dy={i === 0 ? 0 : 16}>
          {l}
        </tspan>
      ))}
    </text>
  );
}

function Arrowhead({ id }: { id: string }) {
  return (
    <defs>
      <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" className="viz-arrow" />
      </marker>
    </defs>
  );
}

const NODE_W = 170;

/** Levels for a top-to-bottom flow: longest path from the starting steps; edges that close a cycle are kept aside. */
export function levels(data: GraphData): { level: Map<string, number>; back: Set<number> } {
  const ids = data.nodes.map((n) => n.id);
  const out = new Map(ids.map((id) => [id, [] as number[]]));
  data.edges.forEach((e, i) => out.get(e.from)?.push(i));
  const state = new Map<string, 0 | 1 | 2>();
  const back = new Set<number>();
  const visit = (id: string) => {
    state.set(id, 1);
    for (const i of out.get(id) ?? []) {
      const to = data.edges[i]!.to;
      const s = state.get(to) ?? 0;
      if (s === 1 || to === id) back.add(i);
      else if (s === 0) visit(to);
    }
    state.set(id, 2);
  };
  ids.forEach((id) => (state.get(id) ? undefined : visit(id)));
  const level = new Map(ids.map((id) => [id, 0]));
  for (let pass = 0; pass < ids.length; pass++) {
    let changed = false;
    data.edges.forEach((e, i) => {
      if (back.has(i)) return;
      const next = (level.get(e.from) ?? 0) + 1;
      if (next > (level.get(e.to) ?? 0)) {
        level.set(e.to, next);
        changed = true;
      }
    });
    if (!changed) break;
  }
  return { level, back };
}

function ProcessFlow({ data, alt }: { data: GraphData; alt: string }) {
  const arrow = useId().replace(/:/g, "");
  const { level, back } = levels(data);
  const rows: string[][] = [];
  data.nodes.forEach((n) => (rows[level.get(n.id) ?? 0] ??= []).push(n.id));
  const label = new Map(data.nodes.map((n) => [n.id, wrap(n.label)]));
  const widest = Math.max(...rows.map((r) => r?.length ?? 0));
  const width = Math.max(widest * (NODE_W + 24) + 24, 320) + (back.size ? 70 : 0);
  const rowH = 3 * 16 + 20;
  const gapY = 44;
  const pos = new Map<string, { x: number; y: number; h: number }>();
  rows.forEach((row, r) => {
    if (!row) return;
    const total = row.length * NODE_W + (row.length - 1) * 24;
    const start = (width - (back.size ? 70 : 0) - total) / 2;
    row.forEach((id, i) => {
      const h = label.get(id)!.length * 16 + 20;
      pos.set(id, { x: start + i * (NODE_W + 24), y: 16 + r * (rowH + gapY) + (rowH - h) / 2, h });
    });
  });
  const height = 16 + rows.length * (rowH + gapY) - gapY + 16;
  return (
    <svg className="viz-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={alt} style={{ maxWidth: width }}>
      <Arrowhead id={arrow} />
      {data.edges.map((e, i) => {
        const a = pos.get(e.from)!;
        const b = pos.get(e.to)!;
        if (!back.has(i) && (level.get(e.to) ?? 0) > (level.get(e.from) ?? 0)) {
          const x1 = a.x + NODE_W / 2;
          const y1 = a.y + a.h;
          const x2 = b.x + NODE_W / 2;
          const y2 = b.y - 2;
          const my = (y1 + y2) / 2;
          return <path key={i} className="viz-edge" d={`M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`} markerEnd={`url(#${arrow})`} />;
        }
        const x1 = a.x + NODE_W;
        const y1 = a.y + a.h / 2;
        const x2 = b.x + NODE_W + 2;
        const y2 = b.y + b.h / 2;
        const bend = Math.max(x1, x2) + 50;
        return <path key={i} className="viz-edge back" d={`M${x1},${y1} C${bend},${y1} ${bend},${y2} ${x2},${y2}`} markerEnd={`url(#${arrow})`} />;
      })}
      {data.nodes.map((n) => {
        const p = pos.get(n.id)!;
        return (
          <g key={n.id}>
            <rect className="viz-node" x={p.x} y={p.y} width={NODE_W} height={p.h} rx={10} />
            <Label x={p.x + NODE_W / 2} y={p.y + p.h / 2} lines={label.get(n.id)!} />
          </g>
        );
      })}
    </svg>
  );
}

/** The node in the middle of a concept map: the one most linked, when it links to at least three others. */
export function hub(data: GraphData): string | null {
  const degree = new Map<string, number>();
  for (const e of data.edges) {
    if (e.from === e.to) continue;
    degree.set(e.from, (degree.get(e.from) ?? 0) + 1);
    degree.set(e.to, (degree.get(e.to) ?? 0) + 1);
  }
  let best: string | null = null;
  for (const n of data.nodes) if ((degree.get(n.id) ?? 0) > (best ? degree.get(best)! : 2)) best = n.id;
  return data.nodes.length >= 4 ? best : null;
}

function ConceptMap({ data, alt }: { data: GraphData; alt: string }) {
  const arrow = useId().replace(/:/g, "");
  const W = 150;
  const centre = hub(data);
  const ring = data.nodes.filter((d) => d.id !== centre);
  const n = ring.length;
  // Far enough apart that neighbouring boxes on the circle do not touch.
  const R = n <= 1 ? 0 : Math.max(centre ? W + 50 : 110, (W + 30) / (2 * Math.sin(Math.PI / n)));
  const cx = R + W / 2 + 20;
  const cy = R + 50;
  const label = new Map(data.nodes.map((d) => [d.id, wrap(d.label, 18)]));
  const box = (id: string, x: number, y: number) => [id, { x, y, h: label.get(id)!.length * 16 + 16 }] as const;
  const pos = new Map([
    ...(centre ? [box(centre, cx, cy)] : []),
    ...ring.map((d, i) => {
      const angle = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(n, 1);
      return box(d.id, cx + R * Math.cos(angle), cy + R * Math.sin(angle));
    }),
  ]);
  const width = 2 * cx;
  const height = 2 * cy;
  /** Where the line from a box's centre towards (dx, dy) leaves the box. */
  const edgeOf = (h: number, dx: number, dy: number) => {
    const t = Math.min(dx ? W / 2 / Math.abs(dx) : Infinity, dy ? h / 2 / Math.abs(dy) : Infinity);
    return [dx * t, dy * t] as const;
  };
  return (
    <svg className="viz-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={alt} style={{ maxWidth: width }}>
      <Arrowhead id={arrow} />
      {data.edges.map((e, i) => {
        const a = pos.get(e.from)!;
        const b = pos.get(e.to)!;
        if (e.from === e.to) return null;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const [ax, ay] = edgeOf(a.h, dx, dy);
        const [bx, by] = edgeOf(b.h, -dx, -dy);
        return (
          <line key={i} className="viz-edge" x1={a.x + ax} y1={a.y + ay} x2={b.x + bx} y2={b.y + by} markerEnd={`url(#${arrow})`} />
        );
      })}
      {data.nodes.map((d) => {
        const p = pos.get(d.id)!;
        return (
          <g key={d.id}>
            <rect className="viz-node" x={p.x - W / 2} y={p.y - p.h / 2} width={W} height={p.h} rx={p.h / 2} />
            <Label x={p.x} y={p.y} lines={label.get(d.id)!} />
          </g>
        );
      })}
    </svg>
  );
}

function Comparison({ data }: { data: ComparisonData }) {
  return (
    <div className="table-wrap">
      <table className="viz-table">
        <thead>
          <tr>
            <th scope="col">
              <span className="sr-only">Criterion</span>
            </th>
            {data.columns.map((c, i) => (
              <th key={i} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i}>
              <th scope="row">{r.criterion}</th>
              {r.values.map((v, j) => (
                <td key={j}>{v}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Timeline({ data }: { data: TimelineData }) {
  return (
    <ol className="viz-timeline">
      {data.events.map((e, i) => (
        <li key={i}>
          <strong>{e.label}</strong>
          <span>{e.description}</span>
        </li>
      ))}
    </ol>
  );
}

/** About `count` round tick values covering [lo, hi]. */
export function ticks(lo: number, hi: number, count = 5): number[] {
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.round(v / step) * step);
  if (out[out.length - 1]! < hi) out.push(out[out.length - 1]! + step);
  return out;
}

function Chart({ data, alt }: { data: ChartData; alt: string }) {
  const W = 520;
  const H = 300;
  const m = { l: 60, r: 16, t: 16, b: 56 };
  const pw = W - m.l - m.r;
  const ph = H - m.t - m.b;
  const categorical = data.chart === "bar" || data.points.some((p) => typeof p.x === "string");
  const ys = data.points.map((p) => p.y);
  const yt = ticks(Math.min(...ys, data.chart === "bar" ? 0 : Math.min(...ys)), Math.max(...ys, data.chart === "bar" ? 0 : Math.max(...ys)));
  const y0 = yt[0]!;
  const y1 = yt[yt.length - 1]!;
  const sy = (v: number) => m.t + ph - ((v - y0) / (y1 - y0)) * ph;
  let sx: (p: { x: string | number }, i: number) => number;
  let xTicks: { x: number; label: string }[];
  const band = pw / data.points.length;
  if (categorical) {
    sx = (_p, i) => m.l + band * i + band / 2;
    const every = Math.ceil(data.points.length / 10);
    xTicks = data.points.flatMap((p, i) => (i % every === 0 ? [{ x: sx(p, i), label: String(p.x).slice(0, 12) }] : []));
  } else {
    const xs = data.points.map((p) => p.x as number);
    const xt = ticks(Math.min(...xs), Math.max(...xs));
    const x0 = xt[0]!;
    const x1 = xt[xt.length - 1]!;
    sx = (p) => m.l + (((p.x as number) - x0) / (x1 - x0)) * pw;
    xTicks = xt.map((v) => ({ x: m.l + ((v - x0) / (x1 - x0)) * pw, label: num(v) }));
  }
  const ordered = data.points.map((p, i) => ({ p, i, x: sx(p, i) }));
  if (!categorical) ordered.sort((a, b) => a.x - b.x);
  return (
    <svg className="viz-svg viz-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={alt} style={{ maxWidth: W }}>
      {yt.map((v) => (
        <g key={`y${v}`}>
          <line className="viz-grid" x1={m.l} x2={W - m.r} y1={sy(v)} y2={sy(v)} />
          <text className="viz-tick" x={m.l - 8} y={sy(v)} textAnchor="end" dominantBaseline="middle">
            {num(v)}
          </text>
        </g>
      ))}
      {xTicks.map((t, i) => (
        <text key={`x${i}`} className="viz-tick" x={t.x} y={H - m.b + 18} textAnchor="middle">
          {t.label}
        </text>
      ))}
      <line className="viz-axis" x1={m.l} x2={W - m.r} y1={sy(Math.max(y0, Math.min(0, y1)))} y2={sy(Math.max(y0, Math.min(0, y1)))} />
      {data.chart === "bar" &&
        data.points.map((p, i) => {
          const base = sy(Math.max(y0, Math.min(0, y1)));
          const top = sy(p.y);
          return <rect key={i} className="viz-bar" x={sx(p, i) - band * 0.35} width={band * 0.7} y={Math.min(base, top)} height={Math.abs(base - top)} rx={3} />;
        })}
      {data.chart === "line" && <path className="viz-line" d={ordered.map((o, k) => `${k ? "L" : "M"}${o.x},${sy(o.p.y)}`).join(" ")} />}
      {data.chart !== "bar" && ordered.map((o) => <circle key={o.i} className="viz-point" cx={o.x} cy={sy(o.p.y)} r={4} />)}
      <text className="viz-axis-label" x={m.l + pw / 2} y={H - 10} textAnchor="middle">
        {data.x_label}
      </text>
      <text className="viz-axis-label" transform={`translate(14 ${m.t + ph / 2}) rotate(-90)`} textAnchor="middle">
        {data.y_label}
      </text>
    </svg>
  );
}

function ChartTable({ data }: { data: ChartData }) {
  return (
    <details>
      <summary className="tiny">Data</summary>
      <div className="table-wrap">
        <table className="viz-table">
          <thead>
            <tr>
              <th scope="col">{data.x_label}</th>
              <th scope="col">{data.y_label}</th>
            </tr>
          </thead>
          <tbody>
            {data.points.map((p, i) => (
              <tr key={i}>
                <td>{typeof p.x === "number" ? num(p.x) : p.x}</td>
                <td>{num(p.y)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** The four predefined formulas a slider may drive. The model only chooses one and the slider's range. */
export const PRESETS = {
  linear_growth: { formula: (p: number) => `y = ${num(p)} · x`, f: (p: number, x: number) => p * x, x: [0, 10] as const },
  exponential_decay: {
    formula: (p: number) => `y = e^(−${num(p)} · x)`,
    f: (p: number, x: number) => Math.exp(-p * x),
    x: [0, 5] as const,
  },
  quadratic_curve: { formula: (p: number) => `y = ${num(p)} · x²`, f: (p: number, x: number) => p * x * x, x: [-3, 3] as const },
};

function Parameter({ data, alt }: { data: ParameterData; alt: string }) {
  const [p, setP] = useState(data.initial);
  const id = useId();
  const slider = (
    <label className="viz-slider" htmlFor={id}>
      <span>
        {data.parameter}: <strong>{num(p)}</strong>
      </span>
      <input
        id={id}
        type="range"
        min={data.minimum}
        max={data.maximum}
        step={data.step}
        value={p}
        onChange={(e) => setP(Number(e.target.value))}
      />
      <span className="tiny muted">
        {num(data.minimum)} – {num(data.maximum)}
      </span>
    </label>
  );
  if (data.preset === "unit_circle") {
    const rad = (p * Math.PI) / 180;
    const S = 260;
    const c = S / 2;
    const r = 100;
    const x = c + r * Math.cos(rad);
    const y = c - r * Math.sin(rad);
    return (
      <div className="stack" style={{ gap: 8 }}>
        {slider}
        <svg className="viz-svg" viewBox={`0 0 ${S} ${S}`} role="img" aria-label={alt} style={{ maxWidth: S }}>
          <line className="viz-grid" x1={10} x2={S - 10} y1={c} y2={c} />
          <line className="viz-grid" x1={c} x2={c} y1={10} y2={S - 10} />
          <circle className="viz-circle" cx={c} cy={c} r={r} />
          <line className="viz-guide" x1={x} x2={x} y1={y} y2={c} />
          <line className="viz-guide" x1={c} x2={x} y1={y} y2={y} />
          <line className="viz-line" x1={c} y1={c} x2={x} y2={y} />
          <circle className="viz-point" cx={x} cy={y} r={5} />
        </svg>
        <p className="small" style={{ margin: 0 }} aria-live="polite">
          angle {num(p)}° · cos = {num(Math.round(Math.cos(rad) * 1000) / 1000)} · sin = {num(Math.round(Math.sin(rad) * 1000) / 1000)}
        </p>
      </div>
    );
  }
  const preset = PRESETS[data.preset];
  const [xa, xb] = preset.x;
  const samples = 80;
  const curve = (q: number) => Array.from({ length: samples + 1 }, (_, i) => xa + ((xb - xa) * i) / samples).map((x) => ({ x, y: preset.f(q, x) }));
  // Fixed axes across the whole slider range, so moving it shows the change instead of rescaling.
  const all = [...curve(data.minimum), ...curve(data.maximum), ...curve(data.initial)].map((pt) => pt.y).filter(Number.isFinite);
  const clamp = (v: number) => Math.max(-1e6, Math.min(1e6, v));
  const yt = ticks(clamp(Math.min(...all, 0)), clamp(Math.max(...all, 0)));
  const W = 480;
  const H = 260;
  const m = { l: 52, r: 12, t: 12, b: 32 };
  const sx = (x: number) => m.l + ((x - xa) / (xb - xa)) * (W - m.l - m.r);
  const y0 = yt[0]!;
  const y1 = yt[yt.length - 1]!;
  const sy = (y: number) => m.t + (H - m.t - m.b) - ((clamp(y) - y0) / (y1 - y0)) * (H - m.t - m.b);
  const xt = ticks(xa, xb);
  return (
    <div className="stack" style={{ gap: 8 }}>
      {slider}
      <svg className="viz-svg viz-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={alt} style={{ maxWidth: W }}>
        <defs>
          <clipPath id={`${id.replace(/:/g, "")}clip`}>
            <rect x={m.l} y={m.t} width={W - m.l - m.r} height={H - m.t - m.b} />
          </clipPath>
        </defs>
        {yt.map((v) => (
          <g key={`y${v}`}>
            <line className="viz-grid" x1={m.l} x2={W - m.r} y1={sy(v)} y2={sy(v)} />
            <text className="viz-tick" x={m.l - 6} y={sy(v)} textAnchor="end" dominantBaseline="middle">
              {num(v)}
            </text>
          </g>
        ))}
        {xt.map((v) => (
          <text key={`x${v}`} className="viz-tick" x={sx(v)} y={H - 10} textAnchor="middle">
            {num(v)}
          </text>
        ))}
        <path
          className="viz-line"
          clipPath={`url(#${id.replace(/:/g, "")}clip)`}
          d={curve(p).map((pt, i) => `${i ? "L" : "M"}${sx(pt.x)},${sy(pt.y)}`).join(" ")}
        />
      </svg>
      <p className="small" style={{ margin: 0 }} aria-live="polite">
        {preset.formula(p)}
      </p>
    </div>
  );
}

function Body({ block }: { block: VisualBlock }): ReactNode {
  switch (block.type) {
    case "process_flow":
      return <ProcessFlow data={block.data} alt={block.alt_text} />;
    case "concept_map":
      return <ConceptMap data={block.data} alt={block.alt_text} />;
    case "comparison":
      return <Comparison data={block.data} />;
    case "timeline":
      return <Timeline data={block.data} />;
    case "data_chart":
      return (
        <>
          <Chart data={block.data} alt={block.alt_text} />
          <ChartTable data={block.data} />
        </>
      );
    case "interactive_parameter":
      return <Parameter data={block.data} alt={block.alt_text} />;
    default:
      return null;
  }
}

/** A checked visual with its title, labels and the full text description; or why it could not be shown. */
export function Visual({ result, raw, source }: { result: VisualResult | undefined; raw: string; source: string }) {
  if (!result || !result.ok) {
    return (
      <div className="notice small viz-failed">
        This visual could not be shown{result && !result.ok ? `: ${result.error}` : "."} The explanation in the text still
        applies.
        <details>
          <summary className="tiny">What {source} sent</summary>
          <pre className="md-code">
            <code>{raw}</code>
          </pre>
        </details>
      </div>
    );
  }
  const b = result.block;
  return (
    <figure className="viz">
      <figcaption className="viz-head">
        <strong>{b.title}</strong>
        {b.illustrative && <span className="chip warn">Illustrative example</span>}
      </figcaption>
      <div className="viz-body">
        <Body block={b} />
      </div>
      <p className="tiny muted" style={{ margin: 0 }}>
        Drawn by RecallSpring from data {source} sent · not checked against your material
      </p>
      <details>
        <summary className="tiny">Text description</summary>
        <p className="small" style={{ margin: "6px 0 0" }}>
          {b.alt_text}
        </p>
      </details>
    </figure>
  );
}
