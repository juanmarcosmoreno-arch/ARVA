import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { AnalysisTimeline, MetricTile } from "@/components/domain/bits";
import { Explain } from "@/components/guide/Explain";
import { useSettings } from "@/store/settings";

describe("Explain ('What does this mean?')", () => {
  beforeEach(() => useSettings.setState({ language: "en", guideLevel: "beginner" }));

  it("opens the guide article for a metric", async () => {
    render(<Explain id="n50" />);
    await userEvent.click(screen.getByRole("button", { name: /What does this mean\? — N50 and N90/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("N50 is the length L");
    expect(screen.queryByText("Methodological detail")).not.toBeInTheDocument();
  });

  it("adapts depth to the selected level and language", async () => {
    useSettings.setState({ language: "es", guideLevel: "advanced" });
    render(<Explain id="read_quality" />);
    await userEvent.click(screen.getByRole("button", { name: /¿Qué significa esto\?/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Detalle metodológico");
    expect(screen.getByRole("dialog")).toHaveTextContent("−10·log10");
  });
});

describe("MetricTile", () => {
  it("renders value and explanation trigger", () => {
    render(<MetricTile label="N50" value="9,620 bp" explain="n50" />);
    expect(screen.getByText("9,620 bp")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /N50/ })).toBeInTheDocument();
  });
});

describe("AnalysisTimeline", () => {
  beforeEach(() => useSettings.setState({ language: "en" }));

  it("marks planned stages with their phase and disables them", () => {
    render(
      <MemoryRouter>
        <AnalysisTimeline
          stages={[
            { key: "raw", label: "Raw data", state: "done", detail: "1 file(s)" },
            { key: "assembly", label: "Assembly", state: "planned", phase: 3 },
          ]}
          onSelect={() => {}}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("Phase 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assembly: planned" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Raw data: done" })).toBeEnabled();
  });
});
