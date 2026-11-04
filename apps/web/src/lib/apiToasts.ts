import { ApiError } from "@/lib/api";
import { isUnreachable } from "@/lib/unreachable";
import { useToasts } from "@/store/toasts";

/** An unexpected server error (one the API kept in its error log) is also shown as a toast with its error id; an API
 * that gives no answer at all (Docker Desktop closed) as one "ARVA is not responding" toast with a retry button. HTTP
 * errors the API answered with (4xx, coded refusals) are left to the page that asked. */
export function toastServerError(error: unknown) {
  if (isUnreachable(error)) useToasts.getState().push({ message: "", kind: "unreachable" });
  else if (error instanceof ApiError && error.errorId) useToasts.getState().push({ message: error.message, errorId: error.errorId });
}

/** Any answer from the API means it is reachable again: the "not responding" toast goes. */
export function apiAnswered() {
  useToasts.getState().dismissUnreachable();
}
