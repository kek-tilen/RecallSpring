import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { ChatAnswerForm } from "./pages/Answer";

beforeAll(() => {
  Object.assign(URL, { createObjectURL: () => "blob:preview", revokeObjectURL: () => {} });
  // jsdom has no <dialog> methods.
  Object.assign(HTMLDialogElement.prototype, {
    showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
    close(this: HTMLDialogElement) {
      this.removeAttribute("open");
    },
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const QUESTION = { id: "q1", course_id: "k1", prompt: "Convert -0.375 to IEEE 754.", bloom_level: 3, rubric: null };

it("a pasted photo is saved in Answer photos and counts as the answer", async () => {
  const sent: { path: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(String(input), "http://localhost").pathname.replace("/api/v1", "");
    if (path === "/questions/q1") return json(200, QUESTION);
    if (path === "/sources" && init?.method === "POST") {
      const form = init.body as FormData;
      sent.push({ path, body: { course: form.get("course_id"), category: form.get("category"), folder: form.get("folder_path") } });
      return json(201, { id: "p1", filename: "pasted.png" });
    }
    if (path === "/attempts") {
      sent.push({ path, body: JSON.parse(String(init?.body)) });
      return json(201, { attempt_id: "a1", status: "saved_awaiting_evaluation", saved_at: "2026-11-22T11:00:00Z" });
    }
    return json(200, []);
  });
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ChatAnswerForm questionId="q1" onSaved={onSaved} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const save = (await screen.findByRole("button", { name: "Save and send to ChatGPT" })) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  expect(screen.getByText(/Solved it on paper\? A photo of your work counts as your answer \(optional\)/)).toBeTruthy();

  const file = new File([new Uint8Array([137, 80, 78, 71])], "image.png", { type: "image/png" });
  fireEvent.paste(screen.getByRole("textbox"), { clipboardData: { files: [file], items: [], types: ["Files"] } });
  await waitFor(() => expect(save.disabled).toBe(false), { timeout: 5000 });
  expect(sent[0]).toEqual({ path: "/sources", body: { course: "k1", category: "notes", folder: "Answer photos" } });
  expect(screen.getByAltText(/Photo 1/)).toBeTruthy();

  fireEvent.click(save);
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith("answer", ["p1"]), { timeout: 5000 });
  // After saving, the photo stays visible; a click shows it large in this page (no new tab, no download).
  expect(screen.queryByRole("link", { name: /Photo 1/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Photo 1/ }));
  const viewer = screen.getByRole("dialog", { name: "Photo viewer" });
  const big = viewer.querySelector("img") as HTMLImageElement;
  expect(big.getAttribute("src")).toContain("/sources/p1/file");
  fireEvent.click(screen.getByRole("button", { name: "Actual size" }));
  expect(screen.getByRole("button", { name: "Fit to screen" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("link", { name: "Download" }).getAttribute("href")).toContain("/sources/p1/file");
  expect(screen.queryByRole("button", { name: "Next photo" })).toBeNull(); // one photo: no previous/next
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog", { name: "Photo viewer" })).toBeNull();
  // A thumbnail that cannot be shown becomes a download link.
  fireEvent.error(screen.getByAltText(/Photo 1/));
  expect(screen.getByRole("link", { name: "Download photo 1" })).toBeTruthy();
  expect((sent[1]!.body as { photo_ids: string[]; answer_text: string }).photo_ids).toEqual(["p1"]);
});
