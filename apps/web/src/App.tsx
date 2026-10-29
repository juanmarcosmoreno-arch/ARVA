import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { ErrorBoundary, RouteErrorScreen } from "@/components/diagnostics/ErrorScreen";
import { AppShell } from "@/components/layout/AppShell";
import { SplashScreen } from "@/components/layout/SplashScreen";
import { Toaster } from "@/components/layout/Toaster";
import { ApiError } from "@/lib/api";
import { DashboardPage } from "@/pages/DashboardPage";
import { ExplorerListPage, ExplorerPage } from "@/pages/ExplorerPage";
import { GenomicPage } from "@/pages/GenomicPage";
import { GuidePage } from "@/pages/GuidePage";
import { ImportPage } from "@/pages/ImportPage";
import { NotFoundPage, PlannedModulePage } from "@/pages/PlannedModulePage";
import { ProjectDetailPage } from "@/pages/ProjectDetailPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { SampleDetailPage } from "@/pages/SampleDetailPage";
import { SamplesPage } from "@/pages/SamplesPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { ToolsPage } from "@/pages/ToolsPage";
import { useToasts } from "@/store/toasts";

/** An unexpected server error (one the API kept in its error log) is also shown as a toast with its error id. */
function toastServerError(error: unknown) {
  if (error instanceof ApiError && error.errorId) useToasts.getState().push({ message: error.message, errorId: error.errorId });
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } },
  queryCache: new QueryCache({ onError: toastServerError }),
  mutationCache: new MutationCache({ onError: toastServerError }),
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
      { path: "reports", element: <SamplesPage context="reports" /> },
      { path: "guide", element: <GuidePage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "tools", element: <ToolsPage /> },
      { path: "explorer", element: <ExplorerListPage /> },
      { path: "genomic", element: <GenomicPage /> },
      { path: "explorer/:annotationId", element: <ExplorerPage /> },
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
