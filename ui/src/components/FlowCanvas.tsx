import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection as RFConnection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import type {
  Connection,
  NodeCatalogEntry,
  NodeRun,
  Run,
  Workflow,
  WorkflowNode,
} from "../types";

interface FlowNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  group: string;
  isTrigger: boolean;
  disabled: boolean;
  status: string;
  outputs: string[];
  error: string;
  onRetry?: (nodeId: string) => void;
}

function FlowNode({ data, selected, id }: NodeProps) {
  const node = data as unknown as FlowNodeData;
  return (
    <div
      className={[
        "flow-node",
        `group-${node.group}`,
        `status-${node.status}`,
        node.disabled ? "is-disabled" : "",
        selected ? "is-selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {node.status === "error" && node.onRetry && (
        <button
          className="node-retry"
          title="Retry this node"
          onClick={(event) => {
            event.stopPropagation();
            node.onRetry?.(id);
          }}
        >
          Retry
        </button>
      )}
      {!node.isTrigger && <Handle type="target" position={Position.Left} id="in" />}
      <div className="flow-node-head">
        <span className="flow-node-dot" />
        <span className="flow-node-title">{node.label}</span>
      </div>
      <div className="flow-node-type">{node.nodeType}</div>
      <div className="flow-node-status">
        {node.status === "running"
          ? "running"
          : node.status === "success"
            ? "ok"
            : node.status === "error"
              ? "error"
              : node.status === "skipped"
                ? "skipped"
                : ""}
      </div>
      {node.outputs.map((output, index) => (
        <Handle
          key={output}
          id={output}
          type="source"
          position={Position.Right}
          style={{ top: `${((index + 1) / (node.outputs.length + 1)) * 100}%` }}
          title={output}
        />
      ))}
      {node.outputs.length > 1 && (
        <div className="flow-node-branches">{node.outputs.join(" / ")}</div>
      )}
      {node.error && (
        <div className="flow-node-error" title={node.error}>
          {node.error.length > 160 ? `${node.error.slice(0, 160)}...` : node.error}
        </div>
      )}
    </div>
  );
}

const nodeTypes = { qa: FlowNode };

interface FlowCanvasProps {
  workflow: Workflow;
  catalog: NodeCatalogEntry[];
  run: Run | null;
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
  onNodeMove: (id: string, position: { x: number; y: number }) => void;
  onDeleteNodes: (ids: string[]) => void;
  onConnectionsChange: (connections: Connection[]) => void;
  onRetryNode: (nodeId: string) => void;
}

function nodeRunFor(run: Run | null, nodeId: string): NodeRun | undefined {
  return run?.nodeRuns.find((entry) => entry.nodeId === nodeId);
}

function makeNode(
  node: WorkflowNode,
  catalogMap: Map<string, NodeCatalogEntry>,
  run: Run | null,
  selectedNodeId: string | null,
  onRetryNode: (nodeId: string) => void,
  position?: { x: number; y: number },
): Node {
  const definition = catalogMap.get(node.type);
  const nodeRun = nodeRunFor(run, node.id);
  const data: FlowNodeData = {
    label: node.name,
    nodeType: node.type,
    group: definition?.group ?? "action",
    isTrigger: definition?.isTrigger ?? false,
    disabled: Boolean(node.disabled),
    status: nodeRun?.status ?? "idle",
    outputs: definition?.outputs ?? ["main"],
    error: nodeRun?.error ?? "",
    onRetry: onRetryNode,
  };
  return {
    id: node.id,
    type: "qa",
    position: position ?? node.position,
    selected: node.id === selectedNodeId,
    data,
  };
}

function toEdge(connection: Connection, index: number): Edge {
  const output = connection.output ?? "main";
  return {
    id: `${connection.from}->${connection.to}:${output}:${index}`,
    source: connection.from,
    target: connection.to,
    sourceHandle: output,
    targetHandle: "in",
    label: output === "main" ? undefined : output,
    className: output === "true" ? "edge-true" : output === "false" ? "edge-false" : "",
    interactionWidth: 28,
    deletable: true,
  };
}

