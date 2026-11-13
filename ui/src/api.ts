import type {
  CredentialSummary,
  NodeCatalogEntry,
  Run,
  Workflow,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  nodes: () => request<NodeCatalogEntry[]>("/api/nodes"),
  workflows: () => request<Workflow[]>("/api/workflows"),
  workflow: (id: string) => request<Workflow>(`/api/workflows/${id}`),
  createWorkflow: (name: string) =>
    request<Workflow>("/api/workflows", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  updateWorkflow: (workflow: Workflow) =>
    request<Workflow>(`/api/workflows/${workflow.id}`, {
      method: "PUT",
      body: JSON.stringify({
        name: workflow.name,
        description: workflow.description ?? "",
        active: workflow.active,
        nodes: workflow.nodes,
        connections: workflow.connections,
      }),
    }),
  deleteWorkflow: (id: string) =>
    request<{ deleted: boolean }>(`/api/workflows/${id}`, { method: "DELETE" }),
  importWorkflow: (workflow: unknown) =>
    request<Workflow>("/api/workflows/import", {
      method: "POST",
      body: JSON.stringify({ workflow }),
    }),
  runWorkflow: (id: string, data?: unknown, startNodeId?: string) =>
    request<{ runId: string }>(`/api/workflows/${id}/run`, {
      method: "POST",
      body: JSON.stringify({ data, startNodeId }),
    }),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  cancelRun: (id: string) =>
    request<{ canceled: boolean }>(`/api/runs/${id}/cancel`, { method: "POST" }),
  retryNode: (runId: string, nodeId: string) =>
    request<{ runId: string }>(`/api/runs/${runId}/retry/${nodeId}`, {
      method: "POST",
    }),
  credentials: () => request<CredentialSummary[]>("/api/credentials"),
  createCredential: (name: string, type: string, data: Record<string, unknown>) =>
    request<CredentialSummary>("/api/credentials", {
      method: "POST",
      body: JSON.stringify({ name, type, data }),
    }),
  deleteCredential: (id: string) =>
    request<{ deleted: boolean }>(`/api/credentials/${id}`, { method: "DELETE" }),
};

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
