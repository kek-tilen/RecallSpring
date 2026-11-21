import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { get, request } from "../api";
import { ImportSummary, Upload } from "../components/Upload";
import { Async, Card, Confirm, ErrorNote, Modal, PageHead } from "../components/ui";
import { bytes, dateLabel, plural } from "../format";
import { keys, useChatImport, useChatImports, useCourses, useFolders, usePreferences } from "../queries";
import type { ChatConversation, ChatImport, ImportResult, StudyPreferences } from "../types";

const DEFAULT_FOLDER = "Chats from ChatGPT";

/** The learner's own words on how they like to study; the assistant reads them at the start of every session. */
export function PreferencesEditor({ suggestion }: { suggestion?: string }) {
  const q = usePreferences();
  return <Async q={q}>{(p) => <PreferencesForm initial={p} suggestion={suggestion} />}</Async>;
}

function PreferencesForm({ initial, suggestion }: { initial: StudyPreferences; suggestion?: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState(initial.text);
  useEffect(() => setText(initial.text), [initial.text]);
  const save = useMutation({
    mutationFn: () => request<StudyPreferences>("/settings/preferences", { method: "PUT", json: { text } }),
    onSuccess: (p) => qc.setQueryData(keys.preferences, p),
  });
  const over = text.trim().length > initial.max_chars;
  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }
  return (
    <form className="stack" onSubmit={submit}>
      <p className="small muted" style={{ margin: 0 }}>
        How you like to learn, in your own words: for example “ask me questions before explaining” or “explain with
        examples from medicine”. Your assistant follows them where they fit; they never change how answers are graded.
      </p>
      <label className="field">
        <span className="sr-only">Study preferences</span>
        <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder="Nothing yet." />
      </label>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <span className={over ? "small" : "small muted"} style={over ? { color: "var(--danger)" } : undefined}>
          {text.trim().length} / {initial.max_chars} characters
        </span>
        <span className="row" style={{ gap: 8 }}>
          {suggestion && (
            <button
              type="button"
              className="btn small ghost"
              onClick={() => setText((t) => (t.trim() ? `${t.trim()}\n\n${suggestion}` : suggestion))}
            >
              Add what was found in the export
            </button>
          )}
          <button type="submit" className="btn small primary" disabled={save.isPending || over || text === initial.text}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </span>
      </div>
      {save.isSuccess && text === initial.text && (
        <span className="small muted" role="status">
          Saved. Your assistant sees them the next time it starts a study session.
        </span>
      )}
      {save.error && <ErrorNote error={save.error} />}
    </form>
  );
}

function ChatGptStart({ onOpen }: { onOpen: (id: string) => void }) {
  const qc = useQueryClient();
  const staged = useChatImports();
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.set("file", file);
      return request<ChatImport>("/imports/chatgpt", { form });
    },
    onSuccess: (view) => {
      qc.setQueryData(keys.chatImport(view.id), view);
      void qc.invalidateQueries({ queryKey: keys.chatImports });
      onOpen(view.id);
    },
  });
  return (
    <div className="stack">
      <ol className="small" style={{ margin: 0, paddingLeft: 20 }}>
        <li>
          In ChatGPT open <strong>Settings → Data controls → Export data</strong> and confirm.
        </li>
        <li>ChatGPT emails you a link. Download the ZIP; there is no need to unpack it.</li>
        <li>
          Upload it here. RecallSpring keeps it privately for a few days while you pick the chats that belong to your
          courses. Nothing goes into your library until you save it.
        </li>
      </ol>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button type="button" className="btn primary" onClick={() => input.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? "Reading the export…" : "Upload ChatGPT export"}
        </button>
        <input
          ref={input}
          type="file"
          accept=".zip,application/zip"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
            e.target.value = "";
          }}
        />
      </div>
      {upload.error && <ErrorNote error={upload.error} />}
      <Async q={staged} lines={2}>
        {(list) =>
          list.length === 0 ? null : (
            <ul className="list" aria-label="Uploaded exports">
              {list.map((i) => (
                <li key={i.id} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                  <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                    <strong style={{ overflowWrap: "anywhere" }}>{i.filename}</strong>
                    <span className="tiny muted">
                      Uploaded {dateLabel(i.created_at)} · {plural(i.conversations, "chat")}, {i.saved} saved · removed{" "}
                      {dateLabel(i.expires_at)}
                    </span>
                  </span>
                  <button type="button" className="btn small" onClick={() => onOpen(i.id)}>
                    Pick chats
                  </button>
                </li>
              ))}
            </ul>
          )
        }
      </Async>
      <p className="tiny muted" style={{ margin: 0 }}>
        Chats are saved word for word as material of the course you choose. ChatGPT's replies are not treated as
        course material, and nothing is graded from them; your assistant can go through them with you and suggest what you
        may already know.
      </p>
    </div>
  );
}

