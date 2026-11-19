import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { request } from "../api";
import { ErrorNote } from "../components/ui";
import { keys } from "../queries";
import type { SessionInfo } from "../types";

export function safeNext(next: string | null): string {
  // Only same-app paths; never an absolute or protocol-relative URL (browsers read "/\host" like "//host").
  return next && /^\/(?![/\\])/.test(next) && !next.startsWith("/login") ? next : "/";
}

export function LoginPage() {
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
          <img src="/favicon.svg" alt="" width={36} height={36} />
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
        <p className="muted tiny">This sign-in is RecallSpring's own. It is separate from Claude and any AI provider.</p>
      </form>
    </main>
  );
}