export function FlowCanvas({
  workflow,
  catalog,
  run,
  selectedNodeId,
  onSelectNode,
  onNodeMove,
  onDeleteNodes,
  onConnectionsChange,
  onRetryNode,
}: FlowCanvasProps) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);

  const catalogMap = useMemo(
    () => new Map(catalog.map((entry) => [entry.type, entry])),
    [catalog],
  );

  useEffect(() => {
    setNodes(
      workflow.nodes.map((node) =>
        makeNode(node, catalogMap, run, selectedNodeId, onRetryNode),
      ),
    );
    setEdges(workflow.connections.map(toEdge));
    // Reset only when switching workflows.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow.id]);

  useEffect(() => {
    setNodes((previous) => {
      const byId = new Map(previous.map((entry) => [entry.id, entry]));
      return workflow.nodes.map((node) =>
        makeNode(
          node,
          catalogMap,
          run,
          selectedNodeId,
          onRetryNode,
          byId.get(node.id)?.position ?? node.position,
        ),
      );
    });
    setEdges(workflow.connections.map(toEdge));
  }, [workflow, catalogMap, run, selectedNodeId, onRetryNode]);

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setNodes((current) => applyNodeChanges(changes, current));
      for (const change of changes) {
        if (change.type === "position" && change.position && !change.dragging) {
          onNodeMove(change.id, change.position);
        }
      }
    },
    [onNodeMove],
  );

  const handleEdgesChange = useCallback((changes: EdgeChange[]) => {
    setEdges((current) => applyEdgeChanges(changes, current));
  }, []);

  const deleteConnections = useCallback(
    (deletedEdges: Edge[]) => {
      const removed = new Set(
        deletedEdges.map(
          (edge) =>
            `${edge.source}->${edge.target}:${(edge.sourceHandle as string | null) ?? "main"}`,
        ),
      );
      onConnectionsChange(
        workflow.connections.filter(
          (connection) =>
            !removed.has(
              `${connection.from}->${connection.to}:${connection.output ?? "main"}`,
            ),
        ),
      );
    },
    [onConnectionsChange, workflow.connections],
  );

  const handleConnect = useCallback(
    (connection: RFConnection) => {
      if (!connection.source || !connection.target) return;
      if (connection.source === connection.target) return;
      const output = (connection.sourceHandle as string | null) ?? "main";
      const exists = workflow.connections.some(
        (item) =>
          item.from === connection.source &&
          item.to === connection.target &&
          (item.output ?? "main") === output,
      );
      if (exists) return;
      onConnectionsChange([
        ...workflow.connections,
        { from: connection.source, to: connection.target, output },
      ]);
    },
    [onConnectionsChange, workflow.connections],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={handleNodesChange}
      onEdgesChange={handleEdgesChange}
      onEdgesDelete={(deleted) => deleteConnections(deleted)}
      onEdgeDoubleClick={(event, edge) => {
        event.stopPropagation();
        deleteConnections([edge]);
      }}
      deleteKeyCode={["Backspace", "Delete"]}
      onConnect={handleConnect}
      onNodesDelete={(deleted) => onDeleteNodes(deleted.map((entry) => entry.id))}
      onNodeClick={(_event, node) => onSelectNode(node.id)}
      onPaneClick={() => onSelectNode(null)}
      fitView
      fitViewOptions={{ padding: 0.25, maxZoom: 0.9 }}
      proOptions={{ hideAttribution: true }}
      minZoom={0.2}
      maxZoom={1.6}
    >
      <Background gap={18} size={1} color="#d9dee5" />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        nodeColor={(node) => {
          const group = (node.data as { group?: string }).group;
          if (group === "trigger") return "#ffa116";
          if (group === "qa") return "#0074cc";
          if (group === "transform") return "#00af9b";
          return "#2cbb5d";
        }}
      />
    </ReactFlow>
  );
}
