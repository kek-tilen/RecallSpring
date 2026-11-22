import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

export interface ViewerPhoto {
  src: string; // shown in an <img> only, never opened as a page
  name: string;
  download?: string; // where "Download" points (the original file)
}

/** A large view of the learner's photos in a modal: fit to the screen or actual size (to read handwriting), with
 * previous/next (buttons, arrow keys) when there are several. Escape, Close or a click beside the photo closes it. */
export function PhotoViewer({ photos, index, onIndex, onClose }: {
  photos: ViewerPhoto[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [actual, setActual] = useState(false);
  const [broken, setBroken] = useState(false);
  const photo = photos[index];
  const many = photos.length > 1;

  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
    return () => {
      if (d?.open) d.close();
    };
  }, []);
  useEffect(() => {
    setActual(false);
    setBroken(false);
  }, [index]);

  if (!photo) return null;
  const go = (step: number) => onIndex((index + step + photos.length) % photos.length);

  function onKey(e: KeyboardEvent) {
    if (!many) return;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      go(-1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      go(1);
    }
  }

  function onBackdrop(e: MouseEvent) {
    if (e.target === e.currentTarget) onClose();
  }

  return (
    <dialog ref={ref} className="photo-viewer" aria-label="Photo viewer" onClose={onClose} onKeyDown={onKey} onClick={onBackdrop}>
      <div className="photo-viewer-bar">
        <span className="photo-viewer-title" aria-live="polite">
          {many ? `Photo ${index + 1} of ${photos.length}` : "Photo"}
          <span className="photo-viewer-name"> · {photo.name}</span>
        </span>
        <div className="row" style={{ gap: 6 }}>
          {!broken && (
            <button type="button" className="btn small" aria-pressed={actual} onClick={() => setActual((a) => !a)}>
              {actual ? "Fit to screen" : "Actual size"}
            </button>
          )}
          {photo.download && (
            <a className="btn small" href={photo.download} download={photo.name}>
              Download
            </a>
          )}
          <button type="button" className="btn small" onClick={onClose} autoFocus>
            Close
          </button>
        </div>
      </div>
      <div className={`photo-viewer-stage${actual ? " is-actual" : ""}`} onClick={onBackdrop}>
        {broken ? (
          <p className="photo-viewer-broken">This photo cannot be shown here{photo.download ? "; you can still download it." : "."}</p>
        ) : (
          <img
            key={photo.src}
            src={photo.src}
            alt={many ? `Photo ${index + 1}: ${photo.name}` : photo.name}
            title={actual ? "Click to fit to screen" : "Click for actual size"}
            onClick={() => setActual((a) => !a)}
            onError={() => setBroken(true)}
          />
        )}
      </div>
      {many && (
        <>
          <button type="button" className="photo-viewer-nav is-prev" aria-label="Previous photo" onClick={() => go(-1)}>
            ‹
          </button>
          <button type="button" className="photo-viewer-nav is-next" aria-label="Next photo" onClick={() => go(1)}>
            ›
          </button>
        </>
      )}
    </dialog>
  );
}
