import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CopyErrorDetails } from "@/components/diagnostics/CopyErrorDetails";
import { ErrorScreen } from "@/components/diagnostics/ErrorScreen";
import { Toaster } from "@/components/layout/Toaster";
import { DiagnosticsSection } from "@/components/settings/DiagnosticsSection";
import { ErrorNote } from "@/components/ui/misc";
import { ApiError, apiError } from "@/lib/api";
import type { ErrorEntry } from "@/lib/diagnostics";
import { resetErrorReporting } from "@/lib/errorReporting";
import { useSettings } from "@/store/settings";
import { useToasts } from "@/store/toasts";

// CONSTRUCTED: what GET /system/errors returns after a failed SPAdes run and an unexpected API error.
const entries: ErrorEntry[] = [
  { id: "K7Q2-M9XD", time: "2026-10-29T09:58:01Z", component: "job", severity: "error", code: "tool_exit", message: "spades.py exited with status 1",
    params: { tool: "spades.py", status: 1 }, route: null, job_id: "6f1c2a7e-0000-4000-8000-000000000000", job_type: "spades_assembly", correlation_id: "0123456789abcdef" },
  { id: "R2D2-C3P0", time: "2026-10-29T09:00:00Z", component: "api", severity: "error", code: "internal_error", message: "Unexpected error while handling GET /api/v1/x",
    params: { method: "GET", route: "/api/v1/samples/{sample_id}" }, route: "/api/v1/samples/{sample_id}", job_id: null, job_type: null, correlation_id: null },
];
const REPORT = "# ARVA diagnostic report\n\n## Recent errors (2)\n";

let calls: { url: string; init?: RequestInit }[] = [];
let writeText: ReturnType<typeof vi.fn>;

function serve(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    calls.push({ url, init });
    return handler(url, init);
  });
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  useSettings.setState({ language: "en", diagnosticsAnonymise: false });
  writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  resetErrorReporting();
});
afterEach(() => vi.restoreAllMocks());

describe("Settings → Diagnostics", () => {
  it("lists the recent errors in the interface language and copies the report with the chosen options", async () => {
    serve((url) => (url.includes("/system/errors") ? json(entries) : new Response(REPORT)));
    wrap(<DiagnosticsSection />);
    expect(await screen.findByText("K7Q2-M9XD")).toBeInTheDocument();
    expect(screen.getByText("spades.py exited with status 1")).toBeInTheDocument();
    expect(screen.getByText("Unexpected error while handling GET /api/v1/samples/{sample_id}")).toBeInTheDocument();
    expect(screen.getByText("Analysis")).toBeInTheDocument();
    expect(screen.getByText(/never contains your sequences, reads/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download/ }).getAttribute("href")).toBe("/api/v1/system/diagnostics?format=zip&anonymise=false&since_hours=168");

    fireEvent.click(screen.getByLabelText(/Replace project, sample and file names/));
    fireEvent.click(screen.getByRole("button", { name: /Copy diagnostic report/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(REPORT));
    expect(calls.at(-1)!.url).toBe("/api/v1/system/diagnostics?format=markdown&anonymise=true&since_hours=168");
    expect(await screen.findByText("Copied. Paste it into the chat.")).toBeInTheDocument();
    expect(useSettings.getState().diagnosticsAnonymise).toBe(true);
  });

  it("reads in Spanish and says when there are no errors", async () => {
    useSettings.setState({ language: "es" });
    serve(() => json([]));
    wrap(<DiagnosticsSection />);
    expect(await screen.findByText("No hay errores registrados.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copiar informe de diagnóstico/ })).toBeInTheDocument();
    expect(screen.getByText(/Nunca contiene tus secuencias/)).toBeInTheDocument();
  });
});

describe("Copy error details", () => {
  it("copies the report scoped to a job, anonymised when Settings says so", async () => {
    useSettings.setState({ diagnosticsAnonymise: true });
    serve(() => new Response(REPORT));
    render(<CopyErrorDetails jobId="6f1c2a7e-0000-4000-8000-000000000000" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy error details" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(calls[0].url).toBe("/api/v1/system/diagnostics?format=markdown&anonymise=true&job_id=6f1c2a7e-0000-4000-8000-000000000000");
    expect(writeText).toHaveBeenCalledWith(REPORT);
  });

  it("an unexpected server error shows its id with the button, also in a toast", async () => {
    serve(() => new Response(REPORT));
    render(<ErrorNote error={new ApiError(500, "ARVA hit an unexpected error (error ID R2D2-C3P0).", "R2D2-C3P0")} />);
    expect(screen.getByText("Error ID: R2D2-C3P0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy error details" }));
    await waitFor(() => expect(calls[0].url).toContain("error_id=R2D2-C3P0"));

    useToasts.setState({ toasts: [] });
    useToasts.getState().push({ message: "boom", errorId: "R2D2-C3P0" });
    useToasts.getState().push({ message: "boom", errorId: "R2D2-C3P0" });
    render(<Toaster />);
    expect(screen.getAllByText("Error ID: R2D2-C3P0")).toHaveLength(2);
    expect(useToasts.getState().toasts).toHaveLength(1);
  });
});

describe("errors the interface reports", () => {
  it("the global error screen records the error and shows its id", async () => {
    serve((url) => (url.endsWith("/system/client-errors") ? json({ id: "WXYZ-2345", duplicate: false }, 201) : new Response(REPORT)));
    render(<ErrorScreen error={new TypeError("x is undefined")} componentStack={"\n    at Panel"} />);
    expect(await screen.findByText("Error ID: WXYZ-2345")).toBeInTheDocument();
    const body = JSON.parse(String(calls[0].init!.body));
    expect(body).toMatchObject({ kind: "boundary", message: "x is undefined", name: "TypeError", component_stack: "\n    at Panel", client_commit: "unknown" });
    fireEvent.click(screen.getByRole("button", { name: "Copy error details" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(REPORT));
    expect(calls.at(-1)!.url).toContain("error_id=WXYZ-2345");
  });

  it("without the API the screen says so and copies what the interface knows", async () => {
    serve(() => {
      throw new TypeError("Failed to fetch");
    });
    render(<ErrorScreen error={new Error("render failed")} />);
    expect(await screen.findByText(/could not record the error/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy error details" }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(writeText.mock.calls[0][0]).toContain("- Error: Error: render failed");
  });

  it("a server error the API did not record is reported once, by its route shape; a recorded one is not", async () => {
    serve(() => json({ id: "AAAA-BBBB", duplicate: false }, 201));
    const proxy = new Response("Bad Gateway", { status: 502, statusText: "Bad Gateway" });
    Object.defineProperty(proxy, "url", { value: "http://localhost:8080/api/v1/samples/S1/files?x=1" });
    const err = await apiError(proxy, "GET");
    expect(err.status).toBe(502);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(JSON.parse(String(calls[0].init!.body)).api).toEqual({ method: "GET", path: "/api/v1/samples/S1/files", status: 502 });

    const recorded = await apiError(json({ detail: "x", code: "internal_error", params: { error_id: "K7Q2-M9XD" }, error_id: "K7Q2-M9XD" }, 500));
    expect(recorded.errorId).toBe("K7Q2-M9XD");
    expect(calls).toHaveLength(1);
  });
});
