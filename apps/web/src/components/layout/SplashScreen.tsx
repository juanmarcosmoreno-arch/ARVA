import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "@/i18n";
import { useSettings } from "@/store/settings";

export const SPLASH_SEEN_KEY = "arva-splash-seen";
const FADE_MS = 400;
const STILL_MS = 1500;
// Closes the splash even if the video never starts or never fires "ended".
const MAX_MS = 14_000;

function seenThisSession() {
  try {
    return sessionStorage.getItem(SPLASH_SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

function markSeen() {
  try {
    sessionStorage.setItem(SPLASH_SEEN_KEY, "1");
  } catch {
    // Storage can be unavailable (private mode); the splash then shows on every load.
  }
}

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

/** Small start-up window with the ARVA intro, shown once per browser session (Settings → Interface). */
export function SplashScreen() {
  const t = useT();
  const enabled = useSettings((s) => s.showIntro);
  const [open, setOpen] = useState(() => enabled && !seenThisSession());
  const [closing, setClosing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [still] = useState(prefersReducedMotion);
  const skipRef = useRef<HTMLButtonElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const close = useCallback(() => {
    markSeen();
    setClosing(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    skipRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    const limit = window.setTimeout(close, still ? STILL_MS : MAX_MS);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(limit);
    };
  }, [open, still, close]);

  useEffect(() => {
    if (!open || still) return;
    videoRef.current?.play()?.catch(close);
  }, [open, still, close]);

  useEffect(() => {
    if (!closing) return;
    const id = window.setTimeout(() => setOpen(false), FADE_MS);
    return () => window.clearTimeout(id);
  }, [closing]);

  if (!open) return null;

  const onTime = () => {
    const v = videoRef.current;
    if (v && v.duration > 0) setProgress(Math.min(1, v.currentTime / v.duration));
  };

  return (
    <div
      className="fixed inset-0 z-[100] grid place-items-center bg-arva-navy/60 p-4 backdrop-blur-[2px] transition-opacity ease-out"
      style={{ opacity: closing ? 0 : 1, transitionDuration: `${FADE_MS}ms` }}
      onClick={close}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("splash.label")}
        className="w-[min(560px,100%)] overflow-hidden rounded-2xl border border-white/10 bg-arva-navy shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {still ? (
          <img src="/intro/arva-intro-end.jpg" alt="ARVA — Genomic Discovery Platform" className="block aspect-video w-full" />
        ) : (
          <video
            ref={videoRef}
            className="block aspect-video w-full bg-arva-navy"
            src="/intro/arva-intro.mp4"
            poster="/intro/arva-intro-start.jpg"
            muted
            playsInline
            autoPlay
            preload="auto"
            aria-hidden="true"
            onTimeUpdate={onTime}
            onEnded={close}
            onError={close}
          />
        )}
        <div className="flex items-center gap-3 px-4 py-2.5 text-xs text-white/70">
          <span className="shrink-0 tabular-nums">ARVA {__ARVA_VERSION__}</span>
          <div
            className="h-1 flex-1 overflow-hidden rounded-full bg-white/10"
            role="progressbar"
            aria-label={t("splash.progress")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round((still ? 1 : progress) * 100)}
          >
            <div
              className="h-full rounded-full bg-gradient-to-r from-arva-teal to-arva-cyan transition-[width] duration-300 ease-linear"
              style={{ width: `${(still ? 1 : progress) * 100}%` }}
            />
          </div>
          <button
            ref={skipRef}
            type="button"
            onClick={close}
            className="shrink-0 rounded px-1.5 py-0.5 font-medium text-white/80 hover:text-white focus:outline-none focus-visible:ring-1 focus-visible:ring-white/50"
          >
            {t("splash.skip")}
          </button>
        </div>
      </div>
    </div>
  );
}
