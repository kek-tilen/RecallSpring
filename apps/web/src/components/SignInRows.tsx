import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { get, request } from "../api";
import { dateLabel, plural, relativeDay } from "../format";
import { browserError, createPasskey, getPasskey, passkeyAddress, passkeysSupported } from "../passkey";
import { useSession } from "../queries";
import type { PasskeyItem, SignInView } from "../types";
import { ErrorNote } from "./ui";

const KEY = ["sign-in"] as const;
type Step = null | "password" | "manage";
type Pending = { kind: "add" } | { kind: "remove"; passkey: PasskeyItem };

interface Options {
  challenge_id: string;
  options: Record<string, unknown>;
}

function confirmedNow(v: SignInView | undefined): boolean {
  return !!v?.confirmed_until && Date.parse(v.confirmed_until) - Date.now() > 10_000;
}

function lastUsed(p: PasskeyItem): string {
  return p.last_used_at ? `last used ${relativeDay(p.last_used_at)}` : "not used yet";
}

function passkeySummary(v: SignInView, supported: boolean): string {
  if (v.passkeys.length === 0) {
    return supported ? "None yet · sign in with one tap instead of the password" : "This browser does not support passkeys";
  }
  const used = v.passkeys.filter((p) => p.last_used_at).sort((a, b) => (b.last_used_at ?? "").localeCompare(a.last_used_at ?? ""))[0];
  const tail = used ? ` · last used ${relativeDay(used.last_used_at!)} on ${used.address}` : "";
  return `${plural(v.passkeys.length, "passkey")}${tail}`;
}

export function SignInRows() {
  const view = useQuery({ queryKey: KEY, queryFn: () => get<SignInView>("/auth/passkeys") });
  const [step, setStep] = useState<Step>(null);
  const v = view.data;
  const supported = passkeysSupported();
  return (
    <div className="settings-rows sign-in-rows">
      <div>
        <div className="settings-row">
          <span>
            <h3 className="settings-row-title">Password</h3>
            <span className="small muted">
              {v ? `${v.password_changed ? "Changed" : "Set"} ${dateLabel(v.password_changed_at)} · the fallback when a passkey is not at hand` : "…"}
            </span>
          </span>
          <button type="button" className="btn small" aria-expanded={step === "password"} onClick={() => setStep(step === "password" ? null : "password")}>
            {step === "password" ? "Close" : "Change"}
          </button>
        </div>
        {step === "password" && <ChangePassword onDone={() => setStep(null)} />}
      </div>
      <div id="passkeys">
        <div className="settings-row">
          <span>
            <h3 className="settings-row-title">Passkeys</h3>
            <span className="small muted">{v ? passkeySummary(v, supported) : view.error ? "Could not load." : "…"}</span>
          </span>
          {v && (supported || v.passkeys.length > 0) && (
            <button type="button" className="btn small" aria-expanded={step === "manage"} onClick={() => setStep(step === "manage" ? null : "manage")}>
              {step === "manage" ? "Close" : v.passkeys.length ? "Manage" : "Add a passkey"}
            </button>
          )}
        </div>
        {step === "manage" && v && <ManagePasskeys v={v} startAdding={v.passkeys.length === 0} />}
      </div>
      <SignOutRow />
    </div>
  );
}

function SignOutRow() {
  const session = useSession();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const logout = useMutation({
    mutationFn: () => request<void>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      qc.clear();
      navigate("/login", { replace: true });
    },
  });
  return (
    <div className="settings-row">
      <span>
        <h3 className="settings-row-title">Sign out</h3>
        <span className="small muted">Signed in as {session.data?.user.username} on this browser</span>
      </span>
      <button type="button" className="btn small" onClick={() => logout.mutate()} disabled={logout.isPending}>
        Sign out
      </button>
    </div>
  );
}

