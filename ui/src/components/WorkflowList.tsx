import type { Workflow } from "../types";

interface WorkflowListProps {
  workflows: Workflow[];
  currentId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function WorkflowList({
  workflows,
  currentId,
  onSelect,
  onNew,
  onDelete,
}: WorkflowListProps) {
  return (
    <section className="workflow-list">
      <div className="section-head">
        <h3>Workflows</h3>
        <button className="icon-button" onClick={onNew}>
          + New
        </button>
      </div>
      <ul>
        {workflows.map((workflow) => (
          <li key={workflow.id}>
            <button
              className={`workflow-item ${workflow.id === currentId ? "is-active" : ""}`}
              onClick={() => onSelect(workflow.id)}
            >
              <span className={`dot ${workflow.active ? "on" : "off"}`} />
              <span className="workflow-name">{workflow.name}</span>
            </button>
            <button
              className="icon-button subtle"
              title="Delete workflow"
              onClick={() => onDelete(workflow.id)}
            >
              ×
            </button>
          </li>
        ))}
        {workflows.length === 0 && <li className="muted">No workflows yet.</li>}
      </ul>
    </section>
  );
}
