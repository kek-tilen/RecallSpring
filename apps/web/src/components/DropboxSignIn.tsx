import { useState } from "react";
import { dateTime } from "../format";
import type { DropboxPending } from "../types";
import { ErrorNote } from "./ui";

/** Sign in to Dropbox (2026-11-28): Dropbox has no code to type on another device, so RecallSpring opens Dropbox,
 * the learner allows it, and Dropbox shows a code to paste back here. The verifier never reaches the browser. */
export function DropboxSignIn({
  pending,
  what,
  busy,
  error,
  expired,
  onCode,
  onRestart,
  onCancel,
}: {
  pending: DropboxPending | null;
  /** What RecallSpring will put there, e.g. "your encrypted backups". */
  what: string;
  busy: boolean;
  error: unknown;
  expired: boolean;
  onCode: (code: string) => void;
  onRestart: () => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");
  const ready = code.trim().length >= 8;
  return (
    <section className="assistant-steps stack" style={{ gap: 10 }} aria-labelledby="dropbox-h">
      <h4 id="dropbox-h" className="backup-key-title">
        Sign in to Dropbox
      </h4>
      {pending && !expired ? (
        <>
          <ol className="small" style={{ margin: 0, paddingLeft: "1.2rem" }}>
            <li>
              <a className="btn primary small" href={pending.authorize_url} target="_blank" rel="noreferrer">
                Open Dropbox
              </a>{" "}
              and allow RecallSpring.
            </li>
            <li>Dropbox shows a code. Paste it here:</li>
          </ol>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              if (ready) onCode(code.trim());
            }}
          >
            <input
              type="text"
              aria-label="Code from Dropbox"
              autoComplete="off"
              spellCheck={false}
              maxLength={200}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              style={{ flex: "1 1 16rem", minWidth: 0 }}
            />
            <button type="submit" className="btn primary small" disabled={!ready || busy}>
              {busy ? "Connecting…" : "Connect"}
            </button>
          </form>
          <ul className="folder-checks">
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>Dropbox will ask to let RecallSpring use only its own folder, Apps › RecallSpring, for {what}</span>
            </li>
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>No account details: not your name, email or what else is in your Dropbox</span>
            </li>
          </ul>
          <p className="tiny muted" style={{ margin: 0 }}>
            Paste the code before {dateTime(pending.expires_at)}. It works once.
          </p>
          {error != null && <ErrorNote error={error} />}
          <div className="row">
            <button type="button" className="btn small" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="small" role="alert" style={{ margin: 0 }}>
            This sign-in expired before a code was pasted. Nothing was connected.
          </p>
          <div className="row">
            <button type="button" className="btn primary small" onClick={onRestart} disabled={busy}>
              Start again
            </button>
            <button type="button" className="btn small" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </>
      )}
    </section>
  );
}
