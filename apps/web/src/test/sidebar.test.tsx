import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import { Sidebar } from "@/components/layout/Sidebar";

it("highlights one sidebar entry on the Comparative genomics page, not the entries that share it", () => {
  render(
    <MemoryRouter initialEntries={["/comparative/set-1"]}>
      <Sidebar />
    </MemoryRouter>,
  );
  const active = screen.getAllByRole("link").filter((a) => a.className.includes("bg-white/10"));
  expect(active.map((a) => a.textContent)).toEqual(["Comparative Genomics"]);
});
