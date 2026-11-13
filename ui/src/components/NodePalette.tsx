import { useMemo, useState } from "react";
import type { NodeCatalogEntry } from "../types";

const GROUP_LABELS: Record<string, string> = {
  trigger: "Triggers",
  qa: "QA / AI",
  transform: "Transform",
  action: "Actions",
};

const GROUP_ORDER = ["trigger", "qa", "transform", "action"];

interface NodePaletteProps {
  catalog: NodeCatalogEntry[];
  onAdd: (type: string) => void;
}

export function NodePalette({ catalog, onAdd }: NodePaletteProps) {
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const filtered = catalog.filter((entry) => {
      const needle = query.trim().toLowerCase();
      if (!needle) return true;
      return (
        entry.displayName.toLowerCase().includes(needle) ||
        entry.type.toLowerCase().includes(needle) ||
        entry.description.toLowerCase().includes(needle)
      );
    });
    return GROUP_ORDER.map((group) => ({
      group,
      label: GROUP_LABELS[group] ?? group,
      entries: filtered.filter((entry) => entry.group === group),
    })).filter((section) => section.entries.length > 0);
  }, [catalog, query]);

  return (
    <section className="palette">
      <h3>Nodes</h3>
      <input
        className="field-input"
        placeholder="Search nodes…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {groups.map((section) => (
        <div key={section.group} className="palette-group">
          <h4>{section.label}</h4>
          {section.entries.map((entry) => (
            <button
              key={entry.type}
              className={`palette-item group-${entry.group}`}
              onClick={() => onAdd(entry.type)}
              title={entry.description}
            >
              <span className="palette-item-title">{entry.displayName}</span>
              <span className="palette-item-type">{entry.type}</span>
            </button>
          ))}
        </div>
      ))}
    </section>
  );
}
