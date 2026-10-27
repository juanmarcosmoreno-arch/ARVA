import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Tool } from "@/lib/types";

export function useTools() {
  return useQuery({ queryKey: ["tools"], queryFn: () => api.tools(), staleTime: 60_000 });
}

export function useTool(id: string): Tool | undefined {
  return useTools().data?.find((t) => t.id === id);
}
