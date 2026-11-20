import { useState } from "react";
import { Link } from "react-router";
import { CopyButton } from "../components/Copy";
import { Card, PageHead } from "../components/ui";
import { GOOD_TO_KNOW, SEMESTER_TEMPLATE, STEPS, type GuidePrompt, type PromptLang } from "../guide";

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

function Prompt({ prompt, lang }: { prompt: GuidePrompt; lang: PromptLang }) {
  const text = prompt[lang];
  return (
    <li className="prompt">
      <div className="prompt-text">
        <WithPlaceholders text={text} />
        {prompt.note && <div className="tiny muted">{prompt.note}</div>}
      </div>
      <CopyButton text={text} />
    </li>
  );
}

export function GuidePage() {
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
        sub="How to study with Claude and RecallSpring: plan first, then learn, practise and review. Copy a prompt, replace the [brackets] and send it to Claude."
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
                <strong>Kibernetska varnost</strong> <span className="muted small">learning, practice and reviews for this course</span>
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
                <p className="small muted">{step.why}</p>
                <ul className="prompts">
                  {step.prompts.map((p) => (
                    <Prompt key={p.en} prompt={p} lang={lang} />
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
          {GOOD_TO_KNOW.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        <p className="tiny muted" style={{ marginTop: 10 }}>
          Claude answers in the language you write in; RecallSpring itself stays in English. See also <Link to="/settings">Settings</Link>.
        </p>
      </Card>
    </div>
  );
}
