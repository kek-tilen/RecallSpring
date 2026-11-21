import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router";
import { ApiError } from "../api";
import { BAND_LABEL, DIFFICULTY_SOURCE, STUDY_LABEL, gradeLabel } from "../format";
import type { Band, Progress, StudyStatus } from "../types";

export function Card({ title, meta, children, tint, action, id }: {
  id?: string;
  title?: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  tint?: boolean;
  action?: ReactNode;
}) {
  return (
    <section id={id} className={tint ? "card tint" : "card"}>
      {(title || meta || action) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          <div className="row">
            {meta && <span className="meta">{meta}</span>}
            {action}
          </div>
        </div>
      )}
      {children}
    </section>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <div className="small">{children}</div>}
    </div>
  );
}

export function Loading({ lines = 3 }: { lines?: number }) {
  return (
    <div className="stack" role="status" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  const id = error instanceof ApiError ? error.requestId : undefined;
  return (
    <div className="notice bad" role="alert">
      {message}
      {id && <span className="muted tiny"> (request {id})</span>}
    </div>
  );
}

/** Loading / error / content in one place. */
export function Async<T>({ q, children, lines }: {
  q: { data: T | undefined; error: unknown; isPending: boolean };
  children: (data: T) => ReactNode;
  lines?: number;
}) {
  if (q.isPending) return <Loading lines={lines} />;
  if (q.error) return <ErrorNote error={q.error} />;
  return <>{children(q.data as T)}</>;
}

export function PageHead({ title, sub, crumbs, children }: {
  title: ReactNode;
  sub?: ReactNode;
  crumbs?: { to: string; label: string }[];
  children?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        {crumbs && (
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.map((c, i) => (
              <span key={c.to}>
                {i > 0 && " / "}
                <Link to={c.to}>{c.label}</Link>
              </span>
            ))}
          </nav>
        )}
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {children && <div className="row">{children}</div>}
    </header>
  );
}

const STUDY_TONE: Record<StudyStatus, string> = { not_studied: "chip", studied: "chip good", known: "chip solid" };

export function StudyChip({ status }: { status: StudyStatus }) {
  return <span className={STUDY_TONE[status]}>{STUDY_LABEL[status]}</span>;
}

const BAND_STEP: Record<Band, number> = { not_started: 0, emerging: 1, developing: 2, reliable: 3 };

export function BandChip({ band }: { band: Band }) {
  return (
    <span className="chip" title="Estimated from practice, not a guarantee of recall">
      <span className={`sw-inline r${BAND_STEP[band]}`} aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2 }} />
      {BAND_LABEL[band]}
    </span>
  );
}

export function Difficulty({ value, source }: { value: number; source?: string }) {
  const label = `Difficulty ${value} of 5${source ? ` (${DIFFICULTY_SOURCE[source] ?? source})` : ""}`;
  return (
    <span className="row" style={{ gap: 6 }} title={label}>
      <span className="dots" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((i) => (
          <i key={i} className={i <= value ? "on" : ""} />
        ))}
      </span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function GradeChip({ grade, status }: { grade: number | null | undefined; status?: string | null }) {
  const tone = grade === null || grade === undefined ? "chip" : grade >= 3 ? "chip good" : grade === 2 ? "chip warn" : "chip bad";
  return (
    <span className={tone}>
      {gradeLabel(grade)}
      {status && status !== "final" && <span className="muted">· {status}</span>}
    </span>
  );
}

interface Segment {
  label: string;
  value: number;
  step: number | "w"; // 0-3 along the ramp; "w" marks a warning (weak)
}

/** Ordinal stacked meter (one hue, light → dark) with an always-visible legend carrying the counts. */
export function Meter({ segments, label }: { segments: Segment[]; label: string }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  const summary = segments.map((s) => `${s.label}: ${s.value}`).join(", ");
  return (
    <figure style={{ margin: 0 }}>
      <div className="meter" role="img" aria-label={`${label}. ${summary}`}>
        {total === 0 ? (
          <span className="r0" style={{ flex: 1 }} />
        ) : (
          segments
            .filter((s) => s.value > 0)
            .map((s) => (
              <span key={s.label} className={`r${s.step}`} style={{ flex: s.value }} title={`${s.label}: ${s.value} of ${total}`} />
            ))
        )}
      </div>
      <figcaption className="legend">
        {segments.map((s) => (
          <span key={s.label} className="key">
            <span className={`sw r${s.step}`} aria-hidden="true" />
            {s.label} <b>{s.value}</b>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

export function StudyMeter({ progress }: { progress: Progress }) {
  return (
    <Meter
      label="Study progress"
      segments={[
        { label: "Not studied", value: progress.study.not_studied, step: 0 },
        { label: "Studied", value: progress.study.studied, step: 2 },
        { label: "Known", value: progress.study.known, step: 3 },
      ]}
    />
  );
}

export function BandMeter({ progress }: { progress: Progress }) {
  return (
    <Meter
      label="Knowledge estimate"
      segments={[
        { label: "Not started", value: progress.bands.not_started, step: 0 },
        { label: "Emerging", value: progress.bands.emerging, step: 1 },
        { label: "Developing", value: progress.bands.developing, step: 2 },
        { label: "Reliable", value: progress.bands.reliable, step: 3 },
      ]}
    />
  );
}

export function Confirm({ open, title, children, confirmLabel, danger, busy, onConfirm, onClose }: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="confirm-title">
      <div className="stack">
        <h2 id="confirm-title">{title}</h2>
        <div className="small">{children}</div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={danger ? "btn danger" : "btn primary"} disabled={busy} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  );
}

/** Text with search highlights marked «like this» by the server; rendered as text nodes, never as HTML. */
export function Highlighted({ text }: { text: string }) {
  const parts = text.split(/(«[^»]*»)/g);
  return (
    <>
      {parts.map((p, i) => (p.startsWith("«") && p.endsWith("»") ? <mark key={i}>{p.slice(1, -1)}</mark> : <span key={i}>{p}</span>))}
    </>
  );
}

/** Native modal dialog (focus trap, Escape to close) for forms. */
export function Modal({ open, title, children, onClose, wide }: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} aria-label={title} style={wide ? { maxWidth: "min(720px, calc(100vw - 32px))", width: "100%" } : { width: "100%" }}>
      {open && (
        <div className="stack">
          <h2>{title}</h2>
          {children}
        </div>
      )}
    </dialog>
  );
}
