import type { Run } from "../types";

interface RunPanelProps {
  run: Run | null;
  logs: string[];
  starting: boolean;
  sample: string;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSampleChange: (value: string) => void;
  onRun: () => void;
  onCancel: () => void;
}

export function RunPanel({
  run,
  logs,
  starting,
  sample,
  collapsed,
  onToggleCollapsed,
  onSampleChange,
  onRun,
  onCancel,
}: RunPanelProps) {
  const running = run?.status === "running";

  return (
    <section className="run-panel">
      <div className="run-controls">
        <details className="sample-box">
          <summary>Test payload (optional)</summary>
          <textarea
            className="field-input mono"
            rows={5}
            placeholder='{"results": [ ... ]}'
            value={sample}
            onChange={(event) => onSampleChange(event.target.value)}
          />
        </details>
        <button className="primary" onClick={onRun} disabled={starting || running}>
          {starting ? "Starting…" : "Run workflow"}
        </button>
        {running && (
          <button className="danger" onClick={onCancel}>
            Cancel
          </button>
        )}
        {run && (
          <div className="run-meta">
            <span className={`status-pill ${run.status}`}>{run.status}</span>
            <span>{run.trigger}</span>
            <code>{run.id.slice(0, 8)}</code>
          </div>
        )}
        <button className="run-toggle" onClick={onToggleCollapsed}>
          {collapsed ? "Show results" : "Hide results"}
        </button>
      </div>

      <div className="run-body">
        <div className="run-nodes">
          {run ? (
            run.nodeRuns.length === 0 ? (
              <p className="muted">Waiting for nodes…</p>
            ) : (
              run.nodeRuns.map((nodeRun) => (
                <details key={nodeRun.nodeId} className={`run-node status-${nodeRun.status}`}>
                  <summary>
                    <span className="run-node-name">{nodeRun.name}</span>
                    <span className={`chip ${nodeRun.status}`}>{nodeRun.status}</span>
                    <span className="muted">
                      in {nodeRun.itemsIn} / out {nodeRun.itemsOut}
                    </span>
                  </summary>
                  {nodeRun.error && <pre className="error-text">{nodeRun.error}</pre>}
                  {nodeRun.logs.length > 0 && (
                    <pre className="log-text">{nodeRun.logs.join("\n")}</pre>
                  )}
                  <pre className="log-text">{JSON.stringify(nodeRun.output, null, 2)}</pre>
                </details>
              ))
            )
          ) : (
            <p className="muted">Run the workflow to see node results here.</p>
          )}
          {run?.error && <pre className="error-text">{run.error}</pre>}
        </div>

        <pre className="run-logs">{logs.slice(-200).join("\n") || "Live logs will appear here."}</pre>
      </div>
    </section>
  );
}
