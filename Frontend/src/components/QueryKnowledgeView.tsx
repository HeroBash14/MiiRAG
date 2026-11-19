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

const SEARCH_MODE_HINTS: Record<SearchMode, string> = {
  hybrid: "Gabungan pencarian makna (vector) dan kata kunci (keyword), diurutkan dengan RRF. Paling lengkap & seimbang.",
  dense: "Mencari berdasarkan ide dan makna kalimat. Bagus untuk pertanyaan bebas atau konseptual.",
  keyword: "Mencari kata, nomor kode, atau istilah yang persis sama (seperti Ctrl+F). Bagus untuk nomor SOP/pasal.",
};

const SEARCH_MODE_LABELS: Record<SearchMode, string> = {
  hybrid: "Hybrid",
  dense: "Vector",
  keyword: "Keyword",
};

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
  const [isConfigOpen, setIsConfigOpen] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [previewImage, setPreviewImage] = useState<ImagePreviewState | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const imageDialogRef = useRef<HTMLDialogElement>(null);

  // Auto-resize textarea to fit content (max 280px)
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight + 2, 280)}px`;
    }
  }, [queryText]);

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

  const activeTechniquesCount = [useRerank, useQueryExpansion, useHyde, expandContext].filter(Boolean).length;

  const selectedKnowledgeName =
    selectedKid === "all"
      ? `${doneKnowledges.length} knowledge aktif`
      : (doneKnowledges.find((k) => k.id === selectedKid)?.name || "1 knowledge");

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

  const handleResetDefault = () => {
    setSelectedKid("all");
    setSearchMode("hybrid");
    setTopK(5);
    setThreshold(0.35);
    setUseRerank(true);
    setUseQueryExpansion(true);
    setUseHyde(false);
    setExpandContext(false);
    onToast("Konfigurasi dikembalikan ke default");
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
          <p className="sub">Cari jawaban langsung dari dokumen di knowledge Anda.</p>
        </div>
      </div>

      <div className="cols">
        {/* KOLOM KIRI: Query Input & Hasil Pencarian */}
        <div className="qk-left-col">
          <section className="card cp" aria-labelledby="ql">
            <div style={{ marginBottom: "18px" }}>
              <label
                htmlFor="select-knowledge-scope"
                style={{ fontWeight: 600, display: "block", marginBottom: "7px", fontSize: "14px" }}
              >
                Cari di knowledge mana?
              </label>
              <select
                id="select-knowledge-scope"
                value={selectedKid}
                onChange={(e) => setSelectedKid(e.target.value)}
                disabled={loading}
                style={{
                  width: "100%",
                  border: "1px solid var(--ln)",
                  background: "var(--bg)",
                  borderRadius: "10px",
                  padding: "10px 12px",
                  color: "var(--ink)",
                  fontFamily: "inherit",
                  fontSize: "14px",
                }}
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
              <p className="hint" style={{ marginTop: "5px", fontSize: "12.5px" }}>
                Hanya knowledge berstatus Done yang bisa dicari.
              </p>
            </div>

            <label htmlFor="q" id="ql" style={{ fontWeight: 600, display: "block", marginBottom: "9px" }}>
              Apa yang ingin Anda cari?
            </label>
            <div className="q">
              <textarea
                id="q"
                ref={textareaRef}
                rows={5}
                placeholder="Contoh: Apa saja syarat dokumen dan alur pengajuan klaim?"
                value={queryText}
                onChange={(e) => setQueryText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSearch();
                  }
                }}
                disabled={loading}
                autoFocus
              />
              <button
                type="button"
                className="btn p"
                id="go"
                disabled={loading || !queryText.trim()}
                onClick={() => handleSearch()}
              >
                <SearchIcon size={18} />
                <span>{loading ? "Mencari…" : "Cari"}</span>
              </button>
            </div>
          </section>

          {/* Hasil Pencarian (Muncul di bawah Search Query di Kolom Kiri) */}
          {result && (
            <div className="qk-results-container">
              <div className="card cp">
                <div className="row" style={{ flexWrap: "wrap", gap: "10px" }}>
                  <h2 style={{ fontSize: "16px", margin: 0, fontWeight: 700 }}>
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
                      marginTop: "12px",
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
              </div>

              {result.results.length === 0 ? (
                <div className="card cp emp">
                  <h3>Tidak ada potongan dokumen yang memenuhi kriteria</h3>
                  <p>
                    Semua potongan dokumen memiliki kemiripan di bawah batas minimum <b>{threshold}</b>.
                    <br />
                    Coba turunkan <b>Batas kemiripan minimum</b> (misal ke <code>0.20</code>) atau gunakan kata kunci lain.
                  </p>
                </div>
              ) : (
                result.results.map((r, index) => {
                  const scoreStyle = getScoreColor(r.similarity_score);
                  return (
                    <div key={r.chunk_id} className="card cp qk-chunk-card">
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
        </div>

        {/* KOLOM KANAN: Konfigurasi */}
        <section className="card qk-right-col" aria-labelledby="cl">
          <button
            type="button"
            className="ch"
            id="tg"
            aria-expanded={isConfigOpen}
            aria-controls="cb"
            onClick={() => setIsConfigOpen((prev) => !prev)}
          >
            <span>
              <h2 id="cl">Konfigurasi pencarian</h2>
              <span className="sm" id="sm" aria-live="polite">
                <span className="tag">{selectedKnowledgeName}</span>
                <span className="tag">{SEARCH_MODE_LABELS[searchMode]}</span>
                <span className="tag">Top {topK}</span>
                <span className="tag">Skor ≥ {threshold.toFixed(2)}</span>
                <span className="tag">{activeTechniquesCount} teknik aktif</span>
              </span>
            </span>
            <svg
              className="chev"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
          <div className="cb" id="cb" hidden={!isConfigOpen}>
            <div className="g">
              <div className="fl">
                <label style={{ display: "block", fontWeight: 600, fontSize: "14px", marginBottom: "8px" }}>
                  Mode pencarian
                </label>
                <div className="seg" id="mode">
                  <label className={searchMode === "hybrid" ? "on" : ""}>
                    <input
                      type="radio"
                      name="m"
                      value="hybrid"
                      checked={searchMode === "hybrid"}
                      onChange={() => setSearchMode("hybrid")}
                      disabled={loading}
                    />
                    Hybrid
                  </label>
                  <label className={searchMode === "dense" ? "on" : ""}>
                    <input
                      type="radio"
                      name="m"
                      value="dense"
                      checked={searchMode === "dense"}
                      onChange={() => setSearchMode("dense")}
                      disabled={loading}
                    />
                    Vector
                  </label>
                  <label className={searchMode === "keyword" ? "on" : ""}>
                    <input
                      type="radio"
                      name="m"
                      value="keyword"
                      checked={searchMode === "keyword"}
                      onChange={() => setSearchMode("keyword")}
                      disabled={loading}
                    />
                    Keyword
                  </label>
                </div>
                <p className="hint" id="mh" style={{ marginTop: "8px", fontSize: "13px", color: "var(--mut)" }}>
                  {SEARCH_MODE_HINTS[searchMode]}
                </p>
              </div>

              <div className="fl">
                <label htmlFor="k">Jumlah hasil (Top K)</label>
                <div className="rg">
                  <input
                    type="range"
                    id="k"
                    min={1}
                    max={20}
                    value={topK}
                    onChange={(e) => setTopK(Number(e.target.value))}
                    disabled={loading}
                  />
                  <span className="val" id="kv">
                    {topK} hasil
                  </span>
                </div>
                <p className="hint">Berapa banyak potongan dokumen yang ditampilkan.</p>
              </div>

              <div className="fl">
                <label htmlFor="t">Batas kemiripan minimum</label>
                <div className="rg">
                  <input
                    type="range"
                    id="t"
                    min={0}
                    max={1}
                    step={0.05}
                    value={threshold}
                    onChange={(e) => setThreshold(Number(e.target.value))}
                    disabled={loading}
                  />
                  <span className="val" id="tv">
                    {Math.round(threshold * 100)}% ({threshold.toFixed(2)})
                  </span>
                </div>
                <p className="hint">Hasil di bawah angka ini tidak ditampilkan. Makin tinggi, makin ketat.</p>
              </div>
            </div>

            <h3>Tingkatkan akurasi</h3>
            <p className="hint" style={{ margin: "0 0 12px" }}>
              Opsional. Mengaktifkan lebih banyak teknik bisa membuat pencarian lebih lama.
            </p>
            <div className="g" style={{ marginTop: 0, gap: "12px" }}>
              <label className="sw">
                <input
                  type="checkbox"
                  id="rr"
                  checked={useRerank}
                  onChange={(e) => setUseRerank(e.target.checked)}
                  disabled={loading}
                />
                <span className="tr"></span>
                <span>
                  <b>Cross-Encoder Reranker</b>
                  <small>Urutkan ulang hasil agar jawaban yang paling relevan berada di posisi teratas.</small>
                </span>
              </label>

              <label className="sw">
                <input
                  type="checkbox"
                  id="qe"
                  checked={useQueryExpansion}
                  onChange={(e) => setUseQueryExpansion(e.target.checked)}
                  disabled={loading}
                />
                <span className="tr"></span>
                <span>
                  <b>Query Expansion</b>
                  <small>Tambah variasi sinonim dan singkatan dari pertanyaan agar tidak ada yang terlewat.</small>
                </span>
              </label>

              <label className="sw">
                <input
                  type="checkbox"
                  id="hy"
                  checked={useHyde}
                  onChange={(e) => setUseHyde(e.target.checked)}
                  disabled={loading}
                />
                <span className="tr"></span>
                <span>
                  <b>HyDE (Hypothetical Document)</b>
                  <small>AI membuat contoh jawaban dulu untuk dicocokkan ke dokumen. Cocok untuk pertanyaan singkat.</small>
                </span>
              </label>

              <label className="sw">
                <input
                  type="checkbox"
                  id="ec"
                  checked={expandContext}
                  onChange={(e) => setExpandContext(e.target.checked)}
                  disabled={loading}
                />
                <span className="tr"></span>
                <span>
                  <b>Expand Context</b>
                  <small>Sertakan paragraf sebelum dan sesudah hasil yang ditemukan agar konteks utuh.</small>
                </span>
              </label>
            </div>

            <div className="ft">
              <button
                type="button"
                className="btn s"
                id="rs"
                disabled={loading}
                onClick={handleResetDefault}
              >
                Kembalikan ke default
              </button>
            </div>
          </div>
        </section>
      </div>

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
