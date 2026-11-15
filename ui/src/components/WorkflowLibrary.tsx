import { useMemo, useState } from "react";
import type { Workflow } from "../types";

interface WorkflowLibraryProps {
  workflows: Workflow[];
  currentWorkflowId: string | null;
  onOpen: (workflow: Workflow) => void;
  onDelete: (id: string) => Promise<void>;
  onSaveCurrent: () => Promise<Workflow | null>;
  onSaveAsCopy: () => Promise<Workflow | null>;
  onBack: () => void;
}

function downloadWorkflow(workflow: Workflow) {
  const blob = new Blob([JSON.stringify(workflow, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${workflow.name.replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function WorkflowLibrary({
  workflows,
  currentWorkflowId,
  onOpen,
  onDelete,
  onSaveCurrent,
  onSaveAsCopy,
  onBack,
}: WorkflowLibraryProps) {
  const [saving, setSaving] = useState(false);
  const [savingCopy, setSavingCopy] = useState(false);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  const sorted = useMemo(
    () =>
      [...workflows].sort((left, right) => {
        if (left.id === currentWorkflowId) return -1;
        if (right.id === currentWorkflowId) return 1;
        return (right.updatedAt ?? "").localeCompare(left.updatedAt ?? "");
      }),
    [currentWorkflowId, workflows],
  );

  const saveCurrent = async () => {
    setSaving(true);
    setSavedMessage(null);
    try {
      const saved = await onSaveCurrent();
      if (saved) {
        setSavedMessage(`Changes applied: ${saved.name}`);
      }
    } finally {
      setSaving(false);
    }
  };

  const saveCopy = async () => {
    setSavingCopy(true);
    setSavedMessage(null);
    try {
      const saved = await onSaveAsCopy();
      if (saved) {
        setSavedMessage(`Workflow saved: ${saved.name}`);
      }
    } finally {
      setSavingCopy(false);
    }
  };

  return (
    <div className="library-page">
      <header className="library-header">
        <div>
          <h1>My workflows</h1>
          <p>
            Сохранённые workflow со всеми нодами, связями и параметрами.
            Откройте для редактирования или выгрузите JSON.
          </p>
        </div>
        <div className="library-header-actions">
          <button
            className="primary"
            disabled={saving || !currentWorkflowId}
            onClick={() => void saveCurrent()}
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            disabled={savingCopy || !currentWorkflowId}
            onClick={() => void saveCopy()}
            title="Save a copy with all settings"
          >
            {savingCopy ? "Saving…" : "Save workflow"}
          </button>
          <button onClick={onBack}>Back to editor</button>
        </div>
      </header>

      {savedMessage && <div className="library-saved">{savedMessage}</div>}

      <div className="library-grid">
        {sorted.map((workflow) => {
          const triggers = workflow.nodes.filter((node) =>
            node.type.startsWith("trigger."),
          );
          return (
            <article
              className={`library-card ${
                workflow.id === currentWorkflowId ? "is-current" : ""
              }`}
              key={workflow.id}
            >
              <div className="library-card-head">
                <h2>{workflow.name}</h2>
                <span className={`status-pill ${workflow.active ? "success" : ""}`}>
                  {workflow.active ? "active" : "inactive"}
                </span>
              </div>

              {workflow.description && (
                <p className="library-description">{workflow.description}</p>
              )}

              <div className="library-meta">
                <span>{workflow.nodes.length} nodes</span>
                <span>{workflow.connections.length} connections</span>
                <span>
                  updated{" "}
                  {workflow.updatedAt
                    ? new Date(workflow.updatedAt).toLocaleString()
                    : "—"}
                </span>
              </div>

              <div className="library-triggers">
                {triggers.length === 0 ? (
                  <span className="library-trigger">no trigger</span>
                ) : (
                  triggers.map((node) => (
                    <span className="library-trigger" key={node.id}>
                      {node.type}
                    </span>
                  ))
                )}
              </div>

              <div className="library-actions">
                <button onClick={() => onOpen(workflow)}>Open</button>
                <button onClick={() => downloadWorkflow(workflow)}>Export JSON</button>
                <button
                  className="danger"
                  onClick={() => void onDelete(workflow.id)}
                >
                  Delete
                </button>
              </div>

              <details className="library-details">
                <summary>All settings (JSON)</summary>
                <pre>{JSON.stringify(workflow, null, 2)}</pre>
              </details>
            </article>
          );
        })}
      </div>

      {sorted.length === 0 && (
        <div className="library-empty">
          Пока нет сохранённых workflow. Вернитесь в редактор и нажмите Save
          workflow.
        </div>
      )}
    </div>
  );
}
