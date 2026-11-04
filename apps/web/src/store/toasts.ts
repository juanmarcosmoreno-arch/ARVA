import { create } from "zustand";

/** A message shown for a while in the corner, e.g. an unexpected server error with its error log id. `unreachable`
 * is the one notice that ARVA's API gave no answer (its text is the interface's, shown in the current language). */
export interface Toast {
  id: string;
  message: string;
  errorId?: string;
  kind?: "unreachable";
}

interface ToastState {
  toasts: Toast[];
  push: (t: Omit<Toast, "id">) => void;
  dismiss: (id: string) => void;
  /** Removes the "not responding" notice (once the API answers again). */
  dismissUnreachable: () => void;
}

let next = 0;

export const useToasts = create<ToastState>()((set) => ({
  toasts: [],
  push: (toast) =>
    set((s) =>
      (toast.errorId && s.toasts.some((x) => x.errorId === toast.errorId)) || (toast.kind && s.toasts.some((x) => x.kind === toast.kind))
        ? s
        : { toasts: [...s.toasts.slice(-2), { ...toast, id: String((next += 1)) }] },
    ),
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
  dismissUnreachable: () => set((s) => (s.toasts.some((x) => x.kind === "unreachable") ? { toasts: s.toasts.filter((x) => x.kind !== "unreachable") } : s)),
}));
