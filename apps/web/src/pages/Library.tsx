import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { API, get } from "../api";
import { Async, Card, Empty, Highlighted, PageHead } from "../components/ui";
import { Upload } from "../components/Upload";
import { bytes, dateLabel, dateTime, plural } from "../format";
import { courseTitles, useCourses, useSources } from "../queries";
import type { SearchHit, Section, Source } from "../types";

const STATE: Record<Source["parse_state"], { tone: string; label: string }> = {
  pending: { tone: "chip", label: "Queued" },
  processing: { tone: "chip", label: "Processing" },
  ready: { tone: "chip good", label: "Ready" },
  needs_attention: { tone: "chip warn", label: "Needs attention" },
  failed: { tone: "chip bad", label: "Failed" },
};

export function StateChip({ state }: { state: Source["parse_state"] }) {
  return <span className={STATE[state].tone}>{STATE[state].label}</span>;
}

export function SourceTable({ sources, titles }: { sources: Source[]; titles?: Record<string, string> }) {
  if (sources.length === 0) {
    return <Empty title="No material yet">Drop a PDF, Markdown or text file, or ask Claude to import one from your computer.</Empty>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Material</th>
            {titles && <th>Course</th>}
            <th>Text</th>
            <th>Pages</th>
            <th>Sections</th>
            <th>Size</th>
            <th>Added</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.id}>
              <td>
                <Link to={`/library/${s.id}`} style={{ fontWeight: 600 }}>
                  {s.filename}
                </Link>
                {s.duplicate_of_id && <div className="tiny muted">Same file as another upload</div>}
              </td>
              {titles && <td className="small">{titles[s.course_id] ?? ""}</td>}
              <td>
                <StateChip state={s.parse_state} />
              </td>
              <td>{s.page_count ?? "—"}</td>
              <td>{s.section_count}</td>
              <td className="small nowrap">{bytes(s.byte_size)}</td>
              <td className="small nowrap">{dateLabel(s.uploaded_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Search() {
  const [draft, setDraft] = useState("");
  const [term, setTerm] = useState("");
  const q = useQuery({
    queryKey: ["search", term],
    queryFn: () => get<{ hits: SearchHit[]; note: string }>("/sources/search", { q: term, limit: 20 }),
    enabled: term.length > 1,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    setTerm(draft.trim());
  }
  return (
    <Card title="Search your material">
      <form className="row" onSubmit={submit} role="search">
        <label style={{ flex: 1, minWidth: 220 }}>
          <span className="sr-only">Search text</span>
          <input type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="A word or phrase in any language" />
        </label>
        <button type="submit" className="btn">
          Search
        </button>
      </form>
      {term.length > 1 && (
        <div style={{ marginTop: 14 }}>
          <Async q={q}>
            {(r) =>
              r.hits.length === 0 ? (
                <p className="small muted">No match for “{term}”.</p>
              ) : (
                <ul className="list">
                  {r.hits.map((h) => (
                    <li key={h.section_id}>
                      <div className="small">
                        <Link to={`/library/${h.source_id}#${h.section_id}`}>{h.filename}</Link> · {h.citation_label}
                      </div>
                      <div className="small muted">
                        <Highlighted text={h.snippet} />
                      </div>
                    </li>
                  ))}
                </ul>
              )
            }
          </Async>
        </div>
      )}
    </Card>
  );
}

export function LibraryPage() {
  const sources = useSources();
  const courses = useCourses();
  const titles = courseTitles(courses.data);
  return (
    <div className="page">
      <PageHead title="Library" sub="Your original files and the text RecallSpring extracted from them. Claude cites these sections." />
      <Async q={sources}>{(list) => <SourceTable sources={list} titles={titles} />}</Async>
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <Search />
        <Card title="Add material">
          <Upload />
        </Card>
      </div>
    </div>
  );
}

const PAGE = 25;

export function SourcePage() {
  const { sourceId = "" } = useParams();
  const [offset, setOffset] = useState(0);
  const courses = useCourses();
  const titles = courseTitles(courses.data);
  const source = useQuery({
    queryKey: ["source", sourceId],
    queryFn: () => get<Source>(`/sources/${sourceId}`),
    refetchInterval: (q) => (q.state.data && ["pending", "processing"].includes(q.state.data.parse_state) ? 2500 : false),
  });
  const sections = useQuery({
    queryKey: ["sections", sourceId, offset],
    queryFn: () => get<{ sections: Section[]; total: number }>(`/sources/${sourceId}/sections`, { offset, limit: PAGE }),
    enabled: source.data?.parse_state === "ready" || source.data?.parse_state === "needs_attention",
  });
  return (
    <div className="page">
      <Async q={source} lines={6}>
        {(s) => (
          <>
            <PageHead
              title={s.filename}
              crumbs={[
                { to: "/library", label: "Library" },
                { to: `/courses/${s.course_id}?tab=materials`, label: titles[s.course_id] ?? "Course" },
              ]}
            >
              <StateChip state={s.parse_state} />
              <a className="btn small" href={`${API}/sources/${s.id}/file`} download>
                Download original
              </a>
            </PageHead>
            <div className="split">
              <div className="stack">
                {s.parse_message && <div className={s.parse_state === "failed" ? "notice bad" : "notice warn"}>{s.parse_message}</div>}
                {sections.data ? (
                  <Card title="Extracted text" meta={`${plural(sections.data.total, "section")}`}>
                    <ol className="list" style={{ listStyle: "none" }}>
                      {sections.data.sections.map((sec) => (
                        <li key={sec.id} id={sec.id} className="stack" style={{ gap: 4 }}>
                          <div className="small muted">
                            {sec.citation_label}
                            {sec.heading && ` · ${sec.heading}`}
                          </div>
                          <p className="reading pre small">{sec.text}</p>
                        </li>
                      ))}
                    </ol>
                    {sections.data.total > PAGE && (
                      <div className="row" style={{ justifyContent: "space-between", marginTop: 12 }}>
                        <button type="button" className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                          Previous
                        </button>
                        <span className="small muted">
                          {offset + 1}–{Math.min(offset + PAGE, sections.data.total)} of {sections.data.total}
                        </span>
                        <button
                          type="button"
                          className="btn small"
                          disabled={offset + PAGE >= sections.data.total}
                          onClick={() => setOffset(offset + PAGE)}
                        >
                          Next
                        </button>
                      </div>
                    )}
                  </Card>
                ) : sections.isPending && sections.fetchStatus !== "idle" ? (
                  <Card title="Extracted text">
                    <p className="muted small">Loading…</p>
                  </Card>
                ) : (
                  <Card title="Extracted text">
                    <p className="muted small">
                      {s.parse_state === "failed"
                        ? "Text couldn't be extracted. Try a text-based PDF or paste the content."
                        : "Extraction is running in the background."}
                    </p>
                  </Card>
                )}
              </div>
              <Card title="Details">
                <dl className="kv small">
                  <dt>Type</dt>
                  <dd>{s.kind.toUpperCase()}</dd>
                  <dt>Size</dt>
                  <dd>{bytes(s.byte_size)}</dd>
                  <dt>Pages</dt>
                  <dd>{s.page_count ?? "—"}</dd>
                  <dt>Version</dt>
                  <dd>{s.version}</dd>
                  <dt>Added</dt>
                  <dd>{dateTime(s.uploaded_at)}</dd>
                  <dt>Via</dt>
                  <dd>{s.origin === "paste" ? "Pasted text" : "File upload"}</dd>
                  {s.parsed_at && (
                    <>
                      <dt>Extracted</dt>
                      <dd>{dateTime(s.parsed_at)}</dd>
                    </>
                  )}
                </dl>
                {s.parse_notes.length > 0 && (
                  <ul className="small muted" style={{ marginTop: 12 }}>
                    {s.parse_notes.map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          </>
        )}
      </Async>
    </div>
  );
}
