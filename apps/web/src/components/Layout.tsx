import {
  IconBooks,
  IconCalendarEvent,
  IconChartBar,
  IconClock,
  IconHelp,
  IconLayoutSidebar,
  IconMessage,
  IconRefresh,
  IconSchool,
  IconSettings,
  type Icon,
} from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { useAssistants, useDueCount, useSession } from "../queries";
import { BrandMark } from "./BrandMark";
import { FocusPill, PomodoroProvider } from "./Pomodoro";

/**
 * The app shell (UI direction, 2026-11-27): six areas instead of twelve menu items. Desktop has a rail with an icon
 * left of every label; phones have a bottom bar with Today (the RecallSpring symbol) in the middle. Pages that moved
 * into an area keep it highlighted, e.g. Library and Notes belong to Courses, Week to Today, Simulations to Results.
 */
interface Area {
  to: string;
  label: string;
  icon: Icon;
  /** Other paths that belong to this area. */
  also?: string[];
}

const TODAY: Area = { to: "/", label: "Today", icon: IconCalendarEvent, also: ["/week"] };
const COURSES: Area = { to: "/courses", label: "Courses", icon: IconBooks, also: ["/library", "/notes", "/concepts"] };
const REVIEW: Area = { to: "/review", label: "Review", icon: IconRefresh };
const EXAMS: Area = { to: "/exams", label: "Exams", icon: IconSchool };
const RESULTS: Area = { to: "/simulations", label: "Results", icon: IconChartBar };
const CHAT: Area = { to: "/chat", label: "Chat", icon: IconMessage };
const FOCUS: Area = { to: "/focus", label: "Focus", icon: IconClock };

/** Phone bottom bar, in this order: Today in the middle. */
const TABS: Area[] = [REVIEW, RESULTS, TODAY, COURSES, FOCUS];

const RAIL_KEY = "rs-rail";

function railHidden(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "hidden";
  } catch {
    return false;
  }
}

function under(path: string, base: string): boolean {
  return path === base || path.startsWith(`${base}/`);
}

export function isActive(path: string, a: Area): boolean {
  if (a.to === "/" ? path === "/" : under(path, a.to)) return true;
  return (a.also ?? []).some((p) => under(path, p));
}

/** Chat is shown when ChatGPT is one of the learner's assistants (chosen, in the mix or connected). */
export function useChatShown(): boolean {
  const user = useSession().data?.user;
  const status = useAssistants();
  const path = useLocation().pathname;
  if (under(path, "/chat")) return true;
  if (user?.assistant === "chatgpt" || user?.assistant_mix?.includes("chatgpt")) return true;
  return !!status.data?.items.some((i) => i.key === "chatgpt" && (i.connected || i.in_mix));
}

function AreaLink({ a, path, due }: { a: Area; path: string; due?: number }) {
  const active = isActive(path, a);
  const Glyph = a.icon;
  return (
    <Link to={a.to} className={active ? "active" : undefined} aria-current={active ? "page" : undefined}>
      <Glyph size={20} stroke={1.75} aria-hidden="true" focusable="false" />
      <span>{a.label}</span>
      {!!due && (
        <span className="count" aria-label={`${due} due`}>
          {due}
        </span>
      )}
    </Link>
  );
}

export function Layout() {
  const path = useLocation().pathname;
  const chat = useChatShown();
  const [hidden, setHidden] = useState(railHidden);
  const showButton = useRef<HTMLButtonElement>(null);
  const hideButton = useRef<HTMLButtonElement>(null);
  const moved = useRef(false);
  const due = useDueCount();
  const areas = [TODAY, COURSES, REVIEW, EXAMS, RESULTS, ...(chat ? [CHAT] : []), FOCUS];

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
            <IconLayoutSidebar size={18} stroke={1.75} aria-hidden="true" focusable="false" />
          </button>
        )}
        <aside className="rail" id="rail">
          <div className="rail-top">
            <Link to="/" className="brand" aria-label="RecallSpring, Today">
              <BrandMark />
              <span className="brand-name">RecallSpring</span>
            </Link>
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
              <IconLayoutSidebar size={18} stroke={1.75} aria-hidden="true" focusable="false" />
            </button>
          </div>
          {!hidden && <FocusPill />}
          <nav aria-label="Main" className="rail-nav">
            {areas.map((a) => (
              <AreaLink key={a.to} a={a} path={path} due={a === REVIEW ? due : undefined} />
            ))}
          </nav>
          <div className="rail-foot">
            {chat && (
              <Link
                to="/chat"
                className={`rail-icon phone-only${isActive(path, CHAT) ? " active" : ""}`}
                aria-label="Chat"
                aria-current={isActive(path, CHAT) ? "page" : undefined}
              >
                <IconMessage size={20} stroke={1.75} aria-hidden="true" focusable="false" />
              </Link>
            )}
            <Link
              to="/settings"
              className={`rail-settings${under(path, "/settings") || under(path, "/history") ? " active" : ""}`}
              aria-current={under(path, "/settings") ? "page" : undefined}
            >
              <IconSettings size={20} stroke={1.75} aria-hidden="true" focusable="false" />
              <span className="rail-label">Settings</span>
            </Link>
            <Link
              to="/guide"
              className={`rail-icon${under(path, "/guide") ? " active" : ""}`}
              aria-label="Help: the Guide"
              title="Help: the Guide"
              aria-current={under(path, "/guide") ? "page" : undefined}
            >
              <IconHelp size={20} stroke={1.75} aria-hidden="true" focusable="false" />
            </Link>
          </div>
        </aside>
        <main className="main" id="main">
          <Outlet />
        </main>
        <nav aria-label="Main" className="tabbar">
          {TABS.map((a) => {
            const active = isActive(path, a);
            const Glyph = a.icon;
            return (
              <Link
                key={a.to}
                to={a.to}
                className={`${a === TODAY ? "tab-today" : ""}${active ? " active" : ""}`.trim() || undefined}
                aria-current={active ? "page" : undefined}
              >
                {a === TODAY ? (
                  <BrandMark size={26} />
                ) : (
                  <Glyph size={22} stroke={1.75} aria-hidden="true" focusable="false" />
                )}
                <span>{a.label}</span>
                {a === REVIEW && due > 0 && (
                  <span className="tab-count" aria-label={`${due} due`}>
                    {due}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>
    </PomodoroProvider>
  );
}
