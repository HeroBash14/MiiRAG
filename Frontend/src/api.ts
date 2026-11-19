import type {
  GraphNodeDetailResponse,
  KnowledgeDetailResponse,
  KnowledgeGraphResponse,
  KnowledgeListResponse,
  QueryRequest,
  QueryResponse,
} from "./types";

const BASE_URL = "/api/v1";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = "Terjadi kesalahan pada server.";
    try {
      const data = await res.json();
      if (data && data.detail) {
        errorDetail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      errorDetail = `HTTP Error ${res.status}: ${res.statusText}`;
    }
    throw new Error(errorDetail);
  }
  return res.json();
}

export async function fetchKnowledges(
  q?: string,
  status?: string
): Promise<KnowledgeListResponse> {
  const params = new URLSearchParams();
  if (q && q.trim()) params.set("q", q.trim());
  if (status && status !== "all") params.set("status", status);
  const url = `${BASE_URL}/knowledges${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await fetch(url);
  return handleResponse<KnowledgeListResponse>(res);
}

export async function fetchKnowledgeDetail(
  id: string
): Promise<KnowledgeDetailResponse> {
  const res = await fetch(`${BASE_URL}/knowledges/${id}`);
  return handleResponse<KnowledgeDetailResponse>(res);
}

export async function createKnowledge(
  formData: FormData
): Promise<KnowledgeDetailResponse> {
  const res = await fetch(`${BASE_URL}/knowledges`, {
    method: "POST",
    body: formData,
  });
  return handleResponse<KnowledgeDetailResponse>(res);
}

export async function updateDraftKnowledge(
  id: string,
  formData: FormData
): Promise<KnowledgeDetailResponse> {
  const res = await fetch(`${BASE_URL}/knowledges/${id}`, {
    method: "PATCH",
    body: formData,
  });
  return handleResponse<KnowledgeDetailResponse>(res);
}

export async function startKnowledgeEmbedding(
  id: string
): Promise<KnowledgeDetailResponse> {
  const res = await fetch(`${BASE_URL}/knowledges/${id}/process`, {
    method: "POST",
  });
  return handleResponse<KnowledgeDetailResponse>(res);
}

export async function renewKnowledge(
  id: string,
  formData: FormData
): Promise<KnowledgeDetailResponse> {
  const res = await fetch(`${BASE_URL}/knowledges/${id}/renew`, {
    method: "POST",
    body: formData,
  });
  return handleResponse<KnowledgeDetailResponse>(res);
}

export async function deleteKnowledge(id: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/knowledges/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    let errorDetail = "Gagal menghapus knowledge.";
    try {
      const data = await res.json();
      if (data && data.detail) errorDetail = data.detail;
    } catch {
      errorDetail = `HTTP Error ${res.status}`;
    }
    throw new Error(errorDetail);
  }
}

export async function executeQuery(
  payload: QueryRequest
): Promise<QueryResponse> {
  const res = await fetch(`${BASE_URL}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<QueryResponse>(res);
}

export async function fetchKnowledgeGraph(
  knowledgeId: string,
  options?: {
    versionId?: string;
    includeSections?: boolean;
    nodeTypes?: string[];
    minWeight?: number;
  }
): Promise<KnowledgeGraphResponse> {
  const params = new URLSearchParams();
  if (options?.versionId) params.set("version_id", options.versionId);
  if (options?.includeSections === false) params.set("include_sections", "false");
  if (options?.nodeTypes && options.nodeTypes.length > 0) {
    params.set("node_types", options.nodeTypes.join(","));
  }
  if (typeof options?.minWeight === "number" && options.minWeight > 0) {
    params.set("min_weight", String(options.minWeight));
  }
  const qs = params.toString();
  const res = await fetch(`${BASE_URL}/knowledges/${knowledgeId}/graph${qs ? `?${qs}` : ""}`);
  return handleResponse<KnowledgeGraphResponse>(res);
}

export async function rebuildKnowledgeGraph(
  knowledgeId: string,
  versionId?: string
): Promise<KnowledgeGraphResponse> {
  const qs = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
  const res = await fetch(`${BASE_URL}/knowledges/${knowledgeId}/graph/rebuild${qs}`, {
    method: "POST",
  });
  return handleResponse<KnowledgeGraphResponse>(res);
}

export async function fetchGraphNodeDetail(
  knowledgeId: string,
  nodeId: string
): Promise<GraphNodeDetailResponse> {
  const res = await fetch(`${BASE_URL}/knowledges/${knowledgeId}/graph/nodes/${nodeId}`);
  return handleResponse<GraphNodeDetailResponse>(res);
}
