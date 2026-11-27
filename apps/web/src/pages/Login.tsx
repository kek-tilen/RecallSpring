import { BrandMark } from "../components/BrandMark";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { get, request } from "../api";
import { ErrorNote, Loading } from "../components/ui";
import { autofillAvailable, browserError, getPasskey, localhostUrl, onIpAddress, passkeysSupported } from "../passkey";
import { keys } from "../queries";
import type { SessionInfo } from "../types";
import { FirstRunForm } from "./Welcome";

interface SetupStatus {
  needs_setup: boolean;
  refusal: "disabled" | "not_local" | null;
}

export function safeNext(next: string | null): string {
  // Only same-app paths; never an absolute or protocol-relative URL (browsers read "/\host" like "//host").
  return next && /^\/(?![/\\])/.test(next) && !next.startsWith("/login") ? next : "/";
}

export function LoginPage() {
  // A new install has no account yet: the first visit (on this computer) creates it instead of signing in.
  const setup = useQuery({ queryKey: ["auth-setup"], queryFn: () => get<SetupStatus>("/auth/setup"), retry: false, staleTime: 30_000 });
  if (setup.isPending) {
    return (
      <main className="login">
        <Loading />
      </main>
    );
  }
  if (setup.data?.needs_setup) {
    return <main className="login">{setup.data.refusal ? <SetupElsewhere refusal={setup.data.refusal} /> : <FirstRunForm />}</main>;
  }
  return <SignIn />;
}

interface PasskeyOptions {
  challenge_id: string;
  options: Record<string, unknown>;
}

/** The passkey button and, where the browser offers it, passkeys in the username field (autofill). */
function usePasskeySignIn(done: (s: SessionInfo) => void) {
  const where: "here" | "ip" | "none" = !passkeysSupported() ? "none" : onIpAddress() ? "ip" : "here";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [autofill, setAutofill] = useState(false);
  const pending = useRef<AbortController | null>(null);

  async function finish(opts: PasskeyOptions, credential: Record<string, unknown>) {
    done(await request<SessionInfo>("/auth/passkey/login", { method: "POST", json: { challenge_id: opts.challenge_id, credential } }));
  }

  useEffect(() => {
    if (where !== "here") return;
    let stopped = false;
    void (async () => {
      if (!(await autofillAvailable()) || stopped) return;
      setAutofill(true);
      try {
        const opts = await request<PasskeyOptions>("/auth/passkey/login/options", { method: "POST" });
        if (stopped) return;
        const ctrl = new AbortController();
        pending.current = ctrl;
        const credential = await getPasskey(opts.options, ctrl.signal);
        await finish(opts, credential);
      } catch (e) {
        // A cancelled autofill is silent; the button and the password stay.
        if (!stopped && !(e instanceof DOMException)) setError(browserError(e));
      }
    })();
    return () => {
      stopped = true;
      pending.current?.abort();
    };
  }, [where]);

  async function start() {
    pending.current?.abort(); // the browser allows one prompt at a time
    pending.current = null;
    setBusy(true);
    setError(null);
    try {
      const opts = await request<PasskeyOptions>("/auth/passkey/login/options", { method: "POST" });
      await finish(opts, await getPasskey(opts.options));
    } catch (e) {
      setError(browserError(e));
    } finally {
      setBusy(false);
    }
  }

  return { where, busy, error, autofill, start };
}

function SetupElsewhere({ refusal }: { refusal: "disabled" | "not_local" }) {
  return (
    <div className="card stack" role="status">
      <h1 style={{ fontSize: "1.3rem" }}>RecallSpring has no account yet</h1>
      {refusal === "not_local" ? (
        <p className="small">
          For safety, the first account can only be created on the computer RecallSpring runs on. Open{" "}
          <span className="mono">http://127.0.0.1:4318/</span> there.
        </p>
      ) : (
        <p className="small">
          Create the account on the server with <span className="mono">recallspring create-owner --username &lt;name&gt;</span>.
        </p>
      )}
    </div>
  );
}

function SignIn() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const signedIn = (session: SessionInfo) => {
    qc.setQueryData(keys.session, session);
    navigate(safeNext(params.get("next")), { replace: true });
  };
  const login = useMutation({
    mutationFn: () => request<SessionInfo>("/auth/login", { method: "POST", json: { username, password } }),
    onSuccess: signedIn,
  });
  const passkey = usePasskeySignIn(signedIn);

  function submit(e: FormEvent) {
    e.preventDefault();
    login.mutate();
  }

  return (
    <main className="login">
      <form className="card" onSubmit={submit} aria-labelledby="login-title">
        <div className="row" style={{ gap: 12 }}>
          <BrandMark size={36} />
          <div>
            <h1 id="login-title" style={{ fontSize: "1.3rem" }}>
              RecallSpring
            </h1>
            <p className="muted small">Sign in to your study records.</p>
          </div>
        </div>
        <label className="field">
          Username
          <input type="text" autoComplete={passkey.autofill ? "username webauthn" : "username"} value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
        </label>
        <label className="field">
          Password
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {login.error && <ErrorNote error={login.error} />}
        <button type="submit" className="btn primary" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </button>
        {passkey.where === "here" && (
          <>
            <div className="or-line" aria-hidden="true">
              or
            </div>
            <button type="button" className="btn" onClick={() => passkey.start()} disabled={passkey.busy}>
              {passkey.busy ? "Waiting for the passkey…" : "Sign in with a passkey"}
            </button>
            {passkey.error && <ErrorNote error={passkey.error} />}
          </>
        )}
        {passkey.where === "ip" && (
          <p className="notice small" style={{ margin: 0 }}>
            Passkeys work at <span className="mono">localhost{window.location.port ? `:${window.location.port}` : ""}</span>, not at{" "}
            {window.location.hostname}. <a href={localhostUrl()}>Open there</a>
          </p>
        )}
        <p className="muted tiny">This sign-in is RecallSpring's own. It is separate from any AI assistant or provider.</p>
      </form>
    </main>
  );
}
