import { translator } from "@/i18n";
import { messageText } from "@/lib/messages";
import { useSettings } from "@/store/settings";
import type {
  MlstOverview,
  MlstPlan,
  MlstProjectOverview,
  MlstRequest,
  MlstResult,
  NcbiFilters,
  NcbiPlan,
  SpeciesMethod,
  SpeciesOverview,
  SpeciesPlan,
  SpeciesProjectOverview,
  SpeciesRequest,
  SpeciesResult,
  Annotation,
  AnnotationCharts,
  AnnotationExportFormat,
  AnnotationFeatureDetail,
  AnnotationFeaturePage,
  AnnotationListRow,
  AnnotationPlan,
  AnnotationRegion,
  FeatureLayout,
  GenomeMap,
  GenomeSequence,
  GenomeTracks,
  BaktaRequest,
  FeatureQuery,
  ProkkaRequest,
  AnalysisJob,
  AnalysisJobDetail,
  Assembly,
  BatchQcPlan,
  BatchQcRequest,
  AssemblyDetail,
  AssemblyGraph,
  BrowseListing,
  CatalogueEntry,
  CrossCheck,
  DatabaseKind,
  DatabaseLocations,
  DatabaseUsage,
  DetectResult,
  DownloadPlan,
  ExtractPlan,
  DashboardSummary,
  FastpData,
  FastpParams,
  FastqcData,
  FiltlongRequest,
  FlyePlan,
  FlyeRequest,
  ShortReadInputs,
  ShortReadPlan,
  SpadesRequest,
  UnicyclerInputs,
  UnicyclerPlan,
  UnicyclerRequest,
  HeaderSummary,
  LongReadPreset,
  PolishingPlan,
  PolishingRequest,
  ImportListing,
  ImportRoot,
  PerformanceOverview,
  PerformanceUpdate,
  Library,
  MetadataApplyResult,
  MetadataImportMode,
  MetadataImportRecord,
  MetadataPreview,
  MetadataTableOptions,
  MultiqcPlan,
  Project,
  ProjectAssembly,
  ProjectInput,
  QcOverview,
  QuastPlan,
  QuastRequest,
  RawFile,
  ReferenceDatabase,
  Sample,
  SampleInput,
  MetadataBackups,
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

/** A refusal the API names with a code (`{detail, code, params}`, e.g. a disk that is not connected), in the interface
 * language when this version knows the code (`api.error.<code>`); otherwise the server's English text. */
export function codedError(body: unknown): string | null {
  const b = body as { detail?: unknown; code?: unknown; params?: unknown } | null;
  if (!b || typeof b.code !== "string" || typeof b.detail !== "string") return null;
  const params = (b.params && typeof b.params === "object" ? b.params : {}) as Record<string, string | number>;
  return messageText(translator(useSettings.getState().language), "api.error", { code: b.code, params, text: b.detail });
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const coded = codedError(body);
    if (coded) return coded;
    if (typeof body.detail === "string") return body.detail;
    if (typeof body.detail?.message === "string") return body.detail.message;
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

async function requestText(path: string): Promise<{ text: string; source: string | null }> {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return { text: await res.text(), source: res.headers.get("X-ARVA-Log-Source") };
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
      else reject(new ApiError(xhr.status, codedError(xhr.response) ?? xhr.response?.detail ?? translator(useSettings.getState().language)("import.uploadFailed", { status: xhr.status })));
    };
    xhr.onerror = () => reject(new ApiError(0, translator(useSettings.getState().language)("import.networkError")));
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
  adoptStorage: () => request<StorageCapacity>("/system/storage/adopt", json("POST", { confirm: true })),
  requestBackup: () => request<MetadataBackups>("/system/backups", { method: "POST" }),
  performance: () => request<PerformanceOverview>("/system/performance"),
  setPerformance: (body: PerformanceUpdate) => request<PerformanceOverview>("/system/performance", json("PUT", body)),
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
  databaseKinds: () => request<DatabaseKind[]>("/databases/kinds"),
  databaseCatalogue: () => request<CatalogueEntry[]>("/databases/catalogue"),
  databases: () => request<ReferenceDatabase[]>("/databases"),
  database: (id: string) => request<ReferenceDatabase>(`/databases/${id}`),
  databaseUsage: () => request<DatabaseUsage>("/databases/usage"),
  databaseLocations: () => request<DatabaseLocations>("/databases/locations"),
  browseDatabases: (root: string, path: string) => request<BrowseListing>(`/databases/browse?${new URLSearchParams({ root, path })}`),
  detectDatabase: (path: string) => request<DetectResult>(`/databases/detect?${new URLSearchParams({ path })}`),
  databasePlan: (key: string, destination?: string | null, folder?: string | null) =>
    request<DownloadPlan>(
      `/databases/catalogue/${encodeURIComponent(key)}/plan?${new URLSearchParams({ ...(destination ? { destination } : {}), ...(folder ? { folder } : {}) })}`,
    ),
  extractPlan: (path: string, destination?: string | null, folder?: string | null) =>
    request<ExtractPlan>(`/databases/extract/plan?${new URLSearchParams({ path, ...(destination ? { destination } : {}), ...(folder ? { folder } : {}) })}`),
  extractDatabase: (body: { path: string; confirm_bytes: number; collection_date: string; destination?: string | null; folder?: string | null }) =>
    request<ReferenceDatabase>("/databases/extract", json("POST", body)),
  setDefaultDatabase: (id: string) => request<ReferenceDatabase>(`/databases/${id}/default`, { method: "POST" }),
  /** `confirmBytes` repeats the archive size shown to the user; the licence must have been accepted. */
  downloadDatabase: (key: string, confirmBytes: number, acceptLicence: boolean, destination?: string | null, folder?: string | null) =>
    request<ReferenceDatabase>(
      "/databases/downloads",
      json("POST", { key, confirm_bytes: confirmBytes, accept_licence: acceptLicence, destination: destination ?? null, folder: folder ?? null }),
    ),
  registerDatabase: (body: { path: string; kind?: string | null; declared_version?: string | null; collection_date?: string | null; full_checksum?: boolean }) =>
    request<ReferenceDatabase>("/databases/register", json("POST", body)),
  verifyDatabase: (id: string, level: "quick" | "full" = "full") => request<ReferenceDatabase>(`/databases/${id}/verify`, json("POST", { level })),
  cancelDatabaseTask: (id: string) => request<ReferenceDatabase>(`/databases/${id}/cancel`, { method: "POST" }),
  deleteDatabase: (id: string) => request<void>(`/databases/${id}`, { method: "DELETE" }),
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
  /** Queued: cancelled at once. Running: the worker stops the tool within seconds (the job stays "running" until then). */
  cancelJob: (jobId: string) => request<AnalysisJob>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  /** A new Flye job continuing a stopped run from its kept work folder (Flye's --resume). */
  resumeJob: (jobId: string) => request<AnalysisJob>(`/jobs/${jobId}/resume`, { method: "POST" }),
  discardCheckpoint: (jobId: string) => request<AnalysisJob>(`/jobs/${jobId}/checkpoint`, { method: "DELETE" }),
  /** With dry_run the plan only; otherwise the plan's jobs are created (needs the preview's plan_id). */
  batchQc: (projectId: string, body: BatchQcRequest) => request<BatchQcPlan>(`/projects/${projectId}/analyses/batch`, json("POST", body)),
  /** The last lines of a job's live tool log while it exists, else of the ARVA job log (`source` says which). */
  jobLog: (jobId: string, tail = 200) => requestText(`/jobs/${jobId}/log?tail=${tail}`),
  flyePreview: (sampleId: string, body: { raw_file_ids: string[]; assumed_depth_x?: number | null }) =>
    request<FlyePlan>(`/samples/${sampleId}/assembly/flye/preview`, json("POST", body)),
  runFlye: (sampleId: string, body: FlyeRequest) =>
    request<AnalysisJob>(`/samples/${sampleId}/assembly/flye`, json("POST", body)),
  spadesPreview: (sampleId: string, inputs: ShortReadInputs) =>
    request<ShortReadPlan>(`/samples/${sampleId}/assembly/spades/preview`, json("POST", { inputs })),
  runSpades: (sampleId: string, body: SpadesRequest) =>
    request<AnalysisJob>(`/samples/${sampleId}/assembly/spades`, json("POST", body)),
  unicyclerPreview: (sampleId: string, inputs: UnicyclerInputs) =>
    request<UnicyclerPlan>(`/samples/${sampleId}/assembly/unicycler/preview`, json("POST", { inputs })),
  runUnicycler: (sampleId: string, body: UnicyclerRequest) =>
    request<AnalysisJob>(`/samples/${sampleId}/assembly/unicycler`, json("POST", body)),
  quastPreview: (sampleId: string, body: Omit<QuastRequest, "threads">) =>
    request<QuastPlan>(`/samples/${sampleId}/assembly/quast/preview`, json("POST", body)),
  runQuast: (sampleId: string, body: QuastRequest) =>
    request<AnalysisJob>(`/samples/${sampleId}/assembly/quast`, json("POST", body)),
  polishingPreview: (assemblyId: string, body: { inputs: UnicyclerInputs; read_type: LongReadPreset | null }) =>
    request<PolishingPlan>(`/assemblies/${assemblyId}/polishing/preview`, json("POST", body)),
  polish: (assemblyId: string, body: PolishingRequest) => request<AnalysisJob>(`/assemblies/${assemblyId}/polishing`, json("POST", body)),
  assemblies: (sampleId: string) => request<Assembly[]>(`/samples/${sampleId}/assemblies`),
  assembly: (id: string) => request<AssemblyDetail>(`/assemblies/${id}`),
  assemblyContigsUrl: (id: string) => `${BASE}/assemblies/${id}/contigs.fasta`,
  assemblyGraph: (id: string, maxNodes: number, maxEdges: number) =>
    request<AssemblyGraph>(`/assemblies/${id}/graph?${new URLSearchParams({ max_nodes: String(maxNodes), max_edges: String(maxEdges) })}`),
  projectAssemblies: (projectId: string) => request<ProjectAssembly[]>(`/projects/${projectId}/assemblies`),
  baktaPreview: (assemblyId: string, body: { database_id: string | null; skip_plot: boolean }) =>
    request<AnnotationPlan>(`/assemblies/${assemblyId}/annotate/bakta/preview`, json("POST", body)),
  runBakta: (assemblyId: string, body: BaktaRequest) => request<AnalysisJob>(`/assemblies/${assemblyId}/annotate/bakta`, json("POST", body)),
  prokkaPreview: (assemblyId: string, body: { rfam: boolean; use_genus: boolean; genus: string | null; rename_contigs: boolean }) =>
    request<AnnotationPlan>(`/assemblies/${assemblyId}/annotate/prokka/preview`, json("POST", body)),
  runProkka: (assemblyId: string, body: ProkkaRequest) => request<AnalysisJob>(`/assemblies/${assemblyId}/annotate/prokka`, json("POST", body)),
  annotations: (sampleId: string) => request<Annotation[]>(`/samples/${sampleId}/annotations`),
  mlstPreview: (assemblyId: string, scheme: string | null) =>
    request<MlstPlan>(`/assemblies/${assemblyId}/mlst/preview`, json("POST", { scheme })),
  runMlst: (assemblyId: string, body: MlstRequest) => request<AnalysisJob>(`/assemblies/${assemblyId}/mlst`, json("POST", body)),
  mlstResults: (sampleId: string) => request<MlstResult[]>(`/samples/${sampleId}/mlst`),
  mlstProject: (projectId: string) => request<MlstProjectOverview>(`/projects/${projectId}/mlst`),
  mlstProjectCsvUrl: (projectId: string) => `${BASE}/projects/${projectId}/mlst.csv`,
  mlstOverview: () => request<MlstOverview>("/mlst"),
  mlstFileUrl: (id: string, kind: string) => `${BASE}/mlst/${id}/files/${encodeURIComponent(kind)}`,
  speciesPreview: (assemblyId: string, method: SpeciesMethod, databaseId: string | null) =>
    request<SpeciesPlan>(`/assemblies/${assemblyId}/species/preview`, json("POST", { method, database_id: databaseId })),
  runSpecies: (assemblyId: string, body: SpeciesRequest) => request<AnalysisJob>(`/assemblies/${assemblyId}/species`, json("POST", body)),
  speciesResults: (sampleId: string) => request<SpeciesResult[]>(`/samples/${sampleId}/species`),
  speciesProject: (projectId: string) => request<SpeciesProjectOverview>(`/projects/${projectId}/species`),
  speciesProjectCsvUrl: (projectId: string) => `${BASE}/projects/${projectId}/species.csv`,
  speciesOverview: () => request<SpeciesOverview>("/species"),
  speciesFileUrl: (id: string, kind: string) => `${BASE}/species/${id}/files/${encodeURIComponent(kind)}`,
  ncbiPlan: (body: { taxon: string; tax_id: number | null; filters: NcbiFilters; destination?: string | null; folder?: string | null }) =>
    request<NcbiPlan>("/databases/ncbi/plan", json("POST", body)),
  ncbiStart: (body: { taxon: string; tax_id: number; filters: NcbiFilters; confirm_genomes: number; confirm_fingerprint: string; destination?: string | null; folder?: string | null }) =>
    request<ReferenceDatabase>("/databases/ncbi", json("POST", body)),
  annotation: (id: string) => request<Annotation>(`/annotations/${id}`),
  annotationFeatures: (id: string, q: FeatureQuery) => {
    const params = new URLSearchParams({ sort: q.sort, descending: String(q.descending), limit: String(q.limit), offset: String(q.offset) });
    q.types.forEach((t) => params.append("type", t));
    if (q.q.trim()) params.set("q", q.q.trim());
    if (q.hypothetical) params.set("hypothetical", q.hypothetical);
    if (q.contig) params.set("contig", q.contig);
    if (q.contig && q.start) params.set("start", q.start);
    if (q.contig && q.end) params.set("end", q.end);
    return request<AnnotationFeaturePage>(`/annotations/${id}/features?${params}`);
  },
  annotationFeature: (id: string, featureId: number) => request<AnnotationFeatureDetail>(`/annotations/${id}/features/${featureId}`),
  allAnnotations: () => request<AnnotationListRow[]>("/annotations"),
  annotationMap: (id: string, q: { contigs: string[]; points: number }) => {
    const params = new URLSearchParams({ points: String(q.points) });
    for (const c of q.contigs) params.append("contig", c);
    return request<GenomeMap>(`/annotations/${id}/map?${params}`);
  },
  annotationCharts: (id: string, q: { lengthBin?: number | null; window?: number | null } = {}) => {
    const params = new URLSearchParams();
    if (q.lengthBin) params.set("length_bin", String(q.lengthBin));
    if (q.window) params.set("window", String(q.window));
    return request<AnnotationCharts>(`/annotations/${id}/charts?${params}`);
  },
  annotationLayout: (id: string, contig: string) => request<FeatureLayout>(`/annotations/${id}/layout?${new URLSearchParams({ contig })}`),
  annotationTracks: (id: string, q: { contig: string; start: number; end: number; bins: number; window: number | null; step: number | null }) => {
    const params = new URLSearchParams({ contig: q.contig, start: String(q.start), end: String(q.end), bins: String(q.bins) });
    if (q.window) params.set("window", String(q.window));
    if (q.step) params.set("step", String(q.step));
    return request<GenomeTracks>(`/annotations/${id}/tracks?${params}`);
  },
  annotationSequence: (id: string, contig: string, start: number, end: number, strand: "+" | "-" = "+") =>
    request<GenomeSequence>(`/annotations/${id}/sequence?${new URLSearchParams({ contig, start: String(start), end: String(end), strand })}`),
  annotationSequenceUrl: (id: string, contig: string, start: number, end: number, strand: "+" | "-") =>
    `${BASE}/annotations/${id}/sequence?${new URLSearchParams({ contig, start: String(start), end: String(end), strand, format: "fasta" })}`,
  annotationFileUrl: (id: string, kind: string) => `${BASE}/annotations/${id}/files/${encodeURIComponent(kind)}`,
  annotationExportUrl: (id: string, format: AnnotationExportFormat) => `${BASE}/annotations/${id}/export/${format}`,
  /** Selected features, or those overlapping a region, as a file the browser saves (POST, so the ids do not go into a URL). */
  exportAnnotationFeatures: async (id: string, format: AnnotationExportFormat, selection: number[] | AnnotationRegion) => {
    const body = Array.isArray(selection) ? { format, feature_ids: selection } : { format, region: selection };
    const res = await fetch(`${BASE}/annotations/${id}/export`, json("POST", body));
    if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? `annotation_${format}.txt`;
    return { blob: await res.blob(), name };
  },
  /** `name` is a file name, or a path below the job's folder (kept with its slashes so the page's relative links work). */
  jobOutputUrl: (jobId: string, name: string, download = false) =>
    `${BASE}/jobs/${jobId}/outputs/${name.split("/").map(encodeURIComponent).join("/")}${download ? "?download=true" : ""}`,
};
