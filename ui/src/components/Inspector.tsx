import { useEffect, useState } from "react";
import type {
  CredentialSummary,
  NodeCatalogEntry,
  NodeProperty,
  NodeRun,
  WorkflowNode,
} from "../types";

interface InspectorProps {
  node: WorkflowNode | null;
  definition: NodeCatalogEntry | undefined;
  credentials: CredentialSummary[];
  nodeRun: NodeRun | undefined;
  onChange: (id: string, patch: Partial<WorkflowNode>) => void;
  onDelete: (id: string) => void;
}

function formatJson(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined || value === null) return "";
  return JSON.stringify(value, null, 2);
}

function JsonField({
  value,
  rows,
  onChange,
}: {
  value: unknown;
  rows: number;
  onChange: (value: unknown) => void;
}) {
  const [text, setText] = useState(() => formatJson(value));

  useEffect(() => {
    setText(formatJson(value));
  }, [value]);

  return (
    <textarea
      className="field-input mono"
      rows={rows}
      value={text}
      onChange={(event) => setText(event.target.value)}
      onBlur={() => {
        const trimmed = text.trim();
        if (!trimmed) {
          onChange("");
          return;
        }
        try {
          onChange(JSON.parse(trimmed));
        } catch {
          onChange(text);
        }
      }}
    />
  );
}

function PropertyField({
  property,
  value,
  credentials,
  onChange,
}: {
  property: NodeProperty;
  value: unknown;
  credentials: CredentialSummary[];
  onChange: (value: unknown) => void;
}) {
  const rows = property.rows ?? 4;

  if (property.type === "boolean") {
    return (
      <label className="switch-row">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{property.displayName}</span>
      </label>
    );
  }

  if (property.type === "options") {
    return (
      <label className="field">
        <span className="field-label">{property.displayName}</span>
        <select
          className="field-input"
          value={String(value ?? "")}
          onChange={(event) => {
            const option = property.options?.find(
              (entry) => entry.value === event.target.value,
            );
            onChange(option ? option.value : event.target.value);
          }}
        >
          {(property.options ?? []).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (property.type === "credential") {
    return (
      <label className="field">
        <span className="field-label">{property.displayName}</span>
        <select
          className="field-input"
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">— none —</option>
          {credentials.map((credential) => (
            <option key={credential.id} value={credential.id}>
              {credential.name} · {credential.type}
            </option>
          ))}
        </select>
        {credentials.length === 0 && (
          <span className="field-hint">Add a credential in the left sidebar.</span>
        )}
      </label>
    );
  }

  if (property.type === "json") {
    return (
      <label className="field">
        <span className="field-label">{property.displayName}</span>
        <JsonField value={value} rows={rows} onChange={onChange} />
      </label>
    );
  }

  if (property.type === "code" || property.type === "text") {
    return (
      <label className="field">
        <span className="field-label">{property.displayName}</span>
        <textarea
          className="field-input mono"
          rows={rows}
          value={typeof value === "string" ? value : formatJson(value)}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    );
  }

  if (property.type === "number") {
    return (
      <label className="field">
        <span className="field-label">{property.displayName}</span>
        <input
          className="field-input"
          type="number"
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(event) => {
            const raw = event.target.value;
            onChange(raw === "" ? "" : Number(raw));
          }}
        />
      </label>
    );
  }

  return (
    <label className="field">
      <span className="field-label">{property.displayName}</span>
      <input
        className="field-input"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function Inspector({
  node,
  definition,
  credentials,
  nodeRun,
  onChange,
  onDelete,
}: InspectorProps) {
  if (!node) {
    return (
      <div className="inspector-empty">
        <h2>Inspector</h2>
        <p>Select a node on the canvas to edit its parameters.</p>
      </div>
    );
  }

  const parameters = node.parameters ?? {};
  const updateParameter = (name: string, value: unknown) => {
    onChange(node.id, { parameters: { ...parameters, [name]: value } });
  };

  const webhookPath =
    definition?.isTrigger && typeof parameters.path === "string"
      ? parameters.path
      : null;

  return (
    <div className="inspector">
      <div className="inspector-head">
        <div>
          <h2>{definition?.displayName ?? node.type}</h2>
          <code>{node.type}</code>
        </div>
        <button className="icon-button danger" onClick={() => onDelete(node.id)}>
          Delete
        </button>
      </div>

      {definition?.description && (
        <p className="inspector-description">{definition.description}</p>
      )}

      {webhookPath !== null && (
        <div className="webhook-hint">
          <span>Webhook</span>
          <code>POST /webhook/{webhookPath.replace(/^\/+/, "")}</code>
        </div>
      )}

      {nodeRun && (
        <div className={`node-run-box status-${nodeRun.status}`}>
          <strong>Last run: {nodeRun.status}</strong>
          <span>
            in {nodeRun.itemsIn} · out {nodeRun.itemsOut}
          </span>
          {nodeRun.error && <code>{nodeRun.error}</code>}
        </div>
      )}

      <div className="field-group">
        <label className="field">
          <span className="field-label">Node name</span>
          <input
            className="field-input"
            value={node.name}
            onChange={(event) => onChange(node.id, { name: event.target.value })}
          />
        </label>

        <label className="switch-row">
          <input
            type="checkbox"
            checked={Boolean(node.disabled)}
            onChange={(event) =>
              onChange(node.id, { disabled: event.target.checked })
            }
          />
          <span>Disabled (pass items through)</span>
        </label>

        {(definition?.properties ?? []).map((property) => (
          <div key={property.name}>
            <PropertyField
              property={property}
              value={parameters[property.name] ?? property.default}
              credentials={credentials}
              onChange={(value) => updateParameter(property.name, value)}
            />
            {property.description && (
              <span className="field-hint">{property.description}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
