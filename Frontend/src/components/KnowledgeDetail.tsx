import React, { useState } from "react";
import type { DocumentStatus, KnowledgeDetailResponse, QueryResponse } from "../types";
import { formatBytes, formatDate } from "../utils";
import { executeQuery } from "../api";
import { CheckIcon } from "./Icons";
import { MarkdownContent } from "./MarkdownContent";

interface KnowledgeDetailProps {
  knowledge: KnowledgeDetailResponse;
  onBack: () => void;
  onOpenEditDraft: () => void;
  onOpenRenew: () => void;
  onStartProcess: () => void;
  onDelete: () => void;
  onToast: (msg: string) => void;
}

const docStatusBadge = (s: DocumentStatus, kStatus: string) => {
  if (kStatus === "unfinished") {
    return (
      <span className="b u">
        <span className="status-dot dot-unfinished" />
        <span>Belum diproses</span>
      </span>
    );
  }
  switch (s) {
    case "waiting":
      return (
        <span className="b u">
          <span className="status-dot dot-unfinished" />
          <span>Menunggu</span>
        </span>
      );
    case "processing":
      return (
        <span className="b p">
          <span className="status-dot dot-processing" />
          <span>Sedang di-embed…</span>
        </span>
      );
    case "embedded":
      return (
        <span className="b d">
          <CheckIcon size={11} />
          <span>Selesai</span>
        </span>
      );
    case "failed":
      return (
        <span className="b f">
          <span className="status-dot dot-failed" />
          <span>Gagal</span>
        </span>
      );
  }
};

