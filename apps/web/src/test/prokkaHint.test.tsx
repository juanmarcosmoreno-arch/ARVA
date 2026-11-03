import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ExplorerSearch } from "@/components/explorer/ExplorerControls";
import { useSettings } from "@/store/settings";

afterEach(() => vi.unstubAllGlobals());

function search(prokka: boolean) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "Content-Type": "application/json" } })));
  const r = render(
    <QueryClientProvider client={new QueryClient()}>
      <ExplorerSearch annotationId="a1" prokka={prokka} contigs={[{ id: "contig_1", name: "contig_1", length: 1000, circular: null, circularSource: null }]} current="contig_1" onRegion={() => {}} onFeature={() => {}} />
    </QueryClientProvider>,
  );
  const box = screen.getByRole("combobox");
  fireEvent.change(box, { target: { value: "mecA" } });
  fireEvent.keyDown(box, { key: "Enter" });
  return r;
}

it("explains Prokka's generic gene names when a search on a Prokka annotation finds nothing", async () => {
  useSettings.setState({ language: "es" });
  search(true);
  expect(await screen.findByText(/Ningún elemento coincide con «mecA»/)).toBeTruthy();
  expect(screen.getByText(/puede aparecer como pbp/)).toBeTruthy();
});

it("does not show the Prokka hint for a Bakta annotation", async () => {
  useSettings.setState({ language: "en" });
  search(false);
  expect(await screen.findByText(/No feature matches/)).toBeTruthy();
  expect(screen.queryByText(/can appear as pbp/)).toBeNull();
});
