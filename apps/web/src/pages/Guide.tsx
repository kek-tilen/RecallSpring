import { useState } from "react";
import { Link } from "react-router";
import { CopyButton } from "../components/Copy";
import { Card, PageHead } from "../components/ui";
import { useAssistant, type AssistantWords } from "../assistant";
import { fill, GOOD_TO_KNOW, SEMESTER_TEMPLATE, STEPS, type GuidePrompt, type PromptLang } from "../guide";

function readLang(): PromptLang {
  try {
    return localStorage.getItem("rs-prompt-lang") === "sl" ? "sl" : "en";
  } catch {
    return "en";
  }
}

/** Placeholders in [brackets] are highlighted so it is clear what to replace. Rendered as text only. */
function WithPlaceholders({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\[[^\]]+\])/g).map((part, i) =>
        part.startsWith("[") && part.endsWith("]") ? (
          <span key={i} className="ph">
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

function Prompt({ prompt, lang, a }: { prompt: GuidePrompt; lang: PromptLang; a: AssistantWords }) {
  const text = prompt[lang];
  return (
    <li className="prompt">
      <div className="prompt-text">
        <WithPlaceholders text={text} />
        {prompt.note && <div className="tiny muted">{fill(prompt.note, a)}</div>}
      </div>
      <CopyButton text={text} />
    </li>
  );
}

function ClaudeSetup() {
  return (
    <Card title="Set up Claude once">
      <div className="stack">
        <p className="small">
          Use one Claude Project per semester. Paste the instructions below into the project, turn on the RecallSpring connector
          in its chats, then give each chat one job. All chats share the same RecallSpring records, so nothing is copied twice.
        </p>
        <div className="structure" aria-label="Example project structure">
          <div className="structure-project">Project · 5th semester</div>
          <ul>
            <li>
              <strong>Planning chat</strong> <span className="muted small">all courses: dates, scope, material, exam type, priorities</span>
            </li>
            <li>
              <strong>[course]</strong> <span className="muted small">learning, practice and reviews for this course</span>
            </li>
            <li>
              <strong>[next course]</strong> <span className="muted small">one chat per course</span>
            </li>
          </ul>
        </div>
        <details>
          <summary className="small" style={{ cursor: "pointer", fontWeight: 600 }}>
            Project instructions to paste into Claude
          </summary>
          <div className="stack" style={{ marginTop: 10 }}>
            <pre className="template">{SEMESTER_TEMPLATE}</pre>
            <div>
              <CopyButton text={SEMESTER_TEMPLATE} label="Copy instructions" />
            </div>
            <p className="tiny muted">
              Prefer one project per course? That works too: templates for course projects and an Overview project are in
              docs/claude-projects.md.
            </p>
          </div>
        </details>
      </div>
    </Card>
  );
}

function SetupCard({ a }: { a: AssistantWords }) {
  switch (a.key) {
    case "claude":
      return <ClaudeSetup />;
    case "codex":
      return (
        <Card title="Set up Codex once">
          <div className="stack">
            <p className="small">
              The Codex setup (<Link to="/welcome">setup steps</Link>) makes <span className="mono">Documents\RecallSpring Study</span>{" "}
              with one folder per job. Open a folder in Codex and start a session there; all folders share the same RecallSpring
              records, so nothing is copied twice.
            </p>
            <div className="structure" aria-label="Example folder structure">
              <div className="structure-project">RecallSpring Study</div>
              <ul>
                <li>
                  <strong>Planning</strong> <span className="muted small">all courses: dates, scope, material, exam type, priorities</span>
                </li>
                <li>
                  <strong>[course]</strong> <span className="muted small">learning, practice and reviews for this course</span>
                </li>
              </ul>
            </div>
            <p className="tiny muted">A new course gets its folder when you run the setup again.</p>
          </div>
        </Card>
      );
    case "chatgpt":
      return (
        <Card title="Study in Chat">
          <div className="stack">
            <p className="small">
              Sign in under <Link to="/settings#chatgpt">Settings → ChatGPT</Link> and add your material under{" "}
              <Link to="/library">Library</Link>. In <Link to="/chat">Chat</Link>, each new conversation has one job, chosen under{" "}
              <strong>Study</strong>:
            </p>
            <div className="structure" aria-label="Kinds of Chat conversations">
              <div className="structure-project">Chat</div>
              <ul>
                <li>
                  <strong>Planning (all courses)</strong> <span className="muted small">courses, dates, scope, material, old papers, priorities</span>
                </li>
                <li>
                  <strong>[course]</strong> <span className="muted small">learning, practice and reviews; one conversation is one study session</span>
                </li>
              </ul>
            </div>
          </div>
        </Card>
      );
    default:
      return (
        <Card title="Choose your assistant first">
          <p className="small" style={{ margin: 0 }}>
            The steps below work with Claude, Codex or ChatGPT in RecallSpring. <Link to="/welcome">Choose yours</Link> to see how
            to set it up.
          </p>
        </Card>
      );
  }
}

export function GuidePage() {
  const a = useAssistant();
  const [lang, setLang] = useState<PromptLang>(readLang);
  function pick(next: PromptLang) {
    setLang(next);
    try {
      localStorage.setItem("rs-prompt-lang", next);
    } catch {
      /* the choice lasts for this page only */
    }
  }

  return (
    <div className="page">
      <PageHead
        title="Guide"
        sub={`How to study with ${a.name} and RecallSpring: plan first, then learn, practise and review. Copy a prompt, replace the [brackets] and send it to ${a.name}.`}
      >
        <div className="row" role="radiogroup" aria-label="Prompt language">
          <span className="small muted">Prompts in</span>
          {(
            [
              ["en", "English"],
              ["sl", "Slovenščina"],
            ] as const
          ).map(([id, label]) => (
            <button key={id} type="button" role="radio" aria-checked={lang === id} aria-pressed={lang === id} className="chip chip-filter" onClick={() => pick(id)}>
              {label}
            </button>
          ))}
        </div>
      </PageHead>

      <SetupCard a={a} />

      <ol className="steps">
        {STEPS.map((step, i) => (
          <li key={step.id}>
            <Card
              title={
                <span className="row" style={{ gap: 10 }}>
                  <span className="step-num" aria-hidden="true">
                    {i + 1}
                  </span>
                  {step.title}
                </span>
              }
              action={<span className="chip">{step.where}</span>}
            >
              <div className="stack">
                <p className="small muted">{fill(step.why, a)}</p>
                {step.claudeTip && a.key === "claude" && <p className="small muted">{step.claudeTip}</p>}
                {step.planning && a.key === "chatgpt" && (
                  <p className="small muted" style={{ margin: 0 }}>
                    In Chat: a new conversation with <strong>Planning (all courses)</strong> picked under Study.
                  </p>
                )}
                <ul className="prompts">
                  {step.prompts.map((p) => (
                    <Prompt key={p.en} prompt={p} lang={lang} a={a} />
                  ))}
                </ul>
                {step.check && <p className="tiny muted">Check it here: {step.check}</p>}
              </div>
            </Card>
          </li>
        ))}
      </ol>

      <Card title="Good to know" tint>
        <ul className="list small">
          {GOOD_TO_KNOW.filter((f) => !f.only || !a.key || f.only.includes(a.key)).map((f) => (
            <li key={f.text}>{fill(f.text, a)}</li>
          ))}
        </ul>
        <p className="tiny muted" style={{ marginTop: 10 }}>
          {a.Name} answers in the language you write in; RecallSpring itself stays in English. See also <Link to="/settings">Settings</Link>.
        </p>
      </Card>
    </div>
  );
}