export const KnowledgeDetail: React.FC<KnowledgeDetailProps> = ({
  knowledge,
  onBack,
  onOpenEditDraft,
  onOpenRenew,
  onStartProcess,
  onDelete,
  onToast,
}) => {
  const [activeTab, setActiveTab] = useState<"docs" | "hist" | "query">("docs");

  // Query search state
  const [queryText, setQueryText] = useState("");
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);

  const isBusy = knowledge.status === "processing";
  const percent =
    knowledge.doc_count > 0
      ? (knowledge.embedded_doc_count / knowledge.doc_count) * 100
      : 0;

  const hint = {
    unfinished: "Draft belum diproses. Klik “Mulai proses embedding” agar knowledge bisa dipakai.",
    processing: "Dokumen sedang di-embed. Re-new bisa dilakukan setelah proses selesai.",
    done: "Semua dokumen sudah di-embed. Knowledge siap dipakai.",
  }[knowledge.status];

  const handleRunQuery = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!queryText.trim()) return;
    setQueryLoading(true);
    try {
      const res = await executeQuery({
        query: queryText.trim(),
        knowledge_ids: [knowledge.id],
        top_k: 5,
        score_threshold: 0.3,
      });
      setQueryResult(res);
      if (res.results.length === 0) {
        onToast("Tidak ada potongan dokumen yang memenuhi ambang batas (threshold).");
      }
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "Gagal menjalankan pencarian.");
    } finally {
      setQueryLoading(false);
    }
  };

  return (
    <div>
      <button type="button" className="back" onClick={onBack}>
        ← Kembali ke daftar
      </button>

      <div className="hd">
        <div>
          <h1>
            {knowledge.name} <span className="v">v{knowledge.current_version}</span>
          </h1>
          <p className="sub">{knowledge.description || "Tidak ada deskripsi."}</p>
        </div>
        <div className="row">
          {knowledge.status === "unfinished" ? (
            <>
              <button type="button" className="btn" onClick={onOpenEditDraft}>
                Edit draft
              </button>
              <button type="button" className="btn p" onClick={onStartProcess}>
                Mulai proses embedding
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn p"
              onClick={onOpenRenew}
              disabled={isBusy}
              title={isBusy ? "Tunggu proses embedding selesai" : undefined}
            >
              Re-new → v{knowledge.current_version + 1}
            </button>
          )}

          <button
            type="button"
            className="btn danger"
            onClick={onDelete}
            disabled={isBusy}
            title={isBusy ? "Tidak dapat menghapus saat sedang di-embed" : "Hapus knowledge ini"}
          >
            Hapus
          </button>
        </div>
      </div>

      <div className="box">
        <div className="row">
          {knowledge.status === "unfinished" && (
            <span className="b u">
              <span className="status-dot dot-unfinished" />
              <span>Draft</span>
            </span>
          )}
          {knowledge.status === "processing" && (
            <span className="b p">
              <span className="status-dot dot-processing" />
              <span>Processing</span>
            </span>
          )}
          {knowledge.status === "done" && (
            <span className="b d">
              <CheckIcon size={11} />
              <span>Done</span>
            </span>
          )}
          <span className="sub">{knowledge.documents.length} dokumen</span>
        </div>

        {isBusy && (
          <>
            <div className="bar">
              <i style={{ width: `${percent}%` }} />
            </div>
            <div className="pl">
              {knowledge.embedded_doc_count} dari {knowledge.doc_count} dokumen sudah di-embed
            </div>
          </>
        )}
        <p className="sub" style={{ marginTop: "10px" }}>
          {hint}
        </p>
      </div>

      <div className="box">
        <div className="tabs">
          <button
            type="button"
            className={`tab ${activeTab === "docs" ? "on" : ""}`}
            onClick={() => setActiveTab("docs")}
          >
            Dokumen ({knowledge.documents.length})
          </button>
          <button
            type="button"
            className={`tab ${activeTab === "hist" ? "on" : ""}`}
            onClick={() => setActiveTab("hist")}
          >
            Riwayat versi ({knowledge.version_history.length})
          </button>
          <button
            type="button"
            className={`tab ${activeTab === "query" ? "on" : ""}`}
            onClick={() => setActiveTab("query")}
          >
            🔍 Uji Similarity Search
          </button>
        </div>

        {activeTab === "docs" && (
          <div>
            {knowledge.documents.length > 0 ? (
              knowledge.documents.map((d) => (
                <div key={d.id} className="li">
                  <span className="n">
                    {d.filename}
                    <small>{formatBytes(d.file_size)}</small>
                    {d.page_count > 0 && (
                      <small style={{ color: "var(--mut)" }}> · {d.page_count} hal</small>
                    )}
                    {d.chunk_count > 0 && (
                      <small style={{ color: "var(--mut)" }}> · {d.chunk_count} chunks</small>
                    )}
                  </span>
                  <div>
                    {docStatusBadge(d.status, knowledge.status)}
                    {d.error_message && (
                      <span
                        className="sub"
                        style={{ color: "var(--rd)", marginLeft: "8px", fontSize: "12px" }}
                        title={d.error_message}
                      >
                        (Error: {d.error_message.slice(0, 30)}...)
                      </span>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <p className="sub" style={{ padding: "16px 0", textAlign: "center" }}>
                Belum ada dokumen dalam knowledge ini.
              </p>
            )}
          </div>
        )}

        {activeTab === "hist" && (
          <div>
            {knowledge.version_history.length > 0 ? (
              knowledge.version_history.map((h) => (
                <div key={h.id} className="li">
                  <span className="n">
                    <b>v{h.version_number}</b> <small>{formatDate(h.created_at)}</small>
                    <br />
                    <span className="sub">
                      {h.note || "Tanpa catatan"} · {h.doc_count} dokumen
                    </span>
                  </span>
                  {h.is_active ? (
                    <span className="b d">Versi aktif</span>
                  ) : (
                    <span className="sub" style={{ fontSize: "12px" }}>
                      Arsip
                    </span>
                  )}
                </div>
              ))
            ) : (
              <div className="emp">
                Belum ada versi tersimpan. Riwayat versi muncul setelah knowledge diproses.
              </div>
            )}
          </div>
        )}

        {activeTab === "query" && (
          <div style={{ marginTop: "12px" }}>
            <p className="sub" style={{ marginBottom: "14px" }}>
              Uji pencarian kesamaan vector (Cosine Similarity) di dalam dokumen knowledge ini tanpa
              menggunakan LLM.
            </p>

            <form onSubmit={handleRunQuery} className="query-box">
              <div className="query-row">
                <input
                  className="in"
                  style={{ flex: 1 }}
                  placeholder="Ketik pertanyaan atau kata kunci, contoh: cara klaim atau syarat polis..."
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  disabled={queryLoading}
                />
                <button
                  type="submit"
                  className="btn p"
                  disabled={queryLoading || !queryText.trim()}
                >
                  {queryLoading ? "Mencari..." : "Cari Similarity"}
                </button>
              </div>
            </form>

            {queryResult && (
              <div style={{ marginTop: "18px" }}>
                <div className="row" style={{ marginBottom: "10px" }}>
                  <h3>Hasil Pencarian ({queryResult.total_results} potongan ditemukan)</h3>
                  <span className="sub" style={{ fontSize: "12px" }}>
                    Latensi: {queryResult.latency_ms} ms
                  </span>
                </div>

                {queryResult.results.length === 0 ? (
                  <p className="sub" style={{ textAlign: "center", padding: "16px 0" }}>
                    Tidak ada potongan teks yang cocok dengan ambang batas (threshold).
                  </p>
                ) : (
                  queryResult.results.map((item) => (
                    <div key={item.chunk_id} className="query-result-card">
                      <div className="row" style={{ marginBottom: "8px" }}>
                        <span style={{ fontWeight: 600, fontSize: "14px" }}>
                          📄 {item.filename} (Hal. {item.page_number}, Chunk #{item.chunk_index})
                        </span>
                        <span className="score-badge">
                          {(item.similarity_score * 100).toFixed(1)}% Cocok
                        </span>
                      </div>
                      <MarkdownContent content={item.content} />
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
