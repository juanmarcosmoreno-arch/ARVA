import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { GlobalSearch } from "@/components/layout/GlobalSearch";

const PROJECTS = [1, 2, 3].map((i) => ({ id: `p${i}`, name: `Staph ${i}`, description: null, institution: null, sample_count: 0 }));

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

afterEach(() => vi.unstubAllGlobals());

it("reaches every result from the keyboard (combobox with an active option)", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(String(url).includes("/projects") ? PROJECTS : []), { status: 200, headers: { "Content-Type": "application/json" } })));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <GlobalSearch />
        <Routes><Route path="*" element={<Where />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const box = screen.getByRole("combobox");
  fireEvent.focus(box);
  fireEvent.change(box, { target: { value: "staph" } });
  await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(3));
  fireEvent.keyDown(box, { key: "ArrowDown" });
  fireEvent.keyDown(box, { key: "ArrowDown" });
  const options = screen.getAllByRole("option");
  expect(options[2].getAttribute("aria-selected")).toBe("true");
  expect(box.getAttribute("aria-activedescendant")).toBe(options[2].id);
  fireEvent.keyDown(box, { key: "Enter" });
  expect(screen.getByTestId("where").textContent).toBe("/projects/p3");
});
