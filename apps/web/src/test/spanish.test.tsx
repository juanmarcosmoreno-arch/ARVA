import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { FailedCard } from "@/components/assembly/RunMonitor";
import { UploadResultList } from "@/components/domain/FileDropzone";
import { ProjectFormDialog } from "@/components/domain/ProjectFormDialog";
import { SampleFormDialog } from "@/components/domain/SampleForm";
import { translator } from "@/i18n";
import { fmtBp, fmtDate, fmtPct } from "@/lib/format";
import { databaseError, jobError, seqstatsWarnings } from "@/lib/messages";
import type { AnalysisJobDetail, JobResources, RawFile } from "@/lib/types";
import { useSettings } from "@/store/settings";

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const file = (extra: Partial<RawFile>): RawFile => ({
  id: "f1", sample_id: "s", original_filename: "reads_R1.fastq.gz", file_format: "fastq_gz", read_mate: "R1", size_bytes: 1_234_567,
  checksum_sha256: "a".repeat(64), is_valid: true, validation_message: null, uploaded_at: "2026-10-28T13:00:00Z", origin: "imported",
  parent_file_id: null, produced_by_job_id: null, description: null, header_metadata: null, ...extra,
});

const job = (extra: Partial<AnalysisJobDetail>): AnalysisJobDetail => ({
  id: "job-1", project_id: "p", sample_id: "s", job_type: "flye_assembly", tool_name: "Flye", tool_version: "2.9.3", database_name: null,
  database_version: null, parameters: {}, input_raw_file_ids: ["f1"], output_paths: null, status: "failed", started_at: "2026-10-28T13:00:00Z",
  finished_at: "2026-10-28T13:05:00Z", duration_seconds: 300, log_text: "", error_message: null, created_at: "2026-10-28T13:00:00Z", commands: [],
  tool_path: null, result_summary: null, parent_job_id: null, qc_results: [], ...extra,
});

const resources: JobResources = {
  profile: "light", choice: "auto", threads: 2, memory_gb: 3, memory_limit_gb: 3, memory_option: "-m", nice: 15, nice_executable: "/usr/bin/nice",
  usable_cpus: 8, usable_memory_gb: 7.7, in_container: true, host: "MacBook Air · Apple M2",
};

beforeEach(() => useSettings.setState({ language: "es" }));

describe("the Spanish interface", () => {
  it("shows the project form in Spanish", () => {
    renderWith(<ProjectFormDialog open onOpenChange={() => undefined} />);
    const dialog = screen.getByRole("dialog", { name: "Nuevo proyecto" });
    expect(dialog).toHaveTextContent("Un proyecto agrupa muestras, análisis e informes.");
    expect(screen.getByText("Nombre del proyecto *")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("p. ej., mastitis bovina por S. aureus 2024")).toBeInTheDocument();
    expect(screen.getByText("Investigador/a")).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent(/Project name|Researcher|Institution|Description/);
  });

  it("shows the sample form in Spanish, with the field names of the metadata import", () => {
    renderWith(<SampleFormDialog open onOpenChange={() => undefined} projectId="p" />);
    const dialog = screen.getByRole("dialog", { name: "Nueva muestra" });
    expect(dialog).toHaveTextContent("Solo el ID de muestra es obligatorio");
    for (const label of ["ID de muestra *", "Tecnología de secuenciación", "Organismo", "Hospedador", "Fecha de muestreo", "Notas"])
      expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("p. ej., aislado, leche, hisopo")).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent(/Organism\b|Host\b|Sample type|Collection date|Notes/);
  });

  it("translates the import check and the refusals from their codes, keeping unknown codes in English", () => {
    renderWith(
      <UploadResultList
        result={{
          files: [
            file({
              validation_message: "FASTQ structure verified on the first 1000 record(s); ... Note: identical content is already registered in sample S2 as r.fq.",
              validation_detail: { code: "verified", params: { format: "FASTQ", count: 1000, twin_sample: "S2", twin_file: "r.fq" } },
            }),
            file({ id: "f2", original_filename: "x.fq", is_valid: false, validation_message: "A future check", validation_detail: { code: "future_code", params: {} } }),
          ],
          rejected: [
            { filename: "dup.fq", reason: "identical content is already registered for this sample as 'a.fq' (sha256 abc…)", code: "duplicate", params: { file: "a.fq" } },
            { filename: "big.fq", reason: "Not enough free space…", code: "insufficient_storage", params: { needed_bytes: 5 * 1024 ** 3, available_bytes: 1024 ** 3 } },
          ],
        }}
      />,
    );
    expect(screen.getByText(
      "Estructura FASTQ verificada en los primeros 1000 registros; el archivo completo se valida al calcular las estadísticas. " +
        "Nota: el mismo contenido ya está registrado en la muestra S2 como r.fq.",
    )).toBeInTheDocument();
    expect(screen.getByText("A future check")).toBeInTheDocument();
    expect(screen.getByText("el mismo contenido ya está registrado en esta muestra como «a.fq»")).toBeInTheDocument();
    expect(screen.getByText(/se necesitan 5,00 GB pero solo se pueden usar 1,00 GB/)).toBeInTheDocument();
    expect(screen.getAllByText(/1,18 MB/)).toHaveLength(2);
  });

  it("explains a failed job in Spanish from the worker's code, and keeps English text without a code", () => {
    const failed = job({ error_message: "flye exited with status 1", error_detail: { code: "tool_exit", params: { tool: "flye", status: 1 } } });
    const { unmount } = renderWith(<FailedCard job={failed} />);
    expect(screen.getByText("flye terminó con el código de salida 1")).toBeInTheDocument();
    unmount();
    const t = translator("es");
    const oom = job({ error_message: "...", error_detail: { code: "out_of_memory", params: { tool: "flye" } }, resources });
    expect(jobError(t, oom)).toBe(
      "El sistema operativo detuvo flye con SIGKILL, lo que suele significar que el equipo (o el contenedor) se quedó sin memoria. " +
        "ARVA podía usar 7.7 GB de memoria aquí (el límite del contenedor); este trabajo se ejecutó con 2 hilos, un límite de memoria de 3 GB " +
        "(perfil Ligero). Elige un perfil de rendimiento más ligero o menos hilos en Ajustes → Rendimiento, o da más memoria a Docker Desktop " +
        "(Docker Desktop → Settings → Resources).",
    );
    expect(jobError(t, job({ error_message: "TypeError: boom" }))).toBe("TypeError: boom");
    expect(databaseError(t, { error_message: "…", error_detail: { code: "interrupted", params: { done_bytes: 1024 ** 3, total_bytes: 4 * 1024 ** 3 } } }))
      .toBe("la descarga se detuvo en 1,00 GB de 4,00 GB; vuelve a iniciarla para continuar desde ahí");
    expect(seqstatsWarnings(t, { warnings: ["1 record(s) have zero length."], messages: [{ code: "zero_length", params: { count: 1 }, text: "1 record(s) have zero length." }] }))
      .toEqual(["1 registro tiene longitud cero."]);
  });

  it("writes numbers, units and dates as Spanish does", () => {
    expect(fmtBp(2_814_816)).toBe("2.814.816 pb");
    // A no-break space, as Intl writes it, so that the sign never wraps to the next line.
    expect(fmtPct(45.25, 1)).toBe("45,3\u00a0%");
    expect(fmtDate("2026-10-28T13:05:00Z")).toMatch(/28 oct 2026/);
  });
});