function suggestionFrom(view: ChatImport): string | undefined {
  const parts: string[] = [];
  if (view.instructions?.about_you) parts.push(`About me: ${view.instructions.about_you}`);
  if (view.instructions?.how_to_respond) parts.push(`How I like answers: ${view.instructions.how_to_respond}`);
  if (view.memories.length) parts.push(["What ChatGPT remembered about me:", ...view.memories.slice(0, 20).map((m) => `- ${m}`)].join("\n"));
  return parts.length ? parts.join("\n\n") : undefined;
}

function Preview({ importId, chat, onClose }: { importId: string; chat: ChatConversation; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["imports", "chatgpt", importId, "chat", chat.key],
    queryFn: () => get<{ text: string; truncated: boolean }>(`/imports/chatgpt/${importId}/chats/${chat.key}`),
  });
  return (
    <Modal open title={chat.title} onClose={onClose} wide>
      <Async q={q} lines={6}>
        {(p) => (
          <div className="stack" style={{ gap: 8 }}>
            <pre className="chat-preview">{p.text}</pre>
            {p.truncated && <span className="tiny muted">Only the beginning is shown here; the whole chat is saved.</span>}
          </div>
        )}
      </Async>
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  );
}

function ChatImportView({ id, onBack }: { id: string; onBack: () => void }) {
  const q = useChatImport(id);
  return (
    <Async q={q} lines={6}>
      {(view) => <ChatPicker view={view} onBack={onBack} />}
    </Async>
  );
}

