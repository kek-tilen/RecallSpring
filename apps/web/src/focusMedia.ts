/**
 * Things the Focus timer keeps in this browser only: the learner's own background image (IndexedDB, never sent to
 * RecallSpring) and the chime, made with the Web Audio API (no sound files).
 */

export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024;

const DB_NAME = "recallspring-focus";
const STORE = "files";
const IMAGE_KEY = "background";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("unavailable"));
      return;
    }
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("indexeddb"));
  });
}

async function run<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest): Promise<T> {
  const db = await open();
  try {
    return await new Promise<T>((resolve, reject) => {
      const req = fn(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result as T);
      req.onerror = () => reject(req.error ?? new Error("indexeddb"));
    });
  } finally {
    db.close();
  }
}

/** Why a file cannot be used as a background, or null when it can. */
export function imageProblem(file: File): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return "Choose a PNG, JPEG, WebP or GIF image.";
  if (file.size > MAX_IMAGE_BYTES) return "Choose an image under 20 MB.";
  return null;
}

export async function saveImage(file: Blob): Promise<void> {
  await run<IDBValidKey>("readwrite", (s) => s.put(file, IMAGE_KEY));
}

export async function loadImage(): Promise<Blob | null> {
  try {
    const blob = await run<Blob | undefined>("readonly", (s) => s.get(IMAGE_KEY));
    return blob instanceof Blob ? blob : null;
  } catch {
    return null;
  }
}

export async function removeImage(): Promise<void> {
  try {
    await run<undefined>("readwrite", (s) => s.delete(IMAGE_KEY));
  } catch {
    /* nothing stored */
  }
}

// ---------------------------------------------------------------- chime

let ctx: AudioContext | null = null;

/** Call from a click so the browser lets the page play the chime later. */
export function primeAudio(): void {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
  } catch {
    ctx = null;
  }
}

/** A soft two-note chime: rising after a break (back to focus), falling after focus (rest). */
export function chime(kind: "rest" | "focus"): void {
  primeAudio();
  if (!ctx) return;
  const notes = kind === "rest" ? [880, 660, 523.25] : [523.25, 660, 880];
  const t0 = ctx.currentTime + 0.05;
  notes.forEach((freq, i) => {
    const osc = ctx!.createOscillator();
    const gain = ctx!.createGain();
    const at = t0 + i * 0.32;
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(0.18, at + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + 1.1);
    osc.connect(gain).connect(ctx!.destination);
    osc.start(at);
    osc.stop(at + 1.2);
  });
}
