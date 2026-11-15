import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, PointerEvent as ReactPointerEvent } from "react";
import { api, errorMessage } from "./api";
import type {
  CredentialSummary,
  JsonObject,
  NodeCatalogEntry,
  Run,
  RunEvent,
  Workflow,
  WorkflowNode,
} from "./types";
import { FlowCanvas } from "./components/FlowCanvas";
import { HelpPage } from "./components/HelpPage";
import { Inspector } from "./components/Inspector";
import { NodePalette } from "./components/NodePalette";
import { RunPanel } from "./components/RunPanel";
import { WorkflowLibrary } from "./components/WorkflowLibrary";
import { WorkflowList } from "./components/WorkflowList";

type IncomingEvent = RunEvent | { type: "snapshot"; run: Run };

function logsFromRun(run: Run): string[] {
  return run.nodeRuns.flatMap((node) =>
    node.logs.map((line) => `[${node.nodeId.slice(0, 6)}] ${line}`),
  );
}

function comparable(workflow: Workflow): string {
  return JSON.stringify({
    name: workflow.name,
    description: workflow.description ?? "",
    active: workflow.active,
    nodes: workflow.nodes,
    connections: workflow.connections,
  });
}

export function App() {
  const [catalog, setCatalog] = useState<NodeCatalogEntry[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<CredentialSummary[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [activeChildRunId, setActiveChildRunId] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sample, setSample] = useState("");
  const [credName, setCredName] = useState("");
  const [credType, setCredType] = useState("ai");
  const [credData, setCredData] = useState('{\n  "baseUrl": "https://api.openai.com/v1",\n  "apiKey": "",\n  "model": "gpt-4o-mini"\n}');
  const [credError, setCredError] = useState<string | null>(null);
  const [runHeight, setRunHeight] = useState<number>(() => {
    const stored = Number(window.localStorage.getItem("customN8n.runHeight"));
    return Number.isFinite(stored) && stored >= 160 ? stored : 300;
  });
  const [runCollapsed, setRunCollapsed] = useState<boolean>(
    () => window.localStorage.getItem("customN8n.runCollapsed") === "1",
  );
  const runResize = useRef<{ startY: number; startHeight: number } | null>(null);

  const eventSource = useRef<EventSource | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [nodeCatalog, workflowList, credentialList] = await Promise.all([
          api.nodes(),
          api.workflows(),
          api.credentials(),
        ]);
        setCatalog(nodeCatalog);
        setWorkflows(workflowList);
        setCredentials(credentialList);
        if (workflowList.length > 0) {
          setWorkflow(workflowList[0] ?? null);
        }
      } catch (loadError) {
        setError(errorMessage(loadError));
      }
    })();
  }, []);

  useEffect(
    () => () => {
      eventSource.current?.close();
    },
    [],
  );

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 3500);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const selectedNode = useMemo(
    () => workflow?.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [workflow, selectedNodeId],
  );
  const selectedDefinition = useMemo(
    () => catalog.find((entry) => entry.type === selectedNode?.type),
    [catalog, selectedNode],
  );
  const selectedNodeRun = useMemo(
    () => run?.nodeRuns.find((entry) => entry.nodeId === selectedNodeId),
    [run, selectedNodeId],
  );
  const dirty = useMemo(() => {
    if (!workflow) return false;
    const saved = workflows.find((entry) => entry.id === workflow.id);
    return saved ? comparable(saved) !== comparable(workflow) : false;
  }, [workflow, workflows]);

  const selectWorkflow = useCallback((next: Workflow) => {
    eventSource.current?.close();
    eventSource.current = null;
    setWorkflow(next);
    setSelectedNodeId(null);
    setRun(null);
    setLogs([]);
    setSample("");
  }, []);

  const saveWorkflow = useCallback(async (): Promise<Workflow | null> => {
    if (!workflow) return null;
    try {
      const saved = await api.updateWorkflow(workflow);
      setWorkflow(saved);
      setWorkflows((previous) =>
        previous.map((entry) => (entry.id === saved.id ? saved : entry)),
      );
      setError(null);
      return saved;
    } catch (saveError) {
      setError(errorMessage(saveError));
      return null;
    }
  }, [workflow]);

  const applyEvent = useCallback((event: IncomingEvent) => {
    if ("childRunId" in event && event.childRunId) {
      setActiveChildRunId(event.childRunId);
    }
    switch (event.type) {
      case "snapshot":
        setRun(event.run);
        setLogs(logsFromRun(event.run));
        break;
      case "run.start":
        setRun(event.run);
        break;
      case "run.end":
        setRun(event.run);
        setLogs(logsFromRun(event.run));
        eventSource.current?.close();
        eventSource.current = null;
        break;
      case "node.start":
        setRun((previous) => {
          if (!previous) return previous;
          const nodeRun = {
            nodeId: event.nodeId,
            name: event.nodeName,
            type: event.nodeType,
            status: "running" as const,
            startedAt: new Date().toISOString(),
            itemsIn: 0,
            itemsOut: 0,
            logs: [],
          };
          const exists = previous.nodeRuns.some((entry) => entry.nodeId === event.nodeId);
          return {
            ...previous,
            nodeRuns: exists
              ? previous.nodeRuns.map((entry) =>
                  entry.nodeId === event.nodeId ? nodeRun : entry,
                )
              : [...previous.nodeRuns, nodeRun],
          };
        });
        break;
      case "node.end":
        setRun((previous) => {
          if (!previous) return previous;
          const exists = previous.nodeRuns.some(
            (entry) => entry.nodeId === event.nodeRun.nodeId,
          );
          return {
            ...previous,
            nodeRuns: exists
              ? previous.nodeRuns.map((entry) =>
                  entry.nodeId === event.nodeRun.nodeId ? event.nodeRun : entry,
                )
              : [...previous.nodeRuns, event.nodeRun],
          };
        });
        break;
      case "log":
        setLogs((previous) => [
          ...previous,
          `[${event.nodeId?.slice(0, 6) ?? "engine"}] ${event.message}`,
        ]);
        break;
      default:
        break;
    }
  }, []);

  const subscribeToRun = useCallback(
    (runId: string) => {
      eventSource.current?.close();
      eventSource.current = null;
      setRun(null);
      setLogs([]);
      setActiveChildRunId(null);

      const source = new EventSource(`/api/runs/${runId}/events`);
      eventSource.current = source;
      const listener = (message: MessageEvent) => {
        try {
          applyEvent(JSON.parse(message.data) as IncomingEvent);
        } catch {
          /* ignore malformed event */
        }
      };
      for (const name of ["snapshot", "run.start", "run.end", "node.start", "node.end", "log"]) {
        source.addEventListener(name, listener as unknown as EventListener);
      }
      source.onerror = () => {
        if (source.readyState === EventSource.CLOSED) {
          eventSource.current = null;
        }
      };
    },
    [applyEvent],
  );

  const handleRun = useCallback(async () => {
    if (!workflow) return;
    setStarting(true);
    setError(null);
    setLogs([]);
    setRun(null);
    setActiveChildRunId(null);
    eventSource.current?.close();
    eventSource.current = null;
    try {
      const saved = await saveWorkflow();
      if (!saved) return;
      let data: unknown;
      if (sample.trim()) {
        try {
          data = JSON.parse(sample);
        } catch {
          throw new Error("Test payload is not valid JSON");
        }
      }
      const { runId } = await api.runWorkflow(saved.id, data);
      subscribeToRun(runId);
    } catch (runError) {
      setError(errorMessage(runError));
    } finally {
      setStarting(false);
    }
  }, [sample, saveWorkflow, subscribeToRun, workflow]);

  const handleRetryNode = useCallback(
    async (nodeId: string) => {
      if (!run) return;
      try {
        const targetRunId = activeChildRunId ?? run.id;
        const { runId } = await api.retryNode(targetRunId, nodeId);
        subscribeToRun(runId);
      } catch (retryError) {
        setError(errorMessage(retryError));
      }
    },
    [activeChildRunId, run, subscribeToRun],
  );

  const handleCancel = useCallback(async () => {
    if (!run) return;
    try {
      await api.cancelRun(run.id);
    } catch (cancelError) {
      setError(errorMessage(cancelError));
    }
  }, [run]);

  const updateNode = useCallback((id: string, patch: Partial<WorkflowNode>) => {
    setWorkflow((previous) =>
      previous
        ? {
            ...previous,
            nodes: previous.nodes.map((node) =>
              node.id === id ? { ...node, ...patch } : node,
            ),
          }
        : previous,
    );
  }, []);

  const addNode = useCallback(
    (type: string) => {
      const definition = catalog.find((entry) => entry.type === type);
      if (!definition) return;
      const parameters: JsonObject = {};
      for (const property of definition.properties) {
        if (property.default !== undefined) {
          parameters[property.name] = property.default;
        }
      }
      const count = workflow?.nodes.length ?? 0;
      const node: WorkflowNode = {
        id: crypto.randomUUID(),
        type,
        name: definition.displayName,
        position: {
          x: 120 + (count % 3) * 220,
          y: 120 + Math.floor(count / 3) * 140,
        },
        parameters,
      };
      setWorkflow((previous) =>
        previous ? { ...previous, nodes: [...previous.nodes, node] } : previous,
      );
      setSelectedNodeId(node.id);
    },
    [catalog, workflow?.nodes.length],
  );

  const deleteNodes = useCallback(
    (ids: string[]) => {
      setWorkflow((previous) =>
        previous
          ? {
              ...previous,
              nodes: previous.nodes.filter((node) => !ids.includes(node.id)),
              connections: previous.connections.filter(
                (connection) =>
                  !ids.includes(connection.from) && !ids.includes(connection.to),
              ),
            }
          : previous,
      );
      setSelectedNodeId((previous) =>
        previous && ids.includes(previous) ? null : previous,
      );
    },
    [],
  );

  const moveNode = useCallback((id: string, position: { x: number; y: number }) => {
    setWorkflow((previous) =>
      previous
        ? {
            ...previous,
            nodes: previous.nodes.map((node) =>
              node.id === id ? { ...node, position } : node,
            ),
          }
        : previous,
    );
  }, []);

  const changeConnections = useCallback((connections: Workflow["connections"]) => {
    setWorkflow((previous) => (previous ? { ...previous, connections } : previous));
  }, []);

  const handleSelectWorkflow = useCallback(
    (id: string) => {
      if (dirty && !window.confirm("Discard unsaved changes?")) return;
      const next = workflows.find((entry) => entry.id === id);
      if (next) selectWorkflow(next);
    },
    [dirty, selectWorkflow, workflows],
  );

  const handleNewWorkflow = useCallback(async () => {
    if (dirty && !window.confirm("Discard unsaved changes?")) return;
    try {
      const created = await api.createWorkflow("New workflow");
      setWorkflows((previous) => [created, ...previous]);
      selectWorkflow(created);
    } catch (createError) {
      setError(errorMessage(createError));
    }
  }, [dirty, selectWorkflow]);

  const handleDeleteWorkflow = useCallback(
    async (id: string) => {
      if (!window.confirm("Delete this workflow?")) return;
      try {
        await api.deleteWorkflow(id);
        const remaining = workflows.filter((entry) => entry.id !== id);
        setWorkflows(remaining);
        if (workflow?.id === id) {
          if (remaining[0]) selectWorkflow(remaining[0]);
          else {
            setWorkflow(null);
            setSelectedNodeId(null);
          }
        }
      } catch (deleteError) {
        setError(errorMessage(deleteError));
      }
    },
    [selectWorkflow, workflow?.id, workflows],
  );

  const handleImportFile = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) return;
      try {
        const parsed = JSON.parse(await file.text());
        const imported = await api.importWorkflow(parsed);
        setWorkflows((previous) => [imported, ...previous]);
        selectWorkflow(imported);
        setShowLibrary(false);
      } catch (importError) {
        setError(errorMessage(importError));
      }
    },
    [selectWorkflow],
  );

  const handleSave = useCallback(async (): Promise<Workflow | null> => {
    const saved = await saveWorkflow();
    if (saved) {
      setNotice(`Changes applied: ${saved.name}`);
    }
    return saved;
  }, [saveWorkflow]);

  const handleSaveWorkflowCopy = useCallback(async (): Promise<Workflow | null> => {
    if (!workflow) return null;
    const name = window.prompt(
      "Save workflow as (copy with all settings)",
      `${workflow.name} (saved)`,
    );
    if (!name || !name.trim()) return null;
    try {
      const saved = await api.importWorkflow({
        name: name.trim(),
        description: workflow.description ?? "",
        active: workflow.active,
        nodes: workflow.nodes,
        connections: workflow.connections,
      });
      setWorkflows((previous) => [saved, ...previous]);
      setNotice(`Workflow saved to My workflows: ${saved.name}`);
      return saved;
    } catch (saveError) {
      setError(errorMessage(saveError));
      return null;
    }
  }, [workflow]);

  const handleImportExample = useCallback(
    async (payload: unknown) => {
      try {
        const imported = await api.importWorkflow(payload);
        setWorkflows((previous) => [imported, ...previous]);
        selectWorkflow(imported);
        setShowHelp(false);
        setShowLibrary(false);
        setError(null);
      } catch (importError) {
        setError(errorMessage(importError));
      }
    },
    [selectWorkflow],
  );

  const refreshCredentials = useCallback(async () => {
    try {
      setCredentials(await api.credentials());
    } catch (credentialError) {
      setError(errorMessage(credentialError));
    }
  }, []);

  const handleAddCredential = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      setCredError(null);
      let data: Record<string, unknown>;
      try {
        const parsed = JSON.parse(credData);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Credential data must be a JSON object");
        }
        data = parsed as Record<string, unknown>;
      } catch (parseError) {
        setCredError(errorMessage(parseError));
        return;
      }
      try {
        await api.createCredential(credName.trim() || "credential", credType, data);
        setCredName("");
        await refreshCredentials();
      } catch (createError) {
        setCredError(errorMessage(createError));
      }
    },
    [credData, credName, credType, refreshCredentials],
  );

  const handleDeleteCredential = useCallback(
    async (id: string) => {
      if (!window.confirm("Delete this credential?")) return;
      try {
        await api.deleteCredential(id);
        await refreshCredentials();
      } catch (deleteError) {
        setError(errorMessage(deleteError));
      }
    },
    [refreshCredentials],
  );

  const handleRunResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (runCollapsed) return;
      runResize.current = { startY: event.clientY, startHeight: runHeight };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [runCollapsed, runHeight],
  );

  const handleRunResizeMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!runResize.current) return;
    const delta = runResize.current.startY - event.clientY;
    const maxHeight = Math.max(260, window.innerHeight - 220);
    const next = Math.min(
      Math.max(runResize.current.startHeight + delta, 160),
      maxHeight,
    );
    setRunHeight(next);
  }, []);

  const handleRunResizeEnd = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!runResize.current) return;
    runResize.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setRunHeight((current) => {
      window.localStorage.setItem("customN8n.runHeight", String(current));
      return current;
    });
  }, []);

  const toggleRunCollapsed = useCallback(() => {
    setRunCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("customN8n.runCollapsed", next ? "1" : "0");
      return next;
    });
  }, []);

  const status = starting ? "starting" : (run?.status ?? "idle");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          TestOps <span>n8n</span>
        </div>
        {workflow ? (
          <input
            className="title-input"
            value={workflow.name}
            onChange={(event) =>
              setWorkflow((previous) =>
                previous ? { ...previous, name: event.target.value } : previous,
              )
            }
          />
        ) : (
          <span className="muted">no workflow</span>
        )}
        {dirty && <span className="dirty-dot" title="Unsaved changes" />}
        {workflow && (
          <label className="switch-row small">
            <input
              type="checkbox"
              checked={workflow.active}
              onChange={(event) =>
                setWorkflow((previous) =>
                  previous ? { ...previous, active: event.target.checked } : previous,
                )
              }
            />
            <span>active</span>
          </label>
        )}
        <div className="topbar-actions">
          <button
            onClick={() => {
              setShowHelp(true);
              setShowLibrary(false);
            }}
          >
            Guide
          </button>
          <button
            onClick={() => {
              setShowLibrary(true);
              setShowHelp(false);
            }}
          >
            Library
          </button>
          <button onClick={() => fileInput.current?.click()}>Import</button>
          <button
            onClick={() => void handleSaveWorkflowCopy()}
            disabled={!workflow}
            title="Save a copy with all settings to My workflows"
          >
            Save workflow
          </button>
          <button
            onClick={() => void handleSave()}
            disabled={!workflow}
            title="Apply current changes to this workflow"
          >
            Save
          </button>
          <button
            className="primary"
            onClick={() => void handleRun()}
            disabled={!workflow || starting || run?.status === "running"}
          >
            {starting ? "Starting…" : "Run"}
          </button>
          {run?.status === "running" && (
            <button className="danger" onClick={() => void handleCancel()}>
              Cancel
            </button>
          )}
          <span className={`status-pill ${status}`}>{status}</span>
        </div>
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(event) => void handleImportFile(event)}
        />
      </header>

      {error && (
        <div className="error-banner">
          <span>{error}</span>
          <button className="icon-button" onClick={() => setError(null)}>
            ×
          </button>
        </div>
      )}

      {notice && (
        <div className="notice-banner">
          <span>{notice}</span>
          <button className="icon-button" onClick={() => setNotice(null)}>
            ×
          </button>
        </div>
      )}

      {showHelp ? (
        <HelpPage
          onClose={() => setShowHelp(false)}
          onImportWorkflow={handleImportExample}
        />
      ) : showLibrary ? (
        <WorkflowLibrary
          workflows={workflows}
          currentWorkflowId={workflow?.id ?? null}
          onOpen={(selected) => {
            selectWorkflow(selected);
            setShowLibrary(false);
          }}
          onDelete={(id) => handleDeleteWorkflow(id)}
          onSaveCurrent={handleSave}
          onSaveAsCopy={handleSaveWorkflowCopy}
          onBack={() => setShowLibrary(false)}
        />
      ) : (
        <>
      <main className="workspace">
        <aside className="sidebar">
          <WorkflowList
            workflows={workflows}
            currentId={workflow?.id ?? null}
            onSelect={handleSelectWorkflow}
            onNew={() => void handleNewWorkflow()}
            onDelete={(id) => void handleDeleteWorkflow(id)}
          />
          <NodePalette catalog={catalog} onAdd={addNode} />
          <section className="credentials">
            <h3>Credentials</h3>
            <form onSubmit={(event) => void handleAddCredential(event)}>
              <input
                className="field-input"
                placeholder="Name"
                value={credName}
                onChange={(event) => setCredName(event.target.value)}
              />
              <select
                className="field-input"
                value={credType}
                onChange={(event) => setCredType(event.target.value)}
              >
                <option value="ai">ai</option>
                <option value="opencode">opencode</option>
                <option value="deepseek">deepseek</option>
                <option value="anthropic">anthropic</option>
                <option value="http">http</option>
                <option value="slack">slack</option>
                <option value="telegram">telegram</option>
                <option value="confluence">confluence</option>
                <option value="jira">jira</option>
              </select>
              <textarea
                className="field-input mono"
                rows={6}
                value={credData}
                onChange={(event) => setCredData(event.target.value)}
              />
              <button type="submit">Add credential</button>
              {credError && <span className="field-hint error">{credError}</span>}
            </form>
            <ul className="credential-list">
              {credentials.map((credential) => (
                <li key={credential.id}>
                  <span>
                    {credential.name} <small>{credential.type}</small>
                  </span>
                  <button
                    className="icon-button subtle"
                    onClick={() => void handleDeleteCredential(credential.id)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </aside>

        <section className="canvas-panel">
          {workflow ? (
            <FlowCanvas
              workflow={workflow}
              catalog={catalog}
              run={run}
              selectedNodeId={selectedNodeId}
              onSelectNode={setSelectedNodeId}
              onNodeMove={moveNode}
              onDeleteNodes={deleteNodes}
              onConnectionsChange={changeConnections}
              onRetryNode={(nodeId) => void handleRetryNode(nodeId)}
            />
          ) : (
            <div className="empty-state">Create or import a workflow to start.</div>
          )}
        </section>

        <aside className="inspector-panel">
          <Inspector
            node={selectedNode}
            definition={selectedDefinition}
            credentials={credentials}
            nodeRun={selectedNodeRun}
            onChange={updateNode}
            onDelete={(id) => deleteNodes([id])}
          />
        </aside>
      </main>

      <div
        className={`run-dock ${runCollapsed ? "is-collapsed" : ""}`}
        style={runCollapsed ? undefined : { height: runHeight }}
      >
        <div
          className="run-resizer"
          onPointerDown={handleRunResizeStart}
          onPointerMove={handleRunResizeMove}
          onPointerUp={handleRunResizeEnd}
          onPointerCancel={handleRunResizeEnd}
          onDoubleClick={toggleRunCollapsed}
          title="Drag to resize · double-click to collapse"
        >
          <span className="run-resizer-grip" />
        </div>
        <RunPanel
          run={run}
          logs={logs}
          starting={starting}
          sample={sample}
          collapsed={runCollapsed}
          onToggleCollapsed={toggleRunCollapsed}
          onSampleChange={setSample}
          onRun={() => void handleRun()}
          onCancel={() => void handleCancel()}
        />
      </div>
        </>
      )}
    </div>
  );
}
