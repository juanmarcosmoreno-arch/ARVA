import type {
  AnalysisJob,
  AnalysisJobDetail,
  CrossCheck,
  DashboardSummary,
  FastpData,
  FastpParams,
  FastqcData,
  FiltlongRequest,
  HeaderSummary,
  ImportListing,
  ImportRoot,
  Library,
  MetadataApplyResult,
  MetadataImportMode,
  MetadataImportRecord,
  MetadataPreview,
  MetadataTableOptions,
  MultiqcPlan,
  Project,
  ProjectInput,
  QcOverview,
  RawFile,
  Sample,
  SampleInput,
  StorageCapacity,
  Tool,
  UploadResult,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { loc?: string[]; msg: string }) => `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg}`).join("; ");
    }
  } catch {
    /* non-JSON error body */
  }
  return `${res.status} ${res.statusText}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init);
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export interface UploadProgress {
  loaded: number;
  total: number;
}

/** Multipart upload with progress reporting (fetch has no upload progress events). */
function uploadFiles(sampleId: string, files: File[], onProgress?: (p: UploadProgress) => void) {
  return new Promise<UploadResult>((resolve, reject) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/samples/${sampleId}/files`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => onProgress?.({ loaded: e.loaded, total: e.total });
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as UploadResult);
      else reject(new ApiError(xhr.status, xhr.response?.detail ?? `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
    xhr.send(form);
  });
}

/** The multipart body of a metadata preview or apply: the table plus the choices made so far. */
export function metadataForm(file: File, options: MetadataTableOptions, extra: Record<string, string> = {}) {
  const form = new FormData();
  form.append("file", file, file.name);
  if (options.sheet) form.append("sheet", options.sheet);
  if (options.headerRow) form.append("header_row", String(options.headerRow));
  if (options.delimiter) form.append("delimiter", options.delimiter);
  if (options.dateOrder) form.append("date_order", options.dateOrder);
  if (options.mapping && Object.keys(options.mapping).length > 0) form.append("mapping", JSON.stringify(options.mapping));
  for (const [k, v] of Object.entries(extra)) form.append(k, v);
  return form;
}

export const api = {
  dashboard: () => request<DashboardSummary>("/dashboard"),

  projects: () => request<Project[]>("/projects"),
  project: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (input: ProjectInput) => request<Project>("/projects", json("POST", input)),
  updateProject: (id: string, input: Partial<ProjectInput>) =>
    request<Project>(`/projects/${id}`, json("PATCH", input)),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),

  allSamples: () => request<Sample[]>("/samples"),
  samples: (projectId: string) => request<Sample[]>(`/projects/${projectId}/samples`),
  sample: (id: string) => request<Sample>(`/samples/${id}`),
  createSample: (projectId: string, input: SampleInput) =>
    request<Sample>(`/projects/${projectId}/samples`, json("POST", input)),
  updateSample: (id: string, input: Partial<SampleInput>) =>
    request<Sample>(`/samples/${id}`, json("PATCH", input)),

  previewMetadata: (projectId: string, file: File, options: MetadataTableOptions) =>
    request<MetadataPreview>(`/projects/${projectId}/metadata/preview`, { method: "POST", body: metadataForm(file, options) }),
  applyMetadata: (projectId: string, file: File, options: MetadataTableOptions, sha256: string, mode: MetadataImportMode) =>
    request<MetadataApplyResult>(`/projects/${projectId}/metadata/apply`, {
      method: "POST",
      body: metadataForm(file, options, { expected_sha256: sha256, mode }),
    }),
  metadataImports: (projectId: string) => request<MetadataImportRecord[]>(`/projects/${projectId}/metadata/imports`),
  metadataExportUrl: (projectId: string, format: "csv" | "xlsx") => `${BASE}/projects/${projectId}/metadata/export?format=${format}`,
  metadataTemplateUrl: (format: "csv" | "xlsx") => `${BASE}/metadata/template?format=${format}`,

  files: (sampleId: string) => request<RawFile[]>(`/samples/${sampleId}/files`),
  headerSummary: (sampleId: string) => request<HeaderSummary>(`/samples/${sampleId}/header-summary`),
  uploadFiles,

  storage: () => request<StorageCapacity>("/system/storage"),
  importRoots: () => request<ImportRoot[]>("/imports/roots"),
  browseImport: (root: number, path: string) =>
    request<ImportListing>(`/imports/browse?${new URLSearchParams({ root: String(root), path })}`),
  importFromServer: (sampleId: string, body: { root: number; paths: string[] }) =>
    request<AnalysisJob>(`/samples/${sampleId}/files/import-server`, json("POST", body)),

  startSequenceStats: (
    sampleId: string,
    body: { raw_file_ids?: string[]; length_bins?: number; expected_genome_size_bp?: number | null },
  ) => request<AnalysisJob[]>(`/samples/${sampleId}/analyses/sequence-stats`, json("POST", body)),
  sampleJobs: (sampleId: string) => request<AnalysisJobDetail[]>(`/samples/${sampleId}/jobs`),
  job: (id: string) => request<AnalysisJobDetail>(`/jobs/${id}`),

  reportUrl: (sampleId: string, format: "html" | "json" | "csv") =>
    `${BASE}/samples/${sampleId}/report?format=${format}`,
  fileDownloadUrl: (fileId: string) => `${BASE}/files/${fileId}/download`,

  tools: (refresh = false) => request<Tool[]>(`/tools${refresh ? "?refresh=true" : ""}`),
  libraries: () => request<Library[]>("/tools/libraries"),
  runPod5Summary: (sampleId: string, fileIds: string[]) =>
    request<AnalysisJob[]>(`/samples/${sampleId}/analyses/pod5`, json("POST", { raw_file_ids: fileIds })),
  runPerFileTool: (sampleId: string, tool: "seqkit" | "fastqc", fileIds: string[]) =>
    request<AnalysisJob[]>(`/samples/${sampleId}/analyses/${tool}`, json("POST", { raw_file_ids: fileIds })),
  runNanoplot: (sampleId: string, fileIds: string[], longReadsConfirmed: boolean) =>
    request<AnalysisJob[]>(`/samples/${sampleId}/analyses/nanoplot`, json("POST", { raw_file_ids: fileIds, long_reads_confirmed: longReadsConfirmed })),
  runFastp: (sampleId: string, body: { read1_file_id: string; read2_file_id?: string | null; params: FastpParams }) =>
    request<AnalysisJob>(`/samples/${sampleId}/filtering/fastp`, json("POST", body)),
  runFiltlong: (sampleId: string, body: FiltlongRequest) =>
    request<AnalysisJob>(`/samples/${sampleId}/filtering/filtlong`, json("POST", body)),
  crosscheck: (fileId: string) => request<CrossCheck>(`/files/${fileId}/crosscheck`),
  fastqcData: (jobId: string) => request<FastqcData>(`/jobs/${jobId}/fastqc-data`),
  fastpData: (jobId: string) => request<FastpData>(`/jobs/${jobId}/fastp-data`),
  projectJobs: (projectId: string) => request<AnalysisJob[]>(`/projects/${projectId}/jobs`),
  qcOverview: (projectId: string) => request<QcOverview>(`/projects/${projectId}/qc-overview`),
  qcOverviewCsvUrl: (projectId: string) => `${BASE}/projects/${projectId}/qc-overview.csv`,
  multiqcPreview: (projectId: string, body: { sample_ids?: string[]; include_derived: boolean }) =>
    request<MultiqcPlan>(`/projects/${projectId}/analyses/multiqc/preview`, json("POST", body)),
  runMultiqc: (projectId: string, body: { sample_ids?: string[]; include_derived: boolean }) =>
    request<AnalysisJob>(`/projects/${projectId}/analyses/multiqc`, json("POST", body)),
  jobOutputUrl: (jobId: string, name: string, download = false) =>
    `${BASE}/jobs/${jobId}/outputs/${encodeURIComponent(name)}${download ? "?download=true" : ""}`,
};
