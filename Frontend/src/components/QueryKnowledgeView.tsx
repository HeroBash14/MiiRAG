import React, { useEffect, useRef, useState } from "react";
import type { KnowledgeListItem, QueryResponse, SearchMode } from "../types";
import { executeQuery } from "../api";
import {
  CheckIcon,
  ClockIcon,
  CopyIcon,
  ExternalLinkIcon,
  EyeIcon,
  FileTextIcon,
  ImageIcon,
  SearchIcon,
  XIcon,
} from "./Icons";
import { MarkdownContent } from "./MarkdownContent";

interface ImagePreviewState {
  url: string;
  filename: string;
  pageNumber: number;
  knowledgeName: string;
}

interface QueryKnowledgeViewProps {
  knowledges: KnowledgeListItem[];
  onToast: (msg: string) => void;
}

export const QueryKnowledgeView: React.FC<QueryKnowledgeViewProps> = ({
  knowledges,
  onToast,
}) => {
  const [queryText, setQueryText] = useState("");
  const [selectedKid, setSelectedKid] = useState<string>("all");
  const [topK, setTopK] = useState(5);
  const [threshold, setThreshold] = useState(0.35);
  const [searchMode, setSearchMode] = useState<SearchMode>("hybrid");
  const [useRerank, setUseRerank] = useState(true);
  const [useHyde, setUseHyde] = useState(false);
  const [useQueryExpansion, setUseQueryExpansion] = useState(true);
  const [expandContext, setExpandContext] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [previewImage, setPreviewImage] = useState<ImagePreviewState | null>(null);
  const imageDialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = imageDialogRef.current;
    if (!dialog) return;
    if (previewImage) {
      if (!dialog.open) dialog.showModal();
    } else {
      if (dialog.open) dialog.close();
    }
  }, [previewImage]);

  const doneKnowledges = knowledges.filter((k) => k.status === "done");

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanQuery = queryText.trim();
    if (!cleanQuery) return;

    if (doneKnowledges.length === 0) {
      onToast("Belum ada knowledge dengan status 'Done' yang siap dicari.");
      return;
    }

    setLoading(true);
    try {
      const res = await executeQuery({
        query: cleanQuery,
        knowledge_ids: selectedKid === "all" ? undefined : [selectedKid],
        top_k: topK,
        score_threshold: threshold,
        search_mode: searchMode,
        use_rerank: useRerank,
        use_hyde: useHyde,
        use_query_expansion: useQueryExpansion,
        expand_context: expandContext,
      });
      setResult(res);
      if (res.results.length === 0) {
        onToast("Tidak ada dokumen yang relevan di atas threshold kemiripan.");
      }
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "Pencarian query gagal.");
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = (chunkId: number, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(chunkId);
    onToast("Teks potongan dokumen disalin ke clipboard.");
    setTimeout(() => setCopiedId(null), 2000);
  };

  const getScoreColor = (score: number) => {
    if (score >= 0.7) return { bg: "var(--prit)", color: "var(--prid)" };
    if (score >= 0.5) return { bg: "var(--blt)", color: "var(--bl)" };
    return { bg: "var(--amt)", color: "var(--am)" };
  };

  return (
    <div>
      <div className="hd">
        <div>
          <h1>Query Knowledge</h1>
          <p className="sub">
            Pencarian presisi berbasis Hybrid Retrieval (pgvector HNSW + PostgreSQL Full-Text RRF), Contextual Headers, dan Cross-Encoder Reranking.
          </p>
        </div>
      </div>

      <div className="box">
        <form onSubmit={handleSearch} className="query-box">
          <label className="f" htmlFor="query-input" style={{ fontWeight: 600 }}>
            Pertanyaan / Kata Kunci Pencarian
          </label>
          <div style={{ display: "flex", gap: "10px" }}>
            <input
              id="query-input"
              className="in"
              placeholder="Contoh: Apa saja syarat dokumen dan alur pengajuan klaim?"
              value={queryText}
              onChange={(e) => setQueryText(e.target.value)}
              disabled={loading}
              autoFocus
              style={{ fontSize: "15px" }}
            />
              <button
              type="submit"
              className="btn p"
              disabled={loading || !queryText.trim()}
              style={{ padding: "0 20px", whiteSpace: "nowrap" }}
            >
              <SearchIcon size={15} />
              <span>{loading ? "Mencari..." : "Cari Similarity"}</span>
            </button>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "14px",
              marginTop: "10px",
              paddingTop: "14px",
              borderTop: "1px solid var(--ln)",
            }}
          >
            <div>
              <label
                className="sub"
                htmlFor="select-knowledge-scope"
                style={{ display: "block", marginBottom: "5px", fontWeight: 500 }}
              >
                Pilih Knowledge:
              </label>
              <select
                id="select-knowledge-scope"
                className="in"
                value={selectedKid}
                onChange={(e) => setSelectedKid(e.target.value)}
                disabled={loading}
              >
                <option value="all">
                  Semua Knowledge Aktif ({doneKnowledges.length} siap)
                </option>
                {doneKnowledges.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name} (v{k.current_version})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "5px" }}>
                <label className="sub" htmlFor="input-top-k" style={{ fontWeight: 500 }}>
                  Jumlah Hasil (Top K):
                </label>
                <span className="v">{topK}</span>
              </div>
              <input
                id="input-top-k"
                className="in"
                type="number"
                min={1}
                max={20}
                value={topK}
                onChange={(e) => setTopK(Math.max(1, Math.min(20, Number(e.target.value))))}
                disabled={loading}
              />
            </div>

            <div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "5px" }}>
                <label className="sub" htmlFor="input-threshold" style={{ fontWeight: 500 }}>
                  Score Threshold (KKM):
                </label>
                <span className="v">{(threshold * 100).toFixed(0)}% ({threshold})</span>
              </div>
              <input
                id="input-threshold"
                className="in"
                type="number"
                step="0.05"
                min="0.0"
                max="1.0"
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
                disabled={loading}
              />
            </div>

            <div>
              <label
                className="sub"
                htmlFor="select-search-mode"
                style={{ display: "block", marginBottom: "5px", fontWeight: 500 }}
              >
                Mode Retrieval:
              </label>
              <select
                id="select-search-mode"
                className="in"
                value={searchMode}
                onChange={(e) => setSearchMode(e.target.value as SearchMode)}
                disabled={loading}
              >
                <option value="hybrid">Hybrid (Vector + Keyword RRF)</option>
                <option value="dense">Dense Vector (pgvector)</option>
                <option value="keyword">Keyword Only (FTS)</option>
              </select>
            </div>
          </div>

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "14px",
              marginTop: "10px",
              paddingTop: "10px",
              borderTop: "1px solid var(--ln)",
              alignItems: "center",
              fontSize: "13px",
            }}
          >
            <label style={{ display: "inline-flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={useRerank}
                onChange={(e) => setUseRerank(e.target.checked)}
                disabled={loading}
              />
              <span>Cross-Encoder Reranker</span>
            </label>

            <label style={{ display: "inline-flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={useQueryExpansion}
                onChange={(e) => setUseQueryExpansion(e.target.checked)}
                disabled={loading}
              />
              <span>Query Expansion</span>
            </label>

            <label style={{ display: "inline-flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={useHyde}
                onChange={(e) => setUseHyde(e.target.checked)}
                disabled={loading}
              />
              <span>HyDE (Hypothetical Doc)</span>
            </label>

            <label style={{ display: "inline-flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={expandContext}
                onChange={(e) => setExpandContext(e.target.checked)}
                disabled={loading}
              />
              <span>Expand Context</span>
            </label>
          </div>
        </form>
      </div>

      {result && (
        <div className="box">
          <div className="row" style={{ marginBottom: "14px", flexWrap: "wrap", gap: "10px" }}>
            <h2>
              Hasil Pencarian ({result.total_results} potongan chunk relevan)
            </h2>
            <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
              <span className="pill mono" style={{ fontSize: "12.5px" }}>
                <ClockIcon size={13} />
                <span>{result.latency_ms} ms</span>
              </span>
              {result.search_mode && (
                <span className="pill mono" style={{ fontSize: "12.5px", textTransform: "uppercase" }}>
                  {result.search_mode}
                </span>
              )}
              {result.reranked && (
                <span className="pill mono" style={{ fontSize: "12.5px", background: "var(--prit)", color: "var(--prid)" }}>
                  Reranked
                </span>
              )}
              {result.enhancement_used && result.enhancement_used !== "none" && (
                <span className="pill mono" style={{ fontSize: "12.5px", background: "var(--blt)", color: "var(--bl)" }}>
                  {result.enhancement_used}
                </span>
              )}
              <span className="pill mono" style={{ fontSize: "12.5px" }}>
                Threshold ≥ {threshold}
              </span>
            </div>
          </div>

          {result.hyde_document && (
            <div
              style={{
                marginBottom: "14px",
                padding: "10px 12px",
                borderRadius: "8px",
                background: "var(--bg)",
                border: "1px solid var(--ln)",
                fontSize: "12.5px",
                color: "var(--mut)",
              }}
            >
              <strong style={{ color: "var(--ink)" }}>HyDE Passage:</strong> {result.hyde_document}
            </div>
          )}

          {result.results.length === 0 ? (
            <div className="emp">
              <h3>Tidak ada potongan dokumen yang memenuhi kriteria</h3>
              <p>
                Semua potongan dokumen memiliki kemiripan di bawah threshold <b>{threshold}</b>.
                <br />
                Coba turunkan <b>Score Threshold</b> (misal ke <code>0.20</code>) atau gunakan kata kunci lain.
              </p>
            </div>
          ) : (
            result.results.map((r, index) => {
              const scoreStyle = getScoreColor(r.similarity_score);
              return (
                <div key={r.chunk_id} className="query-result-card">
                  <div
                    className="row"
                    style={{
                      marginBottom: "10px",
                      paddingBottom: "10px",
                      borderBottom: "1px solid var(--ln)",
                      flexWrap: "wrap",
                      gap: "8px",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                      <span className="v mono" style={{ fontWeight: 600 }}>
                        #{index + 1}
                      </span>
                      <span style={{ fontWeight: 600, fontSize: "14px" }}>
                        {r.knowledge_name}
                      </span>
                      <span className="v mono">v{r.version}</span>
                      <span className="sub" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                        <FileTextIcon size={13} />
                        <span>{r.filename} · Hal. {r.page_number}, Chunk #{r.chunk_index}</span>
                      </span>
                    </div>

                    <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                      {typeof r.rerank_score === "number" && (
                        <span
                          className="b mono"
                          style={{
                            background: "var(--blt)",
                            color: "var(--bl)",
                            fontWeight: 600,
                          }}
                          title="Skor probabilitas Cross-Encoder Reranker"
                        >
                          Rerank {(r.rerank_score * 100).toFixed(1)}%
                        </span>
                      )}
                      <span
                        className="b mono"
                        style={{
                          background: scoreStyle.bg,
                          color: scoreStyle.color,
                          fontWeight: 600,
                        }}
                      >
                        {(r.similarity_score * 100).toFixed(1)}% Kemiripan
                      </span>
                      {typeof r.keyword_score === "number" && r.keyword_score > 0 && (
                        <span
                          className="b mono"
                          style={{
                            background: "var(--amt)",
                            color: "var(--am)",
                            fontWeight: 600,
                          }}
                          title="Skor PostgreSQL Full-Text Search"
                        >
                          FTS {r.keyword_score.toFixed(2)}
                        </span>
                      )}
                      {r.page_image_url && (
                        <button
                          type="button"
                          className="btn"
                          style={{ padding: "4px 10px", fontSize: "12px" }}
                          onClick={() =>
                            setPreviewImage({
                              url: r.page_image_url!,
                              filename: r.filename,
                              pageNumber: r.page_number,
                              knowledgeName: r.knowledge_name,
                            })
                          }
                          title="Lihat snapshot gambar halaman asli PDF di MinIO"
                        >
                          <ImageIcon size={13} />
                          <span>Hal. {r.page_number}</span>
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn"
                        style={{ padding: "4px 10px", fontSize: "12px" }}
                        onClick={() => handleCopy(r.chunk_id, r.expanded_content || r.content)}
                      >
                        {copiedId === r.chunk_id ? <CheckIcon size={13} /> : <CopyIcon size={13} />}
                        <span>{copiedId === r.chunk_id ? "Tersalin" : "Salin"}</span>
                      </button>
                    </div>
                  </div>

                  {r.section_title && (
                    <div
                      className="sub"
                      style={{
                        fontSize: "12px",
                        marginBottom: "8px",
                        fontWeight: 500,
                        color: "var(--prid)",
                      }}
                    >
                      Bagian: {r.section_title}
                    </div>
                  )}

                  <MarkdownContent content={r.expanded_content || r.content} />

                  {r.page_image_url && (
                    <div className="snapshot-bar">
                      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                        <div className="snapshot-icon-box">
                          <ImageIcon size={16} />
                        </div>
                        <div>
                          <div style={{ fontSize: "13px", fontWeight: 600 }}>
                            Snapshot Halaman {r.page_number} · MinIO
                          </div>
                          <div className="sub" style={{ fontSize: "12px" }}>
                            URL gambar tersedia untuk analisis visual diagram atau tabel oleh LLM.
                          </div>
                        </div>
                      </div>

                      <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                        <button
                          type="button"
                          className="btn"
                          style={{ padding: "5px 12px", fontSize: "12px" }}
                          onClick={() =>
                            setPreviewImage({
                              url: r.page_image_url!,
                              filename: r.filename,
                              pageNumber: r.page_number,
                              knowledgeName: r.knowledge_name,
                            })
                          }
                        >
                          <EyeIcon size={13} />
                          <span>Lihat Gambar</span>
                        </button>
                        <a
                          href={r.page_image_url}
                          target="_blank"
                          rel="noreferrer"
                          className="btn"
                          style={{ padding: "5px 10px", fontSize: "12px", textDecoration: "none" }}
                        >
                          <span>Buka Asli</span>
                          <ExternalLinkIcon size={12} />
                        </a>
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Modal Dialog for Page Snapshot Image Preview */}
      <dialog
        ref={imageDialogRef}
        onClose={() => setPreviewImage(null)}
        onClick={(e) => {
          if (e.target === imageDialogRef.current) {
            setPreviewImage(null);
          }
        }}
        style={{ maxWidth: "920px", width: "95vw" }}
      >
        {previewImage && (
          <div className="md" style={{ padding: "20px", maxHeight: "90vh", display: "flex", flexDirection: "column" }}>
            <div
              className="row"
              style={{
                marginBottom: "14px",
                borderBottom: "1px solid var(--ln)",
                paddingBottom: "12px",
                flexWrap: "wrap",
                gap: "8px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <div className="snapshot-icon-box">
                  <FileTextIcon size={16} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: "15.5px" }}>
                    {previewImage.filename} — Halaman {previewImage.pageNumber}
                  </h3>
                  <p className="sub" style={{ margin: "2px 0 0 0", fontSize: "12.5px" }}>
                    Knowledge: <b>{previewImage.knowledgeName}</b> · Snapshot MinIO
                  </p>
                </div>
              </div>

              <div style={{ display: "flex", gap: "8px" }}>
                <a
                  href={previewImage.url}
                  target="_blank"
                  rel="noreferrer"
                  className="btn"
                  style={{ textDecoration: "none", fontSize: "12.5px" }}
                >
                  <span>Buka Tab Baru</span>
                  <ExternalLinkIcon size={13} />
                </a>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setPreviewImage(null)}
                  style={{ fontSize: "12.5px" }}
                >
                  <XIcon size={14} />
                  <span>Tutup</span>
                </button>
              </div>
            </div>

            <div
              style={{
                flex: 1,
                overflow: "auto",
                textAlign: "center",
                background: "var(--bg)",
                borderRadius: "8px",
                padding: "12px",
                border: "1px solid var(--ln)",
                maxHeight: "68vh",
              }}
            >
              <img
                src={previewImage.url}
                alt={`Snapshot Halaman ${previewImage.pageNumber}`}
                style={{
                  maxWidth: "100%",
                  height: "auto",
                  display: "inline-block",
                  boxShadow: "0 4px 18px rgba(0,0,0,0.12)",
                  borderRadius: "4px",
                }}
              />
            </div>

            <div
              style={{
                marginTop: "12px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                fontSize: "12px",
                color: "var(--mut)",
                flexWrap: "wrap",
                gap: "8px",
              }}
            >
              <span style={{ wordBreak: "break-all", maxWidth: "70%" }}>
                🔗 URL MinIO:{" "}
                <a href={previewImage.url} target="_blank" rel="noreferrer" style={{ color: "var(--pri)" }}>
                  {previewImage.url}
                </a>
              </span>
              <button
                type="button"
                className="btn"
                style={{ padding: "4px 10px", fontSize: "12px" }}
                onClick={() => {
                  navigator.clipboard.writeText(previewImage.url);
                  onToast("URL gambar MinIO disalin.");
                }}
              >
                Salin URL
              </button>
            </div>
          </div>
        )}
      </dialog>
    </div>
  );
};
