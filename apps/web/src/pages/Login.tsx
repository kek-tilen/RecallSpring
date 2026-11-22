import { BrandMark } from "../components/BrandMark";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { get, request } from "../api";
import { ErrorNote, Loading } from "../components/ui";
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
  const login = useMutation({
    mutationFn: () => request<SessionInfo>("/auth/login", { method: "POST", json: { username, password } }),
    onSuccess: (session) => {
      qc.setQueryData(keys.session, session);
      navigate(safeNext(params.get("next")), { replace: true });
    },
  });

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
          <input type="text" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
        </label>
        <label className="field">
          Password
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {login.error && <ErrorNote error={login.error} />}
        <button type="submit" className="btn primary" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </button>
        <p className="muted tiny">This sign-in is RecallSpring's own. It is separate from any AI assistant or provider.</p>
      </form>
    </main>
  );
}
