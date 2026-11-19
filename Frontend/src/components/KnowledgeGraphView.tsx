import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  GraphEdgeItem,
  GraphNodeDetailResponse,
  GraphNodeItem,
  KnowledgeGraphResponse,
} from "../types";
import {
  fetchGraphNodeDetail,
  fetchKnowledgeGraph,
  rebuildKnowledgeGraph,
} from "../api";
import {
  FileTextIcon,
  LayersIcon,
  MaximizeIcon,
  NetworkIcon,
  RefreshIcon,
  SearchIcon,
  XIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "./Icons";
import { MarkdownContent } from "./MarkdownContent";

interface KnowledgeGraphViewProps {
  knowledgeId: string;
  knowledgeStatus: string;
  onToast: (msg: string) => void;
}

type LayoutMode = "force" | "cluster" | "radial" | "circular";

interface SimNode extends GraphNodeItem {
  x: number;
  y: number;
  radius: number;
}

const NODE_TYPE_META: Record<
  string,
  { label: string; colorLight: string; colorDark: string; bgLight: string; bgDark: string }
> = {
  document: {
    label: "Dokumen",
    colorLight: "#0f9d71",
    colorDark: "#34c69a",
    bgLight: "#e1f5ec",
    bgDark: "#16352b",
  },
  concept: {
    label: "Konsep",
    colorLight: "#2563eb",
    colorDark: "#60a5fa",
    bgLight: "#e5edfb",
    bgDark: "#1c2a45",
  },
  reference: {
    label: "Kode / Ref",
    colorLight: "#d97706",
    colorDark: "#f59e0b",
    bgLight: "#fcefd0",
    bgDark: "#3a2f14",
  },
  section: {
    label: "Bagian / Sheet",
    colorLight: "#7c3aed",
    colorDark: "#a78bfa",
    bgLight: "#f3e8ff",
    bgDark: "#2d1f47",
  },
};

const EDGE_TYPE_LABELS: Record<string, string> = {
  semantic_bridge: "Jembatan Semantik (BGE-M3)",
  mentions: "Menyebut / Referensi",
  co_occurs: "Muncul Bersama",
  contains: "Memuat Bagian",
};

const LAYOUT_OPTIONS: { id: LayoutMode; label: string }[] = [
  { id: "force", label: "Force Directed" },
  { id: "cluster", label: "Cluster Dokumen" },
  { id: "radial", label: "Radial Hub" },
  { id: "circular", label: "Circular" },
];

function seededRandom(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 10000) / 10000;
}

function getNodeRadius(node: GraphNodeItem): number {
  if (node.node_type === "document") {
    return Math.min(26, 17 + Math.sqrt(Math.max(1, node.degree)) * 2.2);
  }
  if (node.node_type === "reference") {
    return Math.min(18, 10 + Math.sqrt(Math.max(1, node.degree)) * 1.8);
  }
  if (node.node_type === "concept") {
    return Math.min(20, 9 + node.doc_frequency * 1.8 + Math.sqrt(Math.max(1, node.degree)) * 1.2);
  }
  return Math.min(13, 7 + Math.sqrt(Math.max(1, node.degree)) * 1.0);
}

