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
}

export interface QueryResponse {
  query: string;
  latency_ms: number;
  total_results: number;
  search_mode?: string;
  reranked?: boolean;
  enhancement_used?: string;
  hyde_document?: string | null;
  results: QueryResultItem[];
}
