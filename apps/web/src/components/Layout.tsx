import { useMutation, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router";
import { request } from "../api";
import { useDashboard, useSession } from "../queries";

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/courses", label: "Courses" },
  { to: "/exams", label: "Exams" },
  { to: "/review", label: "Review" },
  { to: "/simulations", label: "Simulations" },
  { to: "/library", label: "Library" },
  { to: "/notes", label: "Notes" },
  { to: "/chat", label: "Chat" },
  { to: "/history", label: "History" },
  { to: "/guide", label: "Guide" },
  { to: "/settings", label: "Settings" },
];

export function Layout() {
  const session = useSession();
  const dashboard = useDashboard();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const logout = useMutation({
    mutationFn: () => request<void>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      qc.clear();
      navigate("/login", { replace: true });
    },
  });
  const due = dashboard.data?.plan.items.filter((i) => i.category === "Review due").length ?? 0;

  return (
    <div className="shell">
      <aside className="rail">
        <NavLink to="/" className="brand" aria-label="RecallSpring home">
          <img src="/favicon.svg" alt="" />
          RecallSpring
        </NavLink>
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
  );
}
