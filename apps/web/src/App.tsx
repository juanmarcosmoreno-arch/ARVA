import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { ErrorBoundary, RouteErrorScreen } from "@/components/diagnostics/ErrorScreen";
import { AppShell } from "@/components/layout/AppShell";
import { SplashScreen } from "@/components/layout/SplashScreen";
import { Toaster } from "@/components/layout/Toaster";
import { apiAnswered, toastServerError } from "@/lib/apiToasts";
import { ComparativePage } from "@/pages/ComparativePage";
import { DashboardPage } from "@/pages/DashboardPage";
import { DiscoverPage } from "@/pages/DiscoverPage";
import { ExplorerListPage, ExplorerPage } from "@/pages/ExplorerPage";
import { GenomicPage } from "@/pages/GenomicPage";
import { GuidePage } from "@/pages/GuidePage";
import { ImportPage } from "@/pages/ImportPage";
import { NotFoundPage, PlannedModulePage } from "@/pages/PlannedModulePage";
import { ProjectDetailPage } from "@/pages/ProjectDetailPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { SampleDetailPage } from "@/pages/SampleDetailPage";
import { SamplesPage } from "@/pages/SamplesPage";
import { SangerPage } from "@/pages/SangerPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { ToolsPage } from "@/pages/ToolsPage";
import { ComparePage, RunPage, WorkflowEditorPage, WorkflowsPage } from "@/pages/WorkflowsPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } },
  queryCache: new QueryCache({ onError: toastServerError, onSuccess: apiAnswered }),
  mutationCache: new MutationCache({ onError: toastServerError, onSuccess: apiAnswered }),
});

export const routes = [
  {
    path: "/",
    element: <AppShell />,
    errorElement: <RouteErrorScreen />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "projects", element: <ProjectsPage /> },
      { path: "projects/:projectId", element: <ProjectDetailPage /> },
      { path: "samples", element: <SamplesPage /> },
      { path: "samples/:sampleId", element: <SampleDetailPage /> },
      { path: "import", element: <ImportPage /> },
      { path: "qc", element: <SamplesPage context="qc" /> },
      { path: "assembly", element: <SamplesPage context="assembly" /> },
      { path: "annotation", element: <SamplesPage context="annotation" /> },
      { path: "reports", element: <SamplesPage context="reports" /> },
      { path: "guide", element: <GuidePage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "tools", element: <ToolsPage /> },
      { path: "explorer", element: <ExplorerListPage /> },
      { path: "genomic", element: <GenomicPage /> },
      { path: "sanger", element: <SangerPage /> },
      { path: "comparative", element: <ComparativePage /> },
      { path: "comparative/:setId", element: <ComparativePage /> },
      { path: "explorer/:annotationId", element: <ExplorerPage /> },
      { path: "discover", element: <DiscoverPage /> },
      { path: "discover/:projectId", element: <DiscoverPage /> },
      { path: "workflows", element: <WorkflowsPage /> },
      { path: "workflows/compare", element: <ComparePage /> },
      { path: "workflows/runs/:runId", element: <RunPage /> },
      { path: "workflows/:workflowId", element: <WorkflowEditorPage /> },
      { path: "modules/:key", element: <PlannedModulePage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

const router = createBrowserRouter(routes);

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <SplashScreen />
        <Toaster />
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
