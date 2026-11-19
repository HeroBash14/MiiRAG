export type KnowledgeStatus = "unfinished" | "processing" | "done";

export type DocumentStatus = "waiting" | "processing" | "embedded" | "failed";

export interface DocumentItem {
  id: string;
  filename: string;
  file_size: number;
  status: DocumentStatus;
  error_message: string | null;
  page_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeVersionItem {
  id: string;
  version_number: number;
  note: string | null;
  status: KnowledgeStatus;
  doc_count: number;
  is_active: boolean;
  created_at: string;
}

export interface KnowledgeStatusCounts {
  all: number;
  unfinished: number;
  processing: number;
  done: number;
}

export interface KnowledgeListItem {
  id: string;
  name: string;
  description: string | null;
  status: KnowledgeStatus;
  current_version: number;
  doc_count: number;
  embedded_doc_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeListResponse {
  counts: KnowledgeStatusCounts;
  items: KnowledgeListItem[];
}

export interface KnowledgeDetailResponse {
  id: string;
  name: string;
  description: string | null;
  status: KnowledgeStatus;
  current_version: number;
  active_version_id: string | null;
  doc_count: number;
  embedded_doc_count: number;
  created_at: string;
  updated_at: string;
  documents: DocumentItem[];
  version_history: KnowledgeVersionItem[];
}

export type SearchMode = "hybrid" | "dense" | "keyword";

export interface QueryRequest {
  query: string;
  knowledge_ids?: string[];
  top_k?: number;
  score_threshold?: number;
  search_mode?: SearchMode;
  use_rerank?: boolean;
  use_hyde?: boolean;
  use_query_expansion?: boolean;
  expand_context?: boolean;
  use_graph?: boolean;
}

export interface QueryResultItem {
  chunk_id: number;
  knowledge_id: string;
  knowledge_name: string;
  version: number;
  document_id: string;
  filename: string;
  page_number: number;
  chunk_index: number;
  content: string;
  similarity_score: number;
  page_image_url?: string | null;
  section_title?: string | null;
  expanded_content?: string | null;
  keyword_score?: number | null;
  rerank_score?: number | null;
  via_graph?: boolean;
  graph_reason?: string | null;
  related_entities?: string[];
}

export interface QueryResponse {
  query: string;
  latency_ms: number;
  total_results: number;
  search_mode?: string;
  reranked?: boolean;
  graph_used?: boolean;
  graph_nodes_matched?: string[];
  enhancement_used?: string;
  hyde_document?: string | null;
  results: QueryResultItem[];
}

export type GraphNodeType = "document" | "section" | "concept" | "reference";
export type GraphEdgeType = "contains" | "mentions" | "co_occurs" | "semantic_bridge";

export interface GraphStats {
  total_nodes: number;
  total_edges: number;
  document_nodes: number;
  section_nodes: number;
  concept_nodes: number;
  reference_nodes: number;
  cross_document_edges: number;
  semantic_bridge_edges: number;
  built_at: string | null;
}

export interface GraphNodeItem {
  id: string;
  node_key: string;
  label: string;
  node_type: GraphNodeType | string;
  description: string;
  degree: number;
  doc_frequency: number;
  chunk_count: number;
  document_id: string | null;
  filenames: string[];
  aliases: string[];
  source_chunk_ids: number[];
  sample_snippets: string[];
}

export interface GraphEdgeItem {
  id: string;
  source: string;
  target: string;
  edge_type: GraphEdgeType | string;
  weight: number;
  label: string;
  keywords: string;
  description: string;
  is_cross_document: boolean;
  source_chunk_ids: number[];
}

export interface KnowledgeGraphResponse {
  knowledge_id: string;
  knowledge_name: string;
  version_id: string | null;
  version_number: number;
  status: "ready" | "empty";
  stats: GraphStats;
  nodes: GraphNodeItem[];
  edges: GraphEdgeItem[];
}

export interface GraphChunkSnippet {
  chunk_id: number;
  document_id: string;
  filename: string;
  page_number: number;
  chunk_index: number;
  section_title: string | null;
  content: string;
}

export interface GraphNeighbor {
  node_id: string;
  label: string;
  node_type: string;
  edge_id: string;
  edge_type: string;
  edge_label: string;
  weight: number;
  is_cross_document: boolean;
}

export interface GraphNodeDetailResponse {
  node: GraphNodeItem;
  neighbors: GraphNeighbor[];
  chunks: GraphChunkSnippet[];
}