function computePositions(
  nodes: GraphNodeItem[],
  edges: GraphEdgeItem[],
  mode: LayoutMode
): Map<string, SimNode> {
  const result = new Map<string, SimNode>();
  if (nodes.length === 0) return result;

  const simNodes: SimNode[] = nodes.map((n) => ({
    ...n,
    x: 0,
    y: 0,
    radius: getNodeRadius(n),
  }));
  const byId = new Map<string, SimNode>(simNodes.map((n) => [n.id, n]));

  const docNodes = simNodes.filter((n) => n.node_type === "document");
  const secNodes = simNodes.filter((n) => n.node_type === "section");
  const entityNodes = simNodes.filter(
    (n) => n.node_type === "concept" || n.node_type === "reference"
  );

  if (mode === "circular") {
    const ordered = [...docNodes, ...entityNodes, ...secNodes];
    const r = Math.max(180, ordered.length * 10);
    ordered.forEach((n, idx) => {
      const angle = (2 * Math.PI * idx) / ordered.length - Math.PI / 2;
      n.x = Math.cos(angle) * r;
      n.y = Math.sin(angle) * r;
    });
    simNodes.forEach((n) => result.set(n.id, n));
    return result;
  }

  if (mode === "radial") {
    const hubs = entityNodes
      .filter((n) => n.doc_frequency >= 2 || n.degree >= 3)
      .sort((a, b) => b.doc_frequency - a.doc_frequency || b.degree - a.degree);
    const hubIds = new Set(hubs.map((h) => h.id));
    const outerEntities = entityNodes.filter((n) => !hubIds.has(n.id));

    hubs.forEach((n, idx) => {
      const r = hubs.length === 1 ? 0 : Math.max(70, hubs.length * 12);
      const angle = (2 * Math.PI * idx) / Math.max(1, hubs.length);
      n.x = Math.cos(angle) * r;
      n.y = Math.sin(angle) * r;
    });

    const docR = Math.max(210, hubs.length * 12 + 120);
    docNodes.forEach((n, idx) => {
      const angle = (2 * Math.PI * idx) / Math.max(1, docNodes.length) - Math.PI / 2;
      n.x = Math.cos(angle) * docR;
      n.y = Math.sin(angle) * docR;
    });

    const outer = [...outerEntities, ...secNodes];
    const outerR = docR + 135;
    outer.forEach((n, idx) => {
      const angle = (2 * Math.PI * idx) / Math.max(1, outer.length);
      n.x = Math.cos(angle) * outerR;
      n.y = Math.sin(angle) * outerR;
    });

    simNodes.forEach((n) => result.set(n.id, n));
    return result;
  }

  // Initial seed positions (used directly by "cluster" and as warm start for "force")
  const docRingR = docNodes.length <= 1 ? 0 : Math.max(210, docNodes.length * 52);
  const docPosByDocId = new Map<string, { x: number; y: number }>();

  docNodes.forEach((dn, idx) => {
    const angle = (2 * Math.PI * idx) / Math.max(1, docNodes.length) - Math.PI / 2;
    dn.x = Math.cos(angle) * docRingR;
    dn.y = Math.sin(angle) * docRingR;
    if (dn.document_id) {
      docPosByDocId.set(dn.document_id, { x: dn.x, y: dn.y });
    }
  });

  // Sections orbit their parent document
  const secByParent = new Map<string, SimNode[]>();
  secNodes.forEach((sn) => {
    const key = sn.document_id || "none";
    const list = secByParent.get(key) || [];
    list.push(sn);
    secByParent.set(key, list);
  });
  secByParent.forEach((list, docId) => {
    const parent = docPosByDocId.get(docId) || { x: 0, y: 0 };
    const baseAngle = Math.atan2(parent.y, parent.x);
    const orbitR = 110;
    list.forEach((sn, idx) => {
      const spread = Math.min(Math.PI * 1.4, list.length * 0.42);
      const offset = list.length === 1 ? 0 : (idx / (list.length - 1) - 0.5) * spread;
      const a = baseAngle + offset;
      sn.x = parent.x + Math.cos(a) * orbitR;
      sn.y = parent.y + Math.sin(a) * orbitR;
    });
  });

  // Entities positioned near centroid of mentioning documents (cross-doc hubs naturally gather in center!)
  const neighborDocMap = new Map<string, SimNode[]>();
  edges.forEach((e) => {
    const src = byId.get(e.source);
    const tgt = byId.get(e.target);
    if (!src || !tgt) return;
    if (src.node_type === "document" && (tgt.node_type === "concept" || tgt.node_type === "reference")) {
      const arr = neighborDocMap.get(tgt.id) || [];
      arr.push(src);
      neighborDocMap.set(tgt.id, arr);
    } else if (tgt.node_type === "document" && (src.node_type === "concept" || src.node_type === "reference")) {
      const arr = neighborDocMap.get(src.id) || [];
      arr.push(tgt);
      neighborDocMap.set(src.id, arr);
    }
  });

  entityNodes.forEach((en, idx) => {
    const linkedDocs = neighborDocMap.get(en.id) || [];
    const jitterAngle = seededRandom(en.id) * Math.PI * 2;
    const jitterR = 35 + seededRandom(en.id + "_r") * 75;
    if (linkedDocs.length > 0) {
      const cx = linkedDocs.reduce((acc, d) => acc + d.x, 0) / linkedDocs.length;
      const cy = linkedDocs.reduce((acc, d) => acc + d.y, 0) / linkedDocs.length;
      en.x = cx + Math.cos(jitterAngle) * jitterR;
      en.y = cy + Math.sin(jitterAngle) * jitterR;
    } else {
      const angle = (2 * Math.PI * idx) / Math.max(1, entityNodes.length);
      en.x = Math.cos(angle) * 140;
      en.y = Math.sin(angle) * 140;
    }
  });

  if (mode === "cluster") {
    // Run a few gentle anti-overlap passes so cluster nodes never sit directly on top of each other
    for (let iter = 0; iter < 35; iter++) {
      for (let i = 0; i < simNodes.length; i++) {
        for (let j = i + 1; j < simNodes.length; j++) {
          const a = simNodes[i];
          const b = simNodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.hypot(dx, dy) || 0.1;
          const minDist = a.radius + b.radius + 36;
          if (dist < minDist) {
            const push = ((minDist - dist) / dist) * 0.45;
            if (a.node_type !== "document") {
              a.x -= dx * push;
              a.y -= dy * push;
            }
            if (b.node_type !== "document") {
              b.x += dx * push;
              b.y += dy * push;
            }
          }
        }
      }
    }
    simNodes.forEach((n) => result.set(n.id, n));
    return result;
  }

  // Force-directed warm-started physics simulation (deterministic & silky smooth)
  const vx = new Map<string, number>();
  const vy = new Map<string, number>();
  simNodes.forEach((n) => {
    vx.set(n.id, 0);
    vy.set(n.id, 0);
  });

  const iterations = Math.min(180, Math.max(90, 220 - simNodes.length));
  const repulsion = 3400;
  const gravity = 0.018;

  for (let step = 0; step < iterations; step++) {
    const temp = 1 - step / iterations;
    const damping = 0.78;

    // Pairwise repulsion + collision prevention
    for (let i = 0; i < simNodes.length; i++) {
      const a = simNodes[i];
      for (let j = i + 1; j < simNodes.length; j++) {
        const b = simNodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const distSq = dx * dx + dy * dy + 1;
        const dist = Math.sqrt(distSq);
        const minDist = a.radius + b.radius + 34;

        let force = repulsion / distSq;
        if (dist < minDist) {
          force += (minDist - dist) * 0.4;
        }
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        vx.set(a.id, (vx.get(a.id) || 0) - fx);
        vy.set(a.id, (vy.get(a.id) || 0) - fy);
        vx.set(b.id, (vx.get(b.id) || 0) + fx);
        vy.set(b.id, (vy.get(b.id) || 0) + fy);
      }
    }

    // Spring attraction along edges
    for (const edge of edges) {
      const src = byId.get(edge.source);
      const tgt = byId.get(edge.target);
      if (!src || !tgt) continue;
      const dx = tgt.x - src.x;
      const dy = tgt.y - src.y;
      const dist = Math.hypot(dx, dy) || 1;
      const idealLen =
        edge.edge_type === "contains"
          ? 110
          : edge.edge_type === "semantic_bridge"
          ? 220
          : 155;
      const strength = edge.edge_type === "contains" ? 0.045 : 0.028 * Math.max(0.4, edge.weight);
      const disp = (dist - idealLen) * strength;
      const fx = (dx / dist) * disp;
      const fy = (dy / dist) * disp;
      vx.set(src.id, (vx.get(src.id) || 0) + fx);
      vy.set(src.id, (vy.get(src.id) || 0) + fy);
      vx.set(tgt.id, (vx.get(tgt.id) || 0) - fx);
      vy.set(tgt.id, (vy.get(tgt.id) || 0) - fy);
    }

    // Gentle centering gravity + position integration
    const maxStep = 28 * Math.max(0.15, temp);
    for (const n of simNodes) {
      let nxv = ((vx.get(n.id) || 0) - n.x * gravity) * damping;
      let nyv = ((vy.get(n.id) || 0) - n.y * gravity) * damping;
      const mag = Math.hypot(nxv, nyv);
      if (mag > maxStep) {
        nxv = (nxv / mag) * maxStep;
        nyv = (nyv / mag) * maxStep;
      }
      n.x += nxv;
      n.y += nyv;
      vx.set(n.id, nxv);
      vy.set(n.id, nyv);
    }
  }

  simNodes.forEach((n) => result.set(n.id, n));
  return result;
}

