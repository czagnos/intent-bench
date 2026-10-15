import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createWorkspaceClient } from "./api";

export type CatalogPreset = {
  id: string;
  name: string;
  description: string;
  workspace: string;
  intent_count: number;
};

const WorkspaceContext = createContext<ReturnType<typeof createWorkspaceClient> | null>(null);
export function WorkspaceProvider({ workspace, children }: { workspace: string; children: ReactNode }) {
  const client = useMemo(() => createWorkspaceClient(workspace), [workspace]);
  return <WorkspaceContext.Provider value={client}>{children}</WorkspaceContext.Provider>;
}
export function useWorkspaceApi() {
  const client = useContext(WorkspaceContext);
  if (!client) throw new Error("Workspace provider is required.");
  return client;
}
