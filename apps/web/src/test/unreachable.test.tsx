import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorScreen } from "@/components/diagnostics/ErrorScreen";
import { Toaster } from "@/components/layout/Toaster";
import { ErrorNote } from "@/components/ui/misc";
import { ApiError, api } from "@/lib/api";
import { apiAnswered, toastServerError } from "@/lib/apiToasts";
import { resetErrorReporting } from "@/lib/errorReporting";
import { isUnreachable, UNREACHABLE } from "@/lib/unreachable";
import { browserLanguage, mergeStored, useSettings } from "@/store/settings";
import { useToasts } from "@/store/toasts";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** What Safari and ARVA.app's web view do when nothing listens on the port (Docker Desktop closed). */
function apiDown() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
    throw new TypeError("Load failed");
  });
}

function wrap(node: ReactNode, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return { client, ...render(<QueryClientProvider client={client}>{node}</QueryClientProvider>) };
}

beforeEach(() => {
  useSettings.setState({ language: "en" });
  useToasts.setState({ toasts: [] });
  resetErrorReporting();
});
afterEach(() => vi.restoreAllMocks());

describe("an API that does not answer", () => {
  it("is raised as a coded ApiError in the interface language, not the browser's 'Load failed'", async () => {
    apiDown();
    const err = await api.projects().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 0, code: UNREACHABLE, message: "ARVA is not responding. Is Docker Desktop open? ARVA's services run inside it." });
    expect(isUnreachable(err)).toBe(true);

    useSettings.setState({ language: "es" });
    await expect(api.projects()).rejects.toThrow("ARVA no responde. ¿Docker Desktop está abierto? Los servicios de ARVA funcionan dentro de él.");
  });

  it("leaves a cancelled request and the API's own HTTP errors as they were", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      throw new DOMException("The operation was aborted.", "AbortError");
    });
    const aborted = await api.projects().catch((e: unknown) => e);
    expect((aborted as Error).name).toBe("AbortError");
    expect(isUnreachable(aborted)).toBe(false);

    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: "Sample not found", code: "not_found" }, 404));
    const refused = await api.projects().catch((e: unknown) => e);
    expect(refused).toMatchObject({ status: 404, code: "not_found" });
    expect(isUnreachable(refused)).toBe(false);
    expect(isUnreachable(new TypeError("x is undefined"))).toBe(false);
    // A browser network error that did not go through lib/api is recognised by its known texts.
    expect(isUnreachable(new TypeError("Failed to fetch"))).toBe(true);
    expect(isUnreachable(new TypeError("NetworkError when attempting to fetch resource."))).toBe(true);
  });

  it("an error note says so, with a button that asks the page's questions again", async () => {
    let up = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      if (!up) throw new TypeError("Load failed");
      return json([]);
    });
    const queryFn = vi.fn(() => api.projects());
    function Page() {
      const q = useQueryProjects(queryFn);
      return q.error ? <ErrorNote error={q.error} /> : <p>{q.data ? "loaded" : "loading"}</p>;
    }
    wrap(<Page />);
    expect(await screen.findByText("ARVA is not responding. Is Docker Desktop open? ARVA's services run inside it.")).toBeInTheDocument();
    expect(screen.queryByText("Load failed")).not.toBeInTheDocument();
    up = true;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("loaded")).toBeInTheDocument();
  });

  it("the global error screen explains it in Spanish, does not try to record it and offers to try again", () => {
    useSettings.setState({ language: "es" });
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const reload = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, reload } as Location);
    render(<ErrorScreen error={new ApiError(0, "x", undefined, UNREACHABLE)} />);
    expect(screen.getByText("ARVA no responde")).toBeInTheDocument();
    expect(screen.getByText(/¿Docker Desktop está abierto\?/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(reload).toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("shows one toast with a retry button, gone once the API answers; a 4xx refusal shows no toast", () => {
    toastServerError(new ApiError(404, "Sample not found", undefined, "not_found"));
    expect(useToasts.getState().toasts).toHaveLength(0);
    toastServerError(new ApiError(0, "x", undefined, UNREACHABLE));
    toastServerError(new TypeError("Load failed"));
    expect(useToasts.getState().toasts).toHaveLength(1);
    toastServerError(new ApiError(500, "boom", "K7Q2-M9XD"));
    expect(useToasts.getState().toasts).toHaveLength(2);

    const { client } = wrap(<Toaster />);
    const refetch = vi.spyOn(client, "refetchQueries");
    expect(screen.getByText("ARVA is not responding. Is Docker Desktop open? ARVA's services run inside it.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledWith({ type: "active" });

    apiAnswered();
    expect(useToasts.getState().toasts.map((t) => t.errorId)).toEqual(["K7Q2-M9XD"]);
  });
});

describe("the interface language", () => {
  it("follows the browser's first language until the user picks one", () => {
    expect(browserLanguage({ languages: ["es-AR", "en-US"], language: "es-AR" })).toBe("es");
    expect(browserLanguage({ languages: ["es-419"] })).toBe("es");
    expect(browserLanguage({ languages: [], language: "es" })).toBe("es");
    expect(browserLanguage({ languages: ["en-GB", "es-ES"], language: "en-GB" })).toBe("en");
    expect(browserLanguage({ languages: ["et-EE"] })).toBe("en");
    expect(browserLanguage(undefined)).toBe("en");
  });

  it("keeps a language the user picked and re-reads the browser's when none was picked", () => {
    const spanishMac = vi.spyOn(navigator, "languages", "get").mockReturnValue(["es-ES", "en-US"]);
    const current = { ...useSettings.getState(), language: browserLanguage(), languageChosen: false };
    expect(current.language).toBe("es");
    // First visit: nothing stored.
    expect(mergeStored(undefined, current)).toMatchObject({ language: "es", languageChosen: false });
    // English picked by hand stays English on a Spanish Mac.
    expect(mergeStored({ language: "en", languageChosen: true, theme: "dark" }, current)).toMatchObject({ language: "en", languageChosen: true, theme: "dark" });
    // Stored before languageChosen existed: English was only the old default, Spanish was always a choice.
    expect(mergeStored({ language: "en", theme: "dark" }, current)).toMatchObject({ language: "es", languageChosen: false, theme: "dark" });
    expect(mergeStored({ language: "es" }, { ...current, language: "en" })).toMatchObject({ language: "es", languageChosen: true });
    spanishMac.mockRestore();

    useSettings.setState({ languageChosen: false });
    useSettings.getState().setLanguage("es");
    expect(useSettings.getState()).toMatchObject({ language: "es", languageChosen: true });
    useSettings.setState({ language: "en", languageChosen: false });
  });
});

function useQueryProjects(queryFn: () => Promise<unknown>) {
  return useQuery({ queryKey: ["projects-test"], queryFn });
}