function ChatPicker({ view, onBack }: { view: ChatImport; onBack: () => void }) {
  const qc = useQueryClient();
  const courses = useCourses();
  const active = (courses.data ?? []).filter((c) => c.status !== "archived");
  const [courseId, setCourseId] = useState("");
  const course = courseId || active[0]?.id || "";
  const folders = useFolders(course || undefined);
  const [folderId, setFolderId] = useState("");
  const [folderName, setFolderName] = useState(DEFAULT_FOLDER);
  const [withFiles, setWithFiles] = useState(true);
  const [term, setTerm] = useState("");
  const [project, setProject] = useState<string>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<ChatConversation | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [discarding, setDiscarding] = useState(false);
  const titles = Object.fromEntries((courses.data ?? []).map((c) => [c.id, c.title]));
  const projectLabel = Object.fromEntries(view.projects.map((p, i) => [p.id, `Project ${i + 1}`]));

  const shown = useMemo(() => {
    const needle = term.trim().toLowerCase();
    return view.conversations.filter(
      (c) =>
        (project === "all" || (project === "none" ? !c.project : c.project === project)) &&
        (!needle || c.title.toLowerCase().includes(needle)),
    );
  }, [view.conversations, term, project]);
  const pickable = shown.filter((c) => !c.too_large);
  const chosen = view.conversations.filter((c) => selected.has(c.key));
  const files = chosen.reduce((n, c) => n + c.files, 0);

  function toggle(key: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const save = useMutation({
    mutationFn: () =>
      request<ImportResult>(`/imports/chatgpt/${view.id}/save`, {
        json: {
          course_id: course,
          folder_id: folderId || null,
          folder: folderName.trim() || null,
          keys: chosen.map((c) => c.key),
          include_files: withFiles,
        },
      }),
    onSuccess: (r) => {
      setResult(r);
      setSelected(new Set());
      for (const key of [keys.chatImport(view.id), keys.chatImports, ["sources"], ["folders"], ["courses"], ["dashboard"]]) {
        void qc.invalidateQueries({ queryKey: [...key] });
      }
    },
  });
  const discard = useMutation({
    mutationFn: () => request(`/imports/chatgpt/${view.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.chatImports });
      onBack();
    },
  });
  const suggestion = suggestionFrom(view);

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <span className="small muted">
          <strong style={{ color: "var(--ink)" }}>{view.filename}</strong> · {bytes(view.bytes)} ·{" "}
          {plural(view.conversations.length, "chat")}
          {view.skipped > 0 && ` (${view.skipped} empty left out)`} · kept here until {dateLabel(view.expires_at)}
        </span>
        <span className="row" style={{ gap: 8 }}>
          <button type="button" className="btn small ghost" onClick={onBack}>
            Back
          </button>
          <button type="button" className="btn small danger" onClick={() => setDiscarding(true)}>
            Remove upload
          </button>
        </span>
      </div>
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <Card title="Pick chats" meta={`${selected.size} chosen`}>
          <div className="stack">
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <label className="field" style={{ flex: "1 1 200px" }}>
                <span className="sr-only">Search chat titles</span>
                <input type="search" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Search titles" />
              </label>
              {view.projects.length > 0 && (
                <label className="field">
                  <span className="sr-only">ChatGPT project</span>
                  <select value={project} onChange={(e) => setProject(e.target.value)}>
                    <option value="all">All chats</option>
                    <option value="none">Not in a project</option>
                    {view.projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {projectLabel[p.id]} ({plural(p.chats, "chat")})
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
            <div className="row small" style={{ gap: 8 }}>
              <button
                type="button"
                className="btn small ghost"
                onClick={() => setSelected((s) => new Set([...s, ...pickable.filter((c) => !c.saved).map((c) => c.key)]))}
              >
                Select shown ({pickable.filter((c) => !c.saved).length})
              </button>
              <button type="button" className="btn small ghost" onClick={() => setSelected(new Set())} disabled={!selected.size}>
                Clear
              </button>
            </div>
            {shown.length === 0 ? (
              <p className="small muted">No chat title matches.</p>
            ) : (
              <ul className="list chat-list" aria-label="Chats in the export">
                {shown.slice(0, 400).map((c) => (
                  <li key={c.key} className={selected.has(c.key) ? "row selected" : "row"} style={{ gap: 10 }}>
                    <input
                      type="checkbox"
                      checked={selected.has(c.key)}
                      onChange={() => toggle(c.key)}
                      disabled={c.too_large}
                      aria-label={`Choose ${c.title}`}
                    />
                    <span className="stack" style={{ gap: 2, minWidth: 0, flex: 1 }}>
                      <button type="button" className="linklike" onClick={() => setPreview(c)} style={{ textAlign: "left" }}>
                        {c.title}
                      </button>
                      <span className="tiny muted">
                        {c.updated ? dateLabel(c.updated) : "No date"} · {plural(c.messages, "message")}
                        {c.files > 0 && ` · ${plural(c.files, "file")}`}
                        {c.project && ` · ${projectLabel[c.project]}`}
                        {c.too_large && " · too large to save"}
                      </span>
                    </span>
                    {c.saved && (
                      <Link to={`/library/${c.saved.source_id}`} className="chip" title={`Saved in ${titles[c.saved.course_id] ?? "a course"}`}>
                        Saved
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {shown.length > 400 && <p className="tiny muted">Showing the 400 newest; search to find older chats.</p>}
          </div>
        </Card>
        <div className="stack" style={{ gap: 16 }}>
          <Card title="Save to a course">
            {active.length === 0 ? (
              <p className="small muted">Create a course first (under Courses), then come back.</p>
            ) : (
              <form
                className="stack"
                onSubmit={(e) => {
                  e.preventDefault();
                  save.mutate();
                }}
              >
                <label className="field">
                  Course
                  <select
                    value={course}
                    onChange={(e) => {
                      setCourseId(e.target.value);
                      setFolderId("");
                    }}
                  >
                    {active.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  In folder
                  <select value={folderId} onChange={(e) => setFolderId(e.target.value)}>
                    <option value="">Top level of the course</option>
                    {(folders.data ?? [])
                      .filter((f) => !f.hidden)
                      .map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.path}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="field">
                  New folder inside it (optional)
                  <input type="text" value={folderName} onChange={(e) => setFolderName(e.target.value)} maxLength={120} />
                </label>
                <label className="row small" style={{ gap: 8 }}>
                  <input type="checkbox" checked={withFiles} onChange={(e) => setWithFiles(e.target.checked)} />
                  Also save the files attached to these chats{files > 0 ? ` (${files})` : ""}
                </label>
                <button type="submit" className="btn primary" disabled={!selected.size || !course || save.isPending}>
                  {save.isPending ? "Saving…" : selected.size ? `Save ${plural(selected.size, "chat")}` : "Choose chats to save"}
                </button>
                {save.error && <ErrorNote error={save.error} />}
                {result && (
                  <div className="stack" style={{ gap: 6 }}>
                    <ImportSummary result={result} />
                    <Link to={`/library/course/${course}`} className="small">
                      Open {titles[course] ?? "the course"} in the library
                    </Link>
                    <span className="tiny muted">
                      Next: use the “Continue from ChatGPT” prompt (Guide) in that course's chat to go through them.
                    </span>
                  </div>
                )}
              </form>
            )}
          </Card>
          {suggestion && (
            <Card title="Found in your export">
              <div className="stack" style={{ gap: 10 }}>
                {view.instructions?.about_you && (
                  <div>
                    <div className="tiny muted">Custom instructions: about you</div>
                    <p className="small quote">{view.instructions.about_you}</p>
                  </div>
                )}
                {view.instructions?.how_to_respond && (
                  <div>
                    <div className="tiny muted">Custom instructions: how ChatGPT should respond</div>
                    <p className="small quote">{view.instructions.how_to_respond}</p>
                  </div>
                )}
                {view.memories.length > 0 && (
                  <details className="small">
                    <summary>{plural(view.memories.length, "memory", "memories")} ChatGPT saved</summary>
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {view.memories.map((m, i) => (
                        <li key={i}>{m}</li>
                      ))}
                    </ul>
                  </details>
                )}
                <p className="tiny muted" style={{ margin: 0 }}>
                  Nothing here is used until you add it to your study preferences below and save.
                </p>
              </div>
            </Card>
          )}
          <Card title="Study preferences">
            <PreferencesEditor suggestion={suggestion} />
          </Card>
        </div>
      </div>
      {preview && <Preview importId={view.id} chat={preview} onClose={() => setPreview(null)} />}
      <Confirm
        open={discarding}
        title="Remove this upload?"
        confirmLabel="Remove upload"
        danger
        busy={discard.isPending}
        onConfirm={() => discard.mutate()}
        onClose={() => setDiscarding(false)}
      >
        <p>
          The copy of {view.filename} is removed from RecallSpring. Chats you already saved stay in your library, and the
          export on your computer is not touched.
        </p>
        {discard.error && <ErrorNote error={discard.error} />}
      </Confirm>
    </div>
  );
}

export function ImportPage() {
  const [params, setParams] = useSearchParams();
  const open = params.get("chatgpt");
  return (
    <div className="page">
      <PageHead
        title="Move in"
        sub="Bring what you studied elsewhere into RecallSpring: chats from ChatGPT, folders and ZIPs of material, and how you like to study."
        crumbs={[{ to: "/library", label: "Library" }]}
      />
      {open ? (
        <ChatImportView id={open} onBack={() => setParams({})} />
      ) : (
        <div className="grid cols-2" style={{ alignItems: "start" }}>
          <Card title="Chats from ChatGPT">
            <ChatGptStart onOpen={(id) => setParams({ chatgpt: id })} />
          </Card>
          <div className="stack" style={{ gap: 16 }}>
            <Card title="A folder or ZIP of material">
              <p className="small muted" style={{ marginTop: 0 }}>
                Files from a ChatGPT project, a shared drive or your downloads: choose a folder or a ZIP and its
                folders become library folders of the course.
              </p>
              <Upload />
            </Card>
            <Card title="Study preferences">
              <PreferencesEditor />
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
