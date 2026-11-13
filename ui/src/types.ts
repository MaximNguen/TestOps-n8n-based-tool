export type JsonObject = Record<string, unknown>;

export interface NodeProperty {
  name: string;
  displayName: string;
  type: "string" | "text" | "number" | "boolean" | "options" | "json" | "code" | "credential";
  default?: unknown;
  description?: string;
  required?: boolean;
  options?: Array<{ label: string; value: string }>;
  credentialType?: string;
  rows?: number;
}

export interface NodeCatalogEntry {
  type: string;
  displayName: string;
  description: string;
  group: "trigger" | "action" | "transform" | "qa";
  inputs: string[];
  outputs: string[];
  isTrigger: boolean;
  properties: NodeProperty[];
}

export interface WorkflowNode {
  id: string;
  type: string;
  name: string;
  position: { x: number; y: number };
  parameters: JsonObject;
  disabled?: boolean;
  retryMaxAttempts?: number | null;
  retryDelaySeconds?: number | null;
}

export interface Connection {
  from: string;
  to: string;
  output?: string;
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  active: boolean;
  nodes: WorkflowNode[];
  connections: Connection[];
  createdAt?: string;
  updatedAt?: string;
}

export type NodeRunStatus = "running" | "success" | "error" | "skipped";

export interface NodeRun {
  nodeId: string;
  name: string;
  type: string;
  status: NodeRunStatus;
  startedAt: string;
  finishedAt?: string;
  error?: string;
  itemsIn: number;
  itemsOut: number;
  logs: string[];
  output?: unknown;
}

export interface Run {
  id: string;
  workflowId: string;
  workflowName: string;
  status: "running" | "success" | "error" | "canceled";
  trigger: string;
  startedAt: string;
  finishedAt?: string;
  error?: string;
  nodeRuns: NodeRun[];
}

export interface CredentialSummary {
  id: string;
  name: string;
  type: string;
  createdAt: string;
  updatedAt: string;
}

export type RunEvent =
  | { type: "snapshot"; run: Run }
  | { type: "run.start"; run: Run }
  | { type: "run.end"; run: Run }
  | {
      type: "node.start";
      runId: string;
      nodeId: string;
      nodeName: string;
      nodeType: string;
      childRunId?: string;
    }
  | { type: "node.end"; runId: string; nodeRun: NodeRun; childRunId?: string }
  | {
      type: "log";
      runId: string;
      nodeId?: string;
      level: string;
      message: string;
      childRunId?: string;
    };