function ChangePassword({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [local, setLocal] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: () => request<SignInView>("/auth/password", { method: "POST", json: { current_password: current, new_password: next } }),
    onSuccess: (v) => {
      qc.setQueryData(KEY, v);
      setSaved(true);
      setCurrent("");
      setNext("");
      setAgain("");
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (next.length < 12) return setLocal("The new password needs at least 12 characters.");
    if (next !== again) return setLocal("The new passwords do not match.");
    setLocal(null);
    save.mutate();
  }
  if (saved) {
    return (
      <div className="assistant-steps stack" style={{ gap: 8 }} role="status">
        <p className="small" style={{ margin: 0 }}>
          Password changed. Other browsers and devices are signed out; this one stays signed in.
        </p>
        <div className="row">
          <button type="button" className="btn small" onClick={onDone}>
            Done
          </button>
        </div>
      </div>
    );
  }
  return (
    <form className="assistant-steps stack" style={{ gap: 10 }} onSubmit={submit} aria-label="Change password">
      <label className="field">
        Current password
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </label>
      <label className="field">
        New password
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} minLength={12} required />
      </label>
      <label className="field">
        New password again
        <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
      </label>
      <p className="tiny muted" style={{ margin: 0 }}>
        At least 12 characters. Saving signs out every other browser and device. Passkeys and assistant connections keep working.
      </p>
      {local && (
        <div className="notice bad" role="alert">
          {local}
        </div>
      )}
      {save.error && <ErrorNote error={save.error} />}
      <div className="row">
        <button type="submit" className="btn primary small" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save password"}
        </button>
        <button type="button" className="btn small" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ManagePasskeys({ v, startAdding }: { v: SignInView; startAdding: boolean }) {
  const qc = useQueryClient();
  const here = passkeyAddress(v.remote_host);
  const canAdd = passkeysSupported() && here;
  const [pending, setPending] = useState<Pending | null>(null);
  const [needConfirm, setNeedConfirm] = useState(false);
  const [added, setAdded] = useState<PasskeyItem | null>(null);
  const [removing, setRemoving] = useState<PasskeyItem | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const setView = (next: SignInView) => qc.setQueryData(KEY, next);

  async function run(action: Pending) {
    setError(null);
    if (!confirmedNow(qc.getQueryData<SignInView>(KEY))) {
      setPending(action);
      setNeedConfirm(true);
      return;
    }
    setBusy(true);
    try {
      if (action.kind === "add") {
        const opts = await request<Options>("/auth/passkeys/options", { method: "POST" });
        let credential: Record<string, unknown>;
        try {
          credential = await createPasskey(opts.options);
        } catch (e) {
          throw browserError(e);
        }
        const res = await request<{ passkey: PasskeyItem; sign_in: SignInView }>("/auth/passkeys", {
          method: "POST",
          json: { challenge_id: opts.challenge_id, credential },
        });
        setView(res.sign_in);
        setAdded(res.passkey);
      } else {
        setView(await request<SignInView>(`/auth/passkeys/${action.passkey.id}`, { method: "DELETE" }));
        setRemoving(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Something went wrong."));
    } finally {
      setBusy(false);
    }
  }

  // "Add a passkey" on the row (no passkeys yet) goes straight to adding one.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (startAdding && canAdd && !autoStarted.current) {
      autoStarted.current = true;
      void run({ kind: "add" });
    }
  });

  if (needConfirm && pending) {
    return (
      <ConfirmItIsYou
        v={v}
        onCancel={() => {
          setNeedConfirm(false);
          setPending(null);
        }}
        onConfirmed={(next) => {
          setView(next);
          setNeedConfirm(false);
          const action = pending;
          setPending(null);
          void run(action);
        }}
      />
    );
  }

  if (added) return <PasskeyAdded passkey={added} onDone={() => setAdded(null)} />;

  return (
    <div className="assistant-steps stack" style={{ gap: 10 }}>
      {v.passkeys.length > 0 && (
        <ul className="passkey-list" aria-label="Your passkeys">
          {v.passkeys.map((p) => (
            <li key={p.id}>
              {renaming === p.id ? (
                <RenameForm passkey={p} onDone={() => setRenaming(null)} />
              ) : (
                <div className="settings-row">
                  <span>
                    <span className="small">
                      <b style={{ fontWeight: 500 }}>{p.name}</b> <span className="chip">{p.address}</span>
                    </span>
                    <span className="tiny muted">
                      Added {dateLabel(p.created_at)} · {lastUsed(p)} · {p.synced ? "synced by your password manager" : "only on this device"}
                    </span>
                  </span>
                  <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                    <button type="button" className="btn small" onClick={() => setRenaming(p.id)} aria-label={`Rename ${p.name}`}>
                      Rename
                    </button>
                    <button type="button" className="btn small" onClick={() => setRemoving(p)} aria-label={`Remove ${p.name}`}>
                      Remove
                    </button>
                  </span>
                </div>
              )}
              {removing?.id === p.id && (
                <div className="notice small stack" style={{ gap: 8, marginTop: 6 }} role="alertdialog" aria-label="Remove passkey">
                  <span>
                    Remove the passkey {p.name}? You can no longer sign in with it
                    {v.passkeys.length === 1 ? "; the password still works." : "."}
                  </span>
                  <span className="row">
                    <button type="button" className="btn small danger" disabled={busy} onClick={() => void run({ kind: "remove", passkey: p })}>
                      Remove
                    </button>
                    <button type="button" className="btn small" onClick={() => setRemoving(null)}>
                      Keep it
                    </button>
                  </span>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {busy && pending === null && !removing && (
        <p className="small" role="status" style={{ margin: 0 }}>
          Your browser or phone now asks where to keep the passkey: this device, a phone, or a password manager.
        </p>
      )}
      {error && <ErrorNote error={error} />}
      {canAdd ? (
        <div className="row">
          <button type="button" className="btn primary small" disabled={busy} onClick={() => void run({ kind: "add" })}>
            Add a passkey
          </button>
        </div>
      ) : (
        <p className="small muted" style={{ margin: 0 }}>
          {passkeysSupported()
            ? `Passkeys can be added at localhost${v.remote_host ? ` or ${v.remote_host}` : ""}, not at this address.`
            : "This browser does not support passkeys."}
        </p>
      )}
      <p className="tiny muted" style={{ margin: 0 }}>
        A passkey works only at the address where it was added. To sign in at both, add one at each.
      </p>
    </div>
  );
}

function ConfirmItIsYou({ v, onCancel, onConfirmed }: { v: SignInView; onCancel: () => void; onConfirmed: (v: SignInView) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const host = window.location.hostname.toLowerCase();
  const passkeyHere = passkeysSupported() && v.passkeys.some((p) => p.address === host);

  async function attempt(fn: () => Promise<SignInView>) {
    setBusy(true);
    setError(null);
    try {
      onConfirmed(await fn());
    } catch (e) {
      setError(browserError(e));
    } finally {
      setBusy(false);
    }
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    void attempt(() => request<SignInView>("/auth/confirm", { method: "POST", json: { password } }));
  }
  return (
    <form className="assistant-steps stack" style={{ gap: 10 }} onSubmit={submit} aria-labelledby="confirm-h">
      <h4 id="confirm-h" className="backup-key-title">
        Confirm it is you
      </h4>
      <p className="small" style={{ margin: 0 }}>
        Before a passkey is added or removed. Good for 5 minutes.
      </p>
      <label className="field">
        Password
        <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
      </label>
      {error && <ErrorNote error={error} />}
      <div className="row">
        <button type="submit" className="btn primary small" disabled={busy}>
          Continue
        </button>
        {passkeyHere && (
          <button
            type="button"
            className="btn small"
            disabled={busy}
            onClick={() =>
              void attempt(async () => {
                const opts = await request<Options>("/auth/confirm/passkey/options", { method: "POST" });
                const credential = await getPasskey(opts.options);
                return request<SignInView>("/auth/confirm/passkey", { method: "POST", json: { challenge_id: opts.challenge_id, credential } });
              })
            }
          >
            Use a passkey instead
          </button>
        )}
        <button type="button" className="btn small" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function PasskeyAdded({ passkey, onDone }: { passkey: PasskeyItem; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(passkey.name);
  const rename = useMutation({
    mutationFn: () => request<SignInView>(`/auth/passkeys/${passkey.id}`, { method: "PATCH", json: { name } }),
    onSuccess: (v) => {
      qc.setQueryData(KEY, v);
      onDone();
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim() && name.trim() !== passkey.name) rename.mutate();
    else onDone();
  }
  return (
    <form className="assistant-steps stack" style={{ gap: 10 }} onSubmit={submit} aria-labelledby="added-h">
      <h4 id="added-h" className="backup-key-title">
        Passkey added
      </h4>
      <ul className="folder-checks">
        <li data-level="ok">
          <span aria-hidden="true">✓</span>
          <span>Works at {passkey.address}</span>
        </li>
        <li data-level="ok">
          <span aria-hidden="true">✓</span>
          <span>{passkey.synced ? "Synced by your password manager" : "Only on this device (not synced)"}</span>
        </li>
      </ul>
      <label className="field">
        Name
        <input type="text" value={name} maxLength={64} onChange={(e) => setName(e.target.value)} />
      </label>
      <p className="tiny muted" style={{ margin: 0 }}>
        A name only you see, to tell your passkeys apart.
      </p>
      {rename.error && <ErrorNote error={rename.error} />}
      <div className="row">
        <button type="submit" className="btn primary small" disabled={rename.isPending}>
          Done
        </button>
      </div>
    </form>
  );
}

function RenameForm({ passkey, onDone }: { passkey: PasskeyItem; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(passkey.name);
  const rename = useMutation({
    mutationFn: () => request<SignInView>(`/auth/passkeys/${passkey.id}`, { method: "PATCH", json: { name } }),
    onSuccess: (v) => {
      qc.setQueryData(KEY, v);
      onDone();
    },
  });
  return (
    <form
      className="row"
      style={{ gap: 6 }}
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) rename.mutate();
      }}
    >
      <label className="sr-only" htmlFor={`rename-${passkey.id}`}>
        New name for {passkey.name}
      </label>
      <input id={`rename-${passkey.id}`} type="text" value={name} maxLength={64} onChange={(e) => setName(e.target.value)} autoFocus />
      <button type="submit" className="btn small primary" disabled={rename.isPending}>
        Save
      </button>
      <button type="button" className="btn small" onClick={onDone}>
        Cancel
      </button>
      {rename.error && <ErrorNote error={rename.error} />}
    </form>
  );
}
