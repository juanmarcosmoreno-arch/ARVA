import { useContext } from "react";
import { QueryClientContext } from "@tanstack/react-query";

/** The code of an ApiError raised when ARVA's API gave no answer at all: fetch itself failed (Docker Desktop closed,
 * the containers still starting or restarting), as opposed to an HTTP error the API answered with. */
export const UNREACHABLE = "api_unreachable";

// What browsers say when fetch gets no response: Safari and WKWebView "Load failed", Chrome "Failed to fetch",
// Firefox "NetworkError when attempting to fetch resource.". Only for a TypeError that escaped lib/api.
const NETWORK_TYPE_ERROR = /^(Load failed|Failed to fetch|NetworkError when attempting to fetch resource\.?)$/;

/** Whether an error means the API did not answer. Read by shape (tests mock lib/api, which raises it). */
export function isUnreachable(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  if ((error as { code?: unknown }).code === UNREACHABLE) return true;
  return error instanceof TypeError && NETWORK_TYPE_ERROR.test(error.message);
}

/** Asks again everything on the page (the queries being shown); a no-op outside a QueryClientProvider. */
export function useRetryQueries(): () => void {
  const client = useContext(QueryClientContext);
  return () => void client?.refetchQueries({ type: "active" });
}