export const KnowledgeGraphView: React.FC<KnowledgeGraphViewProps> = ({
  knowledgeId,
  knowledgeStatus,
  onToast,
}) => {
  const [graphData, setGraphData] = useState<KnowledgeGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);

  // Filters & view states
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("force");
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false);
  const [visibleTypes, setVisibleTypes] = useState<Record<string, boolean>>({
    document: true,
    concept: true,
    reference: true,
    section: true,
  });
  const [crossDocOnly, setCrossDocOnly] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [layoutSeed, setLayoutSeed] = useState(0);

  // Selection & inspector
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [nodeDetail, setNodeDetail] = useState<GraphNodeDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Canvas & camera refs
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cameraRef = useRef({ x: 0, y: 0, zoom: 1 });
  const simNodesRef = useRef<Map<string, SimNode>>(new Map());
  const dragRef = useRef<{
    type: "pan" | "node" | null;
    nodeId?: string;
    startX: number;
    startY: number;
    camStartX: number;
    camStartY: number;
    moved: boolean;
  }>({ type: null, startX: 0, startY: 0, camStartX: 0, camStartY: 0, moved: false });
  const [renderTick, setRenderTick] = useState(0);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchKnowledgeGraph(knowledgeId, { includeSections: true });
      setGraphData(data);
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "Gagal memuat Knowledge Graph.");
    } finally {
      setLoading(false);
    }
  }, [knowledgeId, onToast]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  const handleRebuild = async () => {
    setRebuilding(true);
    try {
      const data = await rebuildKnowledgeGraph(knowledgeId);
      setGraphData(data);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setNodeDetail(null);
      onToast(
        `Knowledge Graph selesai dibangun (${data.stats.total_nodes} node, ${data.stats.total_edges} relasi).`
      );
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "Gagal membangun Knowledge Graph.");
    } finally {
      setRebuilding(false);
    }
  };

  // Load real chunk details when user selects a node
  useEffect(() => {
    if (!selectedNodeId) {
      setNodeDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    fetchGraphNodeDetail(knowledgeId, selectedNodeId)
      .then((res) => {
        if (!cancelled) setNodeDetail(res);
      })
      .catch(() => {
        if (!cancelled) setNodeDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [knowledgeId, selectedNodeId]);

  // Filtered nodes & edges
  const { filteredNodes, filteredEdges } = useMemo(() => {
    if (!graphData || graphData.status !== "ready") {
      return { filteredNodes: [] as GraphNodeItem[], filteredEdges: [] as GraphEdgeItem[] };
    }
    const baseNodes = graphData.nodes.filter((n) => visibleTypes[n.node_type] !== false);
    const nodeIds = new Set(baseNodes.map((n) => n.id));
    let edges = graphData.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));

    if (crossDocOnly) {
      edges = edges.filter((e) => e.is_cross_document);
      const connectedIds = new Set<string>();
      edges.forEach((e) => {
        connectedIds.add(e.source);
        connectedIds.add(e.target);
      });
      const crossNodes = baseNodes.filter(
        (n) => n.node_type === "document" || connectedIds.has(n.id)
      );
      return { filteredNodes: crossNodes, filteredEdges: edges };
    }

    return { filteredNodes: baseNodes, filteredEdges: edges };
  }, [graphData, visibleTypes, crossDocOnly]);

  // Search matches dropdown
  const searchMatches = useMemo(() => {
    const q = searchTerm.trim().toLowerCase();
    if (!q) return [];
    return filteredNodes
      .filter(
        (n) =>
          n.label.toLowerCase().includes(q) ||
          n.aliases.some((a) => a.toLowerCase().includes(q)) ||
          n.filenames.some((f) => f.toLowerCase().includes(q))
      )
      .slice(0, 8);
  }, [filteredNodes, searchTerm]);

  // Adjacency map for fast 1-hop hover/select spotlight
  const adjacencyMap = useMemo(() => {
    const map = new Map<string, Set<string>>();
    filteredEdges.forEach((e) => {
      if (!map.has(e.source)) map.set(e.source, new Set());
      if (!map.has(e.target)) map.set(e.target, new Set());
      map.get(e.source)!.add(e.target);
      map.get(e.target)!.add(e.source);
    });
    return map;
  }, [filteredEdges]);

  const fitCamera = useCallback(() => {
    const canvas = canvasRef.current;
    const nodes = Array.from(simNodesRef.current.values());
    if (!canvas || nodes.length === 0) return;

    const rect = canvas.getBoundingClientRect();
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    nodes.forEach((n) => {
      minX = Math.min(minX, n.x - n.radius - 45);
      maxX = Math.max(maxX, n.x + n.radius + 45);
      minY = Math.min(minY, n.y - n.radius - 30);
      maxY = Math.max(maxY, n.y + n.radius + 30);
    });
    const w = Math.max(120, maxX - minX);
    const h = Math.max(120, maxY - minY);
    const padding = 48;
    const zoom = Math.max(
      0.28,
      Math.min(1.45, Math.min((rect.width - padding * 2) / w, (rect.height - padding * 2) / h))
    );
    cameraRef.current = {
      x: -(minX + maxX) / 2,
      y: -(minY + maxY) / 2,
      zoom,
    };
    setRenderTick((t) => t + 1);
  }, []);

  // Recompute positions when graph, filter, or layout changes
  useEffect(() => {
    simNodesRef.current = computePositions(filteredNodes, filteredEdges, layoutMode);
    const timer = window.setTimeout(() => {
      fitCamera();
    }, 20);
    return () => window.clearTimeout(timer);
  }, [filteredNodes, filteredEdges, layoutMode, layoutSeed, fitCamera]);

  const focusNode = useCallback((nodeId: string) => {
    const sn = simNodesRef.current.get(nodeId);
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(null);
    if (sn) {
      cameraRef.current = {
        x: -sn.x,
        y: -sn.y,
        zoom: Math.max(cameraRef.current.zoom, 1.15),
      };
      setRenderTick((t) => t + 1);
    }
  }, []);

  // Screen <-> World transforms
  const screenToWorld = (sx: number, sy: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const cam = cameraRef.current;
    return {
      x: (sx - rect.width / 2) / cam.zoom - cam.x,
      y: (sy - rect.height / 2) / cam.zoom - cam.y,
    };
  };

  // Hit-test node at screen coordinates
  const findNodeAt = (sx: number, sy: number): SimNode | null => {
    const world = screenToWorld(sx, sy);
    const nodes = Array.from(simNodesRef.current.values());
    // Check top-most (documents/entities first)
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dist = Math.hypot(world.x - n.x, world.y - n.y);
      if (dist <= n.radius + 5) return n;
    }
    return null;
  };

  // Hit-test edge at screen coordinates
  const findEdgeAt = (sx: number, sy: number): GraphEdgeItem | null => {
    const world = screenToWorld(sx, sy);
    const threshold = 7 / Math.max(0.5, cameraRef.current.zoom);
    for (const edge of filteredEdges) {
      const a = simNodesRef.current.get(edge.source);
      const b = simNodesRef.current.get(edge.target);
      if (!a || !b) continue;
      // Approximate midpoint curve distance
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const lenSq = dx * dx + dy * dy;
      if (lenSq < 1) continue;
      const t = Math.max(0, Math.min(1, ((world.x - a.x) * dx + (world.y - a.y) * dy) / lenSq));
      const projX = a.x + t * dx;
      const projY = a.y + t * dy;
      if (Math.hypot(world.x - projX, world.y - projY) <= threshold) {
        return edge;
      }
    }
    return null;
  };

  // High-DPI Canvas render effect
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
        canvas.width = Math.round(rect.width * dpr);
        canvas.height = Math.round(rect.height * dpr);
      }

      const isDark =
        document.documentElement.getAttribute("data-theme") === "dark" ||
        (!document.documentElement.getAttribute("data-theme") &&
          window.matchMedia("(prefers-color-scheme: dark)").matches);

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, rect.width, rect.height);

      // Subtle dot grid background
      const cam = cameraRef.current;
      const gridSize = 28 * cam.zoom;
      if (gridSize >= 10) {
        ctx.fillStyle = isDark ? "rgba(154, 168, 180, 0.09)" : "rgba(102, 117, 131, 0.11)";
        const offsetX = ((rect.width / 2 + cam.x * cam.zoom) % gridSize + gridSize) % gridSize;
        const offsetY = ((rect.height / 2 + cam.y * cam.zoom) % gridSize + gridSize) % gridSize;
        for (let gx = offsetX; gx < rect.width; gx += gridSize) {
          for (let gy = offsetY; gy < rect.height; gy += gridSize) {
            ctx.beginPath();
            ctx.arc(gx, gy, 1, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }

      ctx.translate(rect.width / 2, rect.height / 2);
      ctx.scale(cam.zoom, cam.zoom);
      ctx.translate(cam.x, cam.y);

      const activeFocusId = hoveredNodeId || selectedNodeId;
      const activeNeighbors = activeFocusId ? adjacencyMap.get(activeFocusId) : null;
      const selectedEdgeObj = selectedEdgeId
        ? filteredEdges.find((e) => e.id === selectedEdgeId) || null
        : null;

      // 1. Draw edges
      for (const edge of filteredEdges) {
        const a = simNodesRef.current.get(edge.source);
        const b = simNodesRef.current.get(edge.target);
        if (!a || !b) continue;

        const isSelectedEdge = edge.id === selectedEdgeId;
        const isIncident =
          activeFocusId !== null &&
          (edge.source === activeFocusId || edge.target === activeFocusId);
        const dimmed =
          (activeFocusId !== null && !isIncident) ||
          (selectedEdgeObj !== null && !isSelectedEdge);

        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const curveOffset = edge.edge_type === "semantic_bridge" ? 0.14 : 0.06;
        const cx = mx - dy * curveOffset;
        const cy = my + dx * curveOffset;

        ctx.save();
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.quadraticCurveTo(cx, cy, b.x, b.y);

        if (edge.edge_type === "semantic_bridge") {
          ctx.setLineDash([6, 4]);
          ctx.strokeStyle = dimmed
            ? isDark
              ? "rgba(52, 198, 154, 0.10)"
              : "rgba(15, 157, 113, 0.12)"
            : isDark
            ? "rgba(52, 198, 154, 0.85)"
            : "rgba(15, 157, 113, 0.80)";
          ctx.lineWidth = isSelectedEdge || isIncident ? 2.8 : Math.max(1.4, edge.weight * 2.4);
        } else if (edge.edge_type === "mentions") {
          ctx.strokeStyle = dimmed
            ? isDark
              ? "rgba(148, 163, 184, 0.08)"
              : "rgba(100, 116, 139, 0.09)"
            : isIncident || isSelectedEdge
            ? isDark
              ? "rgba(96, 165, 250, 0.9)"
              : "rgba(37, 99, 235, 0.8)"
            : isDark
            ? "rgba(148, 163, 184, 0.30)"
            : "rgba(100, 116, 139, 0.28)";
          ctx.lineWidth = isSelectedEdge || isIncident ? 2.2 : 1.25;
        } else if (edge.edge_type === "co_occurs") {
          ctx.strokeStyle = dimmed
            ? isDark
              ? "rgba(167, 139, 250, 0.07)"
              : "rgba(124, 58, 237, 0.07)"
            : isIncident || isSelectedEdge
            ? isDark
              ? "rgba(167, 139, 250, 0.85)"
              : "rgba(124, 58, 237, 0.72)"
            : isDark
            ? "rgba(167, 139, 250, 0.22)"
            : "rgba(124, 58, 237, 0.20)";
          ctx.lineWidth = isSelectedEdge || isIncident ? 2.0 : 1.0;
        } else {
          ctx.strokeStyle = dimmed
            ? isDark
              ? "rgba(148, 163, 184, 0.06)"
              : "rgba(148, 163, 184, 0.08)"
            : isDark
            ? "rgba(148, 163, 184, 0.22)"
            : "rgba(148, 163, 184, 0.30)";
          ctx.lineWidth = isSelectedEdge || isIncident ? 1.8 : 0.9;
        }

        ctx.stroke();

        // Draw edge weight badge on selected/incident semantic_bridge
        if ((isSelectedEdge || (isIncident && edge.edge_type === "semantic_bridge")) && cam.zoom >= 0.55) {
          const lx = 0.25 * a.x + 0.5 * cx + 0.25 * b.x;
          const ly = 0.25 * a.y + 0.5 * cy + 0.25 * b.y;
          const text = edge.label || `${Math.round(edge.weight * 100)}%`;
          ctx.setLineDash([]);
          ctx.font = '600 10px "Plus Jakarta Sans", system-ui, sans-serif';
          const tw = ctx.measureText(text).width + 10;
          ctx.fillStyle = isDark ? "#1a2229" : "#ffffff";
          ctx.strokeStyle = isDark ? "#34c69a" : "#0f9d71";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.roundRect(lx - tw / 2, ly - 9, tw, 18, 6);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = isDark ? "#5fd8b2" : "#0b7f5a";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(text, lx, ly);
        }
        ctx.restore();
      }

      // 2. Draw nodes
      const allSimNodes = Array.from(simNodesRef.current.values());
      // Render sections first, concepts/references second, documents on top
      const orderRank: Record<string, number> = {
        section: 0,
        concept: 1,
        reference: 2,
        document: 3,
      };
      allSimNodes.sort((a, b) => (orderRank[a.node_type] ?? 1) - (orderRank[b.node_type] ?? 1));

      for (const n of allSimNodes) {
        const meta = NODE_TYPE_META[n.node_type] || NODE_TYPE_META.concept;
        const fillColor = isDark ? meta.colorDark : meta.colorLight;

        const isSelected = n.id === selectedNodeId;
        const isHovered = n.id === hoveredNodeId;
        const isNeighbor = activeNeighbors ? activeNeighbors.has(n.id) : false;
        const isEdgeEnd =
          selectedEdgeObj !== null &&
          (selectedEdgeObj.source === n.id || selectedEdgeObj.target === n.id);
        const dimmed =
          (activeFocusId !== null && !isSelected && !isHovered && !isNeighbor) ||
          (selectedEdgeObj !== null && !isEdgeEnd);

        ctx.save();
        ctx.globalAlpha = dimmed ? 0.18 : 1.0;

        // Halo for selected/hovered or cross-doc hubs
        if (isSelected || isHovered) {
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.radius + 7, 0, Math.PI * 2);
          ctx.fillStyle = isDark ? "rgba(52, 198, 154, 0.25)" : "rgba(15, 157, 113, 0.20)";
          ctx.fill();
        } else if (n.doc_frequency >= 2 && n.node_type !== "document") {
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.radius + 3.5, 0, Math.PI * 2);
          ctx.strokeStyle = fillColor;
          ctx.lineWidth = 1.2;
          ctx.globalAlpha = dimmed ? 0.1 : 0.45;
          ctx.stroke();
          ctx.globalAlpha = dimmed ? 0.18 : 1.0;
        }

        // Main circle
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
        ctx.fillStyle = fillColor;
        ctx.fill();
        ctx.lineWidth = isSelected || isHovered ? 2.5 : 1.8;
        ctx.strokeStyle = isDark ? "#12181d" : "#ffffff";
        ctx.stroke();

        // Crisp pill label (LightRAG style!)
        const showLabel =
          isSelected ||
          isHovered ||
          isNeighbor ||
          isEdgeEnd ||
          n.node_type === "document" ||
          n.node_type === "reference" ||
          n.doc_frequency >= 2 ||
          cam.zoom >= 0.82;

        if (showLabel) {
          const shortLabel = n.label.length > 28 ? `${n.label.slice(0, 27)}…` : n.label;
          const fontSize = n.node_type === "document" ? 12 : 11;
          ctx.font = `${n.node_type === "document" || isSelected ? 600 : 500} ${fontSize}px "Plus Jakarta Sans", system-ui, sans-serif`;
          const textW = ctx.measureText(shortLabel).width;
          const padX = 7;
          const boxW = textW + padX * 2;
          const boxH = fontSize + 7;
          const bx = n.x + n.radius + 6;
          const by = n.y - boxH / 2;

          ctx.fillStyle = isDark ? "rgba(26, 34, 41, 0.92)" : "rgba(255, 255, 255, 0.94)";
          ctx.strokeStyle =
            isSelected || isHovered
              ? fillColor
              : isDark
              ? "rgba(42, 52, 61, 0.9)"
              : "rgba(228, 233, 237, 0.95)";
          ctx.lineWidth = isSelected || isHovered ? 1.5 : 1;
          ctx.beginPath();
          ctx.roundRect(bx, by, boxW, boxH, 6);
          ctx.fill();
          ctx.stroke();

          ctx.fillStyle = isDark ? "#e6ecf0" : "#2d3a45";
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillText(shortLabel, bx + padX, n.y + 0.5);
        }

        ctx.restore();
      }

      ctx.restore();
    };

    draw();

    const onResize = () => draw();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [filteredEdges, hoveredNodeId, selectedNodeId, selectedEdgeId, adjacencyMap, renderTick]);

  // Mouse handlers on canvas
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const hitNode = findNodeAt(sx, sy);

    if (hitNode) {
      dragRef.current = {
        type: "node",
        nodeId: hitNode.id,
        startX: sx,
        startY: sy,
        camStartX: hitNode.x,
        camStartY: hitNode.y,
        moved: false,
      };
    } else {
      dragRef.current = {
        type: "pan",
        startX: sx,
        startY: sy,
        camStartX: cameraRef.current.x,
        camStartY: cameraRef.current.y,
        moved: false,
      };
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const drag = dragRef.current;

    if (drag.type === "node" && drag.nodeId) {
      const dx = (sx - drag.startX) / cameraRef.current.zoom;
      const dy = (sy - drag.startY) / cameraRef.current.zoom;
      if (Math.hypot(dx, dy) > 2) drag.moved = true;
      const sn = simNodesRef.current.get(drag.nodeId);
      if (sn) {
        sn.x = drag.camStartX + dx;
        sn.y = drag.camStartY + dy;
        setRenderTick((t) => t + 1);
      }
      return;
    }

    if (drag.type === "pan") {
      const dx = (sx - drag.startX) / cameraRef.current.zoom;
      const dy = (sy - drag.startY) / cameraRef.current.zoom;
      if (Math.hypot(sx - drag.startX, sy - drag.startY) > 3) drag.moved = true;
      cameraRef.current.x = drag.camStartX + dx;
      cameraRef.current.y = drag.camStartY + dy;
      setRenderTick((t) => t + 1);
      return;
    }

    const hitNode = findNodeAt(sx, sy);
    const nextHover = hitNode ? hitNode.id : null;
    if (nextHover !== hoveredNodeId) {
      setHoveredNodeId(nextHover);
    }
    e.currentTarget.style.cursor = hitNode ? "pointer" : "grab";
  };

  const handleMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    const wasMoved = drag.moved;
    const draggedNodeId = drag.nodeId;
    dragRef.current = { type: null, startX: 0, startY: 0, camStartX: 0, camStartY: 0, moved: false };

    if (wasMoved) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (draggedNodeId) {
      setSelectedNodeId(draggedNodeId);
      setSelectedEdgeId(null);
      return;
    }

    const hitEdge = findEdgeAt(sx, sy);
    if (hitEdge) {
      setSelectedEdgeId(hitEdge.id);
      setSelectedNodeId(null);
    } else {
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
    }
  };

  const selectedNode = useMemo(
    () => (selectedNodeId ? filteredNodes.find((n) => n.id === selectedNodeId) || null : null),
    [filteredNodes, selectedNodeId]
  );

  const selectedEdge = useMemo(
    () => (selectedEdgeId ? filteredEdges.find((e) => e.id === selectedEdgeId) || null : null),
    [filteredEdges, selectedEdgeId]
  );

  const nodeLabelMap = useMemo(() => {
    const m = new Map<string, GraphNodeItem>();
    (graphData?.nodes || []).forEach((n) => m.set(n.id, n));
    return m;
  }, [graphData]);

  // Top cross-doc hubs & semantic bridges for overview inspector
  const topHubs = useMemo(
    () =>
      (graphData?.nodes || [])
        .filter((n) => (n.node_type === "concept" || n.node_type === "reference") && n.doc_frequency >= 2)
        .sort((a, b) => b.doc_frequency - a.doc_frequency || b.degree - a.degree)
        .slice(0, 8),
    [graphData]
  );

  const topBridges = useMemo(
    () =>
      (graphData?.edges || [])
        .filter((e) => e.edge_type === "semantic_bridge")
        .sort((a, b) => b.weight - a.weight)
        .slice(0, 6),
    [graphData]
  );

  if (loading) {
    return (
      <div className="emp" style={{ padding: "48px 16px" }}>
        <h3>Memuat Knowledge Graph…</h3>
        <p className="sub">Mengambil peta relasi entitas & jembatan semantik BAAI/bge-m3.</p>
      </div>
    );
  }

  if (knowledgeStatus !== "done") {
    return (
      <div className="emp" style={{ padding: "48px 16px" }}>
        <h3>Knowledge Graph belum tersedia</h3>
        <p className="sub">
          Selesaikan proses embedding dokumen terlebih dahulu. Knowledge Graph akan dibangun otomatis
          secara lokal menggunakan <b>BAAI/bge-m3</b> tanpa LLM.
        </p>
      </div>
    );
  }

  if (!graphData || graphData.status === "empty" || graphData.nodes.length === 0) {
    return (
      <div className="emp" style={{ padding: "48px 20px" }}>
        <div
          style={{
            width: "52px",
            height: "52px",
            borderRadius: "14px",
            background: "var(--prit)",
            color: "var(--prid)",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: "14px",
          }}
        >
          <NetworkIcon size={26} />
        </div>
        <h3 style={{ margin: "0 0 8px" }}>Belum ada Knowledge Graph untuk versi ini</h3>
        <p className="sub" style={{ maxWidth: "520px", margin: "0 auto 18px" }}>
          Bangun peta relasi lintas dokumen secara <b>100% lokal (Zero-LLM, Rp 0)</b> menggunakan
          vektor <code>BAAI/bge-m3</code> untuk memetakan konsep bersama, kode SOP/pasal, dan
          jembatan makna antar file di knowledge ini.
        </p>
        <button
          type="button"
          className="btn p"
          onClick={handleRebuild}
          disabled={rebuilding}
        >
          <NetworkIcon size={16} />
          <span>{rebuilding ? "Membangun Knowledge Graph…" : "Bangun Knowledge Graph (BAAI/bge-m3)"}</span>
        </button>
      </div>
    );
  }

  return (
    <div className="kg-root">
      {/* Top Toolbar */}
      <div className="kg-toolbar">
        <div className="kg-search-wrap">
          <SearchIcon size={14} className="kg-search-icon" />
          <input
            className="kg-search-input"
            placeholder="Cari dokumen, konsep, atau kode…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
          {searchTerm && (
            <button
              type="button"
              className="kg-clear-btn"
              onClick={() => setSearchTerm("")}
              aria-label="Hapus pencarian"
            >
              <XIcon size={13} />
            </button>
          )}
          {searchMatches.length > 0 && (
            <div className="kg-search-dropdown">
              {searchMatches.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className="kg-search-item"
                  onClick={() => {
                    focusNode(m.id);
                    setSearchTerm("");
                  }}
                >
                  <span className={`kg-dot kg-dot-${m.node_type}`} />
                  <span className="kg-search-label">{m.label}</span>
                  <span className="kg-search-meta">
                    {NODE_TYPE_META[m.node_type]?.label || m.node_type}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="kg-filters">
          {(["document", "concept", "reference", "section"] as const).map((type) => {
            const count =
              type === "document"
                ? graphData.stats.document_nodes
                : type === "concept"
                ? graphData.stats.concept_nodes
                : type === "reference"
                ? graphData.stats.reference_nodes
                : graphData.stats.section_nodes;
            const active = visibleTypes[type];
            return (
              <button
                key={type}
                type="button"
                className={`kg-filter-pill ${active ? "on" : ""}`}
                onClick={() => setVisibleTypes((prev) => ({ ...prev, [type]: !prev[type] }))}
              >
                <span className={`kg-dot kg-dot-${type}`} />
                <span>{NODE_TYPE_META[type].label}</span>
                <span className="kg-pill-count">{count}</span>
              </button>
            );
          })}

          <button
            type="button"
            className={`kg-filter-pill ${crossDocOnly ? "on-cross" : ""}`}
            onClick={() => setCrossDocOnly((prev) => !prev)}
            title="Hanya tampilkan jembatan & konsep yang menghubungkan lebih dari 1 dokumen"
          >
            <span>Lintas Dokumen ({graphData.stats.cross_document_edges})</span>
          </button>
        </div>

        <button
          type="button"
          className="btn"
          style={{ padding: "7px 12px", fontSize: "13px" }}
          onClick={handleRebuild}
          disabled={rebuilding}
          title="Hitung ulang Knowledge Graph dari vektor BAAI/bge-m3"
        >
          <RefreshIcon size={14} />
          <span>{rebuilding ? "Membangun…" : "Perbarui Graph"}</span>
        </button>
      </div>

      {/* Main Workspace: Interactive Canvas + Right Inspector */}
      <div className="kg-workspace">
        <div className="kg-canvas-wrap" ref={containerRef}>
          <canvas
            ref={canvasRef}
            className="kg-canvas"
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={() => {
              dragRef.current.type = null;
              setHoveredNodeId(null);
            }}
          />

          {/* Floating Left Controls (LightRAG-style) */}
          <div className="kg-float-controls">
            <div style={{ position: "relative" }}>
              <button
                type="button"
                className={`kg-ctrl-btn ${layoutMenuOpen ? "active" : ""}`}
                onClick={() => setLayoutMenuOpen((o) => !o)}
                title="Ubah Layout Graph"
              >
                <LayersIcon size={16} />
              </button>
              {layoutMenuOpen && (
                <div className="kg-layout-menu">
                  {LAYOUT_OPTIONS.map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      className={`kg-layout-opt ${layoutMode === opt.id ? "on" : ""}`}
                      onClick={() => {
                        setLayoutMode(opt.id);
                        setLayoutMenuOpen(false);
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button
              type="button"
              className="kg-ctrl-btn"
              onClick={() => {
                cameraRef.current.zoom = Math.min(3.0, cameraRef.current.zoom * 1.2);
                setRenderTick((t) => t + 1);
              }}
              title="Perbesar (Zoom In)"
            >
              <ZoomInIcon size={16} />
            </button>
            <button
              type="button"
              className="kg-ctrl-btn"
              onClick={() => {
                cameraRef.current.zoom = Math.max(0.22, cameraRef.current.zoom * 0.82);
                setRenderTick((t) => t + 1);
              }}
              title="Perkecil (Zoom Out)"
            >
              <ZoomOutIcon size={16} />
            </button>
            <button
              type="button"
              className="kg-ctrl-btn"
              onClick={fitCamera}
              title="Paskan ke Layar"
            >
              <MaximizeIcon size={16} />
            </button>
            <button
              type="button"
              className="kg-ctrl-btn"
              onClick={() => setLayoutSeed((s) => s + 1)}
              title="Susun Ulang Posisi"
            >
              <RefreshIcon size={15} />
            </button>
          </div>

          {/* Bottom-Left Legend & Status */}
          <div className="kg-canvas-footer">
            <span>
              Nodes: <b>{filteredNodes.length}</b> · Edges: <b>{filteredEdges.length}</b> · Semantic
              Bridges: <b>{graphData.stats.semantic_bridge_edges}</b>
            </span>
            <span className="kg-legend-line">
              <i className="kg-dash-sample" /> Jembatan Semantik BAAI/bge-m3
            </span>
          </div>
        </div>

        {/* Right Inspector Panel (LightRAG-style) */}
        <aside className="kg-inspector">
          {selectedNode ? (
            <div className="kg-insp-body">
              <div className="kg-insp-head">
                <div>
                  <span className={`kg-type-badge kg-badge-${selectedNode.node_type}`}>
                    {NODE_TYPE_META[selectedNode.node_type]?.label || selectedNode.node_type}
                  </span>
                  <h3 className="kg-insp-title">{selectedNode.label}</h3>
                </div>
                <button
                  type="button"
                  className="kg-clear-btn"
                  onClick={() => setSelectedNodeId(null)}
                  title="Tutup detail node"
                >
                  <XIcon size={15} />
                </button>
              </div>

              <div className="kg-metric-grid">
                <div className="kg-metric">
                  <span>Relasi</span>
                  <b>{selectedNode.degree}</b>
                </div>
                <div className="kg-metric">
                  <span>Dokumen</span>
                  <b>{selectedNode.doc_frequency}</b>
                </div>
                <div className="kg-metric">
                  <span>Chunks</span>
                  <b>{selectedNode.chunk_count}</b>
                </div>
              </div>

              <div className="kg-insp-section">
                <h4>Properties</h4>
                <p className="kg-insp-desc">{selectedNode.description}</p>

                {selectedNode.aliases.length > 0 && (
                  <div className="kg-prop-row">
                    <span className="kg-prop-key">Alias (BGE-M3):</span>
                    <div className="kg-tag-list">
                      {selectedNode.aliases.map((a) => (
                        <span key={a} className="tag">
                          {a}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {selectedNode.filenames.length > 0 && (
                  <div className="kg-prop-row">
                    <span className="kg-prop-key">Sumber Dokumen:</span>
                    <div className="kg-tag-list">
                      {selectedNode.filenames.map((f) => (
                        <span key={f} className="tag">
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="kg-insp-section">
                <h4>Relasi Terhubung ({nodeDetail?.neighbors.length ?? selectedNode.degree})</h4>
                {detailLoading ? (
                  <p className="sub" style={{ fontSize: "12.5px" }}>
                    Memuat relasi & bukti dokumen…
                  </p>
                ) : nodeDetail && nodeDetail.neighbors.length > 0 ? (
                  <div className="kg-neighbor-list">
                    {nodeDetail.neighbors.slice(0, 14).map((nb) => (
                      <button
                        key={`${nb.edge_id}-${nb.node_id}`}
                        type="button"
                        className="kg-neighbor-item"
                        onClick={() => focusNode(nb.node_id)}
                      >
                        <span className={`kg-dot kg-dot-${nb.node_type}`} />
                        <span className="kg-nb-label">{nb.label}</span>
                        <span className={`kg-nb-edge ${nb.is_cross_document ? "cross" : ""}`}>
                          {nb.edge_label || EDGE_TYPE_LABELS[nb.edge_type] || nb.edge_type}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="sub" style={{ fontSize: "12.5px" }}>
                    Tidak ada relasi pada filter saat ini.
                  </p>
                )}
              </div>

              <div className="kg-insp-section">
                <h4>Cuplikan Bukti Dokumen ({nodeDetail?.chunks.length ?? 0})</h4>
                {detailLoading ? (
                  <p className="sub" style={{ fontSize: "12.5px" }}>
                    Memuat isi chunk…
                  </p>
                ) : nodeDetail && nodeDetail.chunks.length > 0 ? (
                  <div className="kg-chunk-list">
                    {nodeDetail.chunks.slice(0, 5).map((ch) => (
                      <div key={ch.chunk_id} className="kg-mini-chunk">
                        <div className="kg-mini-chunk-hd">
                          <FileTextIcon size={12} />
                          <span>
                            {ch.filename} · Hal. {ch.page_number}
                          </span>
                        </div>
                        {ch.section_title && (
                          <div className="kg-mini-chunk-sec">{ch.section_title}</div>
                        )}
                        <div className="kg-mini-chunk-body">
                          <MarkdownContent
                            content={
                              ch.content.length > 360
                                ? `${ch.content.slice(0, 360)}…`
                                : ch.content
                            }
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="sub" style={{ fontSize: "12.5px" }}>
                    Belum ada cuplikan chunk tersedia.
                  </p>
                )}
              </div>
            </div>
          ) : selectedEdge ? (
            <div className="kg-insp-body">
              <div className="kg-insp-head">
                <div>
                  <span className="kg-type-badge kg-badge-document">
                    {EDGE_TYPE_LABELS[selectedEdge.edge_type] || selectedEdge.edge_type}
                  </span>
                  <h3 className="kg-insp-title">{selectedEdge.label || "Relasi Antar Node"}</h3>
                </div>
                <button
                  type="button"
                  className="kg-clear-btn"
                  onClick={() => setSelectedEdgeId(null)}
                >
                  <XIcon size={15} />
                </button>
              </div>

              <div className="kg-edge-endpoints">
                <button
                  type="button"
                  className="kg-neighbor-item"
                  onClick={() => focusNode(selectedEdge.source)}
                >
                  <span
                    className={`kg-dot kg-dot-${nodeLabelMap.get(selectedEdge.source)?.node_type || "concept"}`}
                  />
                  <span className="kg-nb-label">
                    {nodeLabelMap.get(selectedEdge.source)?.label || selectedEdge.source}
                  </span>
                </button>
                <div className="kg-edge-arrow">↕ Bobot: {(selectedEdge.weight * 100).toFixed(0)}%</div>
                <button
                  type="button"
                  className="kg-neighbor-item"
                  onClick={() => focusNode(selectedEdge.target)}
                >
                  <span
                    className={`kg-dot kg-dot-${nodeLabelMap.get(selectedEdge.target)?.node_type || "concept"}`}
                  />
                  <span className="kg-nb-label">
                    {nodeLabelMap.get(selectedEdge.target)?.label || selectedEdge.target}
                  </span>
                </button>
              </div>

              <div className="kg-insp-section">
                <h4>Deskripsi Relasi</h4>
                <p className="kg-insp-desc">{selectedEdge.description}</p>
                {selectedEdge.keywords && (
                  <div className="kg-prop-row">
                    <span className="kg-prop-key">Kata Kunci Penghubung:</span>
                    <div className="kg-tag-list">
                      {selectedEdge.keywords.split(",").map((kw) => (
                        <span key={kw.trim()} className="tag">
                          {kw.trim()}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="kg-insp-body">
              <div className="kg-insp-head">
                <div>
                  <span className="kg-type-badge kg-badge-document">Zero-LLM · BAAI/bge-m3</span>
                  <h3 className="kg-insp-title">Ringkasan Knowledge Graph</h3>
                </div>
              </div>
              <p className="kg-insp-desc">
                Klik <b>node</b> atau <b>garis relasi</b> pada graf untuk melihat detail
                keterhubungan antar dokumen beserta cuplikan teks aslinya. Tarik node untuk
                mengatur posisi, atau gunakan tombol zoom di sisi kiri kanvas.
              </p>

              <div className="kg-metric-grid">
                <div className="kg-metric">
                  <span>Dokumen</span>
                  <b>{graphData.stats.document_nodes}</b>
                </div>
                <div className="kg-metric">
                  <span>Konsep/Ref</span>
                  <b>{graphData.stats.concept_nodes + graphData.stats.reference_nodes}</b>
                </div>
                <div className="kg-metric">
                  <span>Lintas File</span>
                  <b>{graphData.stats.cross_document_edges}</b>
                </div>
              </div>

              {topHubs.length > 0 && (
                <div className="kg-insp-section">
                  <h4>Entitas Hub Lintas Dokumen</h4>
                  <div className="kg-neighbor-list">
                    {topHubs.map((hub) => (
                      <button
                        key={hub.id}
                        type="button"
                        className="kg-neighbor-item"
                        onClick={() => focusNode(hub.id)}
                      >
                        <span className={`kg-dot kg-dot-${hub.node_type}`} />
                        <span className="kg-nb-label">{hub.label}</span>
                        <span className="kg-nb-edge cross">{hub.doc_frequency} file</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {topBridges.length > 0 && (
                <div className="kg-insp-section">
                  <h4>Jembatan Semantik Terkuat (BGE-M3)</h4>
                  <div className="kg-neighbor-list">
                    {topBridges.map((br) => {
                      const src = nodeLabelMap.get(br.source);
                      const tgt = nodeLabelMap.get(br.target);
                      return (
                        <button
                          key={br.id}
                          type="button"
                          className="kg-neighbor-item"
                          onClick={() => {
                            setSelectedEdgeId(br.id);
                            setSelectedNodeId(null);
                          }}
                        >
                          <span className="kg-nb-label" style={{ fontSize: "12px" }}>
                            {src?.label || "?"} ↔ {tgt?.label || "?"}
                          </span>
                          <span className="kg-nb-edge cross">
                            {Math.round(br.weight * 100)}%
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
};
