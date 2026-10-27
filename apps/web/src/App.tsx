import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { DashboardPage } from "@/pages/DashboardPage";
import { GuidePage } from "@/pages/GuidePage";
import { ImportPage } from "@/pages/ImportPage";
import { NotFoundPage, PlannedModulePage } from "@/pages/PlannedModulePage";
import { ProjectDetailPage } from "@/pages/ProjectDetailPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { SampleDetailPage } from "@/pages/SampleDetailPage";
import { SamplesPage } from "@/pages/SamplesPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { ToolsPage } from "@/pages/ToolsPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } },
});

export const routes = [
  {
    path: "/",
    element: <AppShell />,
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
      { path: "modules/:key", element: <PlannedModulePage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

const router = createBrowserRouter(routes);

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
