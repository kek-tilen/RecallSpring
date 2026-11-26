import { BrandMark } from "./BrandMark";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { request } from "../api";
import { useDashboard, useSession } from "../queries";
import { FocusPill, PomodoroProvider } from "./Pomodoro";

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/courses", label: "Courses" },
  { to: "/exams", label: "Exams" },
  { to: "/review", label: "Review" },
  { to: "/simulations", label: "Simulations" },
  { to: "/library", label: "Library" },
  { to: "/notes", label: "Notes" },
  { to: "/chat", label: "Chat" },
  { to: "/focus", label: "Focus" },
  { to: "/history", label: "History" },
  { to: "/guide", label: "Guide" },
  { to: "/settings", label: "Settings" },
];

const RAIL_KEY = "rs-rail";

function railHidden(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "hidden";
  } catch {
    return false;
  }
}

function MenuIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
      <rect x="2" y="2.5" width="14" height="13" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <line x1="7" y1="3" x2="7" y2="15" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

export function Layout() {
  const session = useSession();
  const dashboard = useDashboard();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [hidden, setHidden] = useState(railHidden);
  const showButton = useRef<HTMLButtonElement>(null);
  const hideButton = useRef<HTMLButtonElement>(null);
  const moved = useRef(false);
  const logout = useMutation({
    mutationFn: () => request<void>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      qc.clear();
      navigate("/login", { replace: true });
    },
  });
  const due = dashboard.data?.plan.items.filter((i) => i.category === "Review due" || i.category === "Relearn").length ?? 0;

  function toggle(next: boolean) {
    moved.current = true;
    setHidden(next);
    try {
      if (next) localStorage.setItem(RAIL_KEY, "hidden");
      else localStorage.removeItem(RAIL_KEY);
    } catch {
      /* not remembered in a private window */
    }
  }

  useEffect(() => {
    // Keep keyboard focus on the button that brings the menu back (or hides it again).
    if (!moved.current) return;
    moved.current = false;
    (hidden ? showButton : hideButton).current?.focus();
  }, [hidden]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key === "\\") {
        e.preventDefault();
        toggle(!hidden);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <PomodoroProvider>
      <div className={hidden ? "shell rail-hidden" : "shell"}>
        {hidden && <FocusPill floating />}
        {hidden && (
          <button
            ref={showButton}
            type="button"
            className="btn small ghost rail-show"
            aria-expanded={false}
            aria-controls="rail"
            aria-label="Show menu"
            title="Show menu (Ctrl+\)"
            onClick={() => toggle(false)}
          >
            <MenuIcon />
          </button>
        )}
        <aside className="rail" id="rail">
          <div className="rail-top">
            <NavLink to="/" className="brand" aria-label="RecallSpring home">
              <BrandMark />
              RecallSpring
            </NavLink>
            <button
              ref={hideButton}
              type="button"
              className="btn small ghost rail-hide"
              aria-expanded={true}
              aria-controls="rail"
              aria-label="Hide menu"
              title="Hide menu (Ctrl+\)"
              onClick={() => toggle(true)}
            >
              <MenuIcon />
            </button>
          </div>
          {!hidden && <FocusPill />}
          <nav aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}>
                {n.label}
                {n.to === "/review" && due > 0 && (
                  <span className="count" aria-label={`${due} due`}>
                    {due}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="rail-foot">
            <span>Signed in as {session.data?.user.username}</span>
            <button type="button" className="btn small" onClick={() => logout.mutate()} disabled={logout.isPending}>
              Sign out
            </button>
          </div>
        </aside>
        <main className="main" id="main">
          <Outlet />
        </main>
      </div>
    </PomodoroProvider>
  );
}
