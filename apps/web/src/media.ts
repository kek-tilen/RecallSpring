import { useEffect, useState } from "react";

/** The phone layout's breakpoint (styles.css, `max-width: 860px`). */
export const PHONE_QUERY = "(max-width: 860px)";

function matches(query: string): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
}

/** True on phone-sized screens; follows resizing. False where matchMedia is missing (tests, old browsers). */
export function usePhone(): boolean {
  const [phone, setPhone] = useState(() => matches(PHONE_QUERY));
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(PHONE_QUERY);
    const on = () => setPhone(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return phone;
}
