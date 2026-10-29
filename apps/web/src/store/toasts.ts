import { create } from "zustand";

/** A message shown for a while in the corner, e.g. an unexpected server error with its error log id. */
export interface Toast {
  id: string;
  message: string;
  errorId?: string;
}

interface ToastState {
  toasts: Toast[];
  push: (t: Omit<Toast, "id">) => void;
  dismiss: (id: string) => void;
}

let next = 0;

export const useToasts = create<ToastState>()((set) => ({
  toasts: [],
  push: (toast) =>
    set((s) =>
      toast.errorId && s.toasts.some((x) => x.errorId === toast.errorId)
        ? s
        : { toasts: [...s.toasts.slice(-2), { ...toast, id: String((next += 1)) }] },
    ),
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}));
