import type { ImportResult, Source } from "../types";
import { Modal } from "./ui";
import { Upload } from "./Upload";

/**
 * Upload files from the Chat composer. They are saved in the learner's Library like any upload (same checks and
 * limits; under the conversation's course, or a course the learner picks in a planning conversation) and added to
 * the conversation's material, so their matching excerpts go to ChatGPT and its RecallSpring tools can read them.
 */
export function AttachDialog({
  open,
  courseId,
  onClose,
  onAttached,
}: {
  open: boolean;
  /** The study conversation's course; null lets the learner choose. */
  courseId: string | null;
  onClose: () => void;
  onAttached: (files: Source[]) => void;
}) {
  function imported(result: ImportResult) {
    if (result.imported.length) onAttached(result.imported);
    if (!result.skipped.length) onClose(); // otherwise the dialog stays open and lists what was left out
  }
  return (
    <Modal open={open} title="Add files to this conversation" onClose={onClose} wide>
      <p className="small" style={{ margin: 0 }}>
        The files are saved in your Library{courseId ? "" : " under the course you choose"} and added to this conversation&apos;s
        material, so ChatGPT can use them. RecallSpring needs a few seconds to read a file. Photos are kept in your Library,
        but ChatGPT in Chat cannot see pictures yet.
      </p>
      {open && <Upload courseId={courseId ?? undefined} onImported={imported} />}
    </Modal>
  );
}
