import { dateTime } from "../format";
import type { CloudDevice, CloudProvider } from "../types";
import { CopyButton } from "./Copy";
import { ErrorNote } from "./ui";

/** Pieces shared by Cloud copy and Your cloud folder (2026-11-28): the code sign-in of Google and Microsoft, and the
 * note on which server setting a provider needs. */

export type DeviceProvider = "google" | "onedrive";
export type DeviceOutcome = "denied" | "expired" | "blocked" | "not_supported";

export const COMPANY: Record<CloudProvider, string> = { google: "Google", dropbox: "Dropbox", onedrive: "Microsoft", folder: "the sync app" };

const OTHERS = "Use a personal Microsoft account, Google Drive or Dropbox.";

function outcomeText(provider: DeviceProvider, outcome: DeviceOutcome | null): string {
  if (outcome === "blocked") return `Your school or work account does not allow this kind of sign-in. Nothing was connected. ${OTHERS}`;
  if (outcome === "not_supported")
    return `This school or work account does not let RecallSpring use its own folder in OneDrive. Nothing was connected. ${OTHERS}`;
  if (outcome === "denied")
    return provider === "onedrive"
      ? "Microsoft did not allow RecallSpring. Nothing was connected. A school or work account may need its administrator to allow RecallSpring first."
      : "Google did not allow RecallSpring. Nothing was connected.";
  return "The code expired before the sign-in finished.";
}

/** The code to type at google.com/device or microsoft.com/devicelogin; the page polls by itself (the caller does). */
export function DeviceSignIn({
  id,
  provider,
  device,
  outcome,
  what,
  busy,
  error,
  onRestart,
  onCancel,
}: {
  id: string;
  provider: DeviceProvider;
  device: CloudDevice | null;
  outcome: DeviceOutcome | null;
  /** What RecallSpring will put there, e.g. "your encrypted backups". */
  what: string;
  busy: boolean;
  error: unknown;
  onRestart: () => void;
  onCancel: () => void;
}) {
  const company = COMPANY[provider];
  return (
    <section className="assistant-steps stack" style={{ gap: 10 }} aria-labelledby={id}>
      <h4 id={id} className="backup-key-title">
        Sign in to {company}
      </h4>
      {device ? (
        <>
          <p className="small" style={{ margin: 0 }}>
            On any device, open{" "}
            <a href={device.verification_url} target="_blank" rel="noreferrer">
              {device.verification_url.replace(/^https?:\/\/(www\.)?/, "")}
            </a>
            , sign in with your own account and enter:
          </p>
          <code className="recovery-key cloud-code" aria-label={`Code to enter at ${company}`}>
            {device.user_code}
          </code>
          <ul className="folder-checks">
            <li data-level="ok">
              <span aria-hidden="true">✓</span>
              <span>
                {provider === "onedrive"
                  ? `Microsoft will ask to let RecallSpring use only its own folder, Apps › RecallSpring, for ${what}`
                  : `Google will ask to let RecallSpring use only files it creates, for ${what}`}
              </span>
            </li>
            {provider === "onedrive" && (
              <li data-level="ok">
                <span aria-hidden="true">✓</span>
                <span>A personal account works; a school or work account works when its organisation allows it</span>
              </li>
            )}
          </ul>
          <p className="tiny muted" style={{ margin: 0 }}>
            The code expires at {dateTime(device.expires_at)}. This page continues by itself when you are done.
          </p>
          <div className="row">
            <CopyButton text={device.user_code} label="Copy code" />
            <button type="button" className="btn small" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="small" role="alert" style={{ margin: 0 }}>
            {outcomeText(provider, outcome)}
          </p>
          <div className="row">
            <button type="button" className="btn primary small" onClick={onRestart} disabled={busy}>
              Get a new code
            </button>
            <button type="button" className="btn small" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </>
      )}
      {error != null && <ErrorNote error={error} />}
    </section>
  );
}

type SignInProvider = Exclude<CloudProvider, "folder">;

const SETTING: Record<SignInProvider, React.ReactNode> = {
  google: (
    <>
      <code>RS_CLOUD_GOOGLE_CLIENT_ID</code> and <code>RS_CLOUD_GOOGLE_CLIENT_SECRET</code> for Google Drive
    </>
  ),
  dropbox: (
    <>
      <code>RS_CLOUD_DROPBOX_APP_KEY</code> for Dropbox
    </>
  ),
  onedrive: (
    <>
      <code>RS_CLOUD_ONEDRIVE_CLIENT_ID</code> for OneDrive
    </>
  ),
};

/** "Whoever runs this RecallSpring sets …" for each provider without its app setting; nothing when all are set. A
 * synced folder needs no app setting. */
export function MissingSettings({ available, where }: { available: Record<CloudProvider, boolean>; where: string }) {
  const missing = (Object.keys(SETTING) as SignInProvider[]).filter((p) => !available[p]);
  if (missing.length === 0) return null;
  const none = missing.length === Object.keys(SETTING).length;
  return (
    <p className="tiny muted" style={{ margin: 0 }}>
      {none ? "Not available yet: whoever" : "Whoever"} runs this RecallSpring sets{" "}
      {missing.map((p, i) => (
        <span key={p}>
          {i > 0 && (i === missing.length - 1 ? " and " : ", ")}
          {SETTING[p]}
        </span>
      ))}{" "}
      ({where}).
    </p>
  );
}

/** The disconnect legend: Google and Dropbox are asked to withdraw the sign-in; Microsoft has no call for it; a synced
 * folder has no sign-in. */
export function withdrawText(provider: CloudProvider): string {
  if (provider === "folder") return "Disconnect: RecallSpring stops copying into the folder";
  return provider === "onedrive"
    ? "Disconnect: RecallSpring forgets the sign-in (you can also remove RecallSpring in your Microsoft account)"
    : `Disconnect: RecallSpring forgets the sign-in and asks ${COMPANY[provider]} to withdraw it`;
}
