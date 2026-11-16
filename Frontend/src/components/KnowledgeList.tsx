import React from "react";
import type { KnowledgeListItem, KnowledgeStatus, KnowledgeStatusCounts } from "../types";
import { formatDate } from "../utils";
import { CheckIcon } from "./Icons";

interface KnowledgeListProps {
  items: KnowledgeListItem[];
  counts: KnowledgeStatusCounts;
  filter: string;
  onFilterChange: (f: string) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  onOpenCreateModal: () => void;
  onSelectKnowledge: (id: string) => void;
}

const statusBadge = (status: KnowledgeStatus) => {
  switch (status) {
    case "unfinished":
      return (
        <span className="b u">
          <span className="status-dot dot-unfinished" />
          <span>Draft</span>
        </span>
      );
    case "processing":
      return (
        <span className="b p">
          <span className="status-dot dot-processing" />
          <span>Processing</span>
        </span>
      );
    case "done":
      return (
        <span className="b d">
          <CheckIcon size={11} />
          <span>Done</span>
        </span>
      );
  }
};

export const KnowledgeList: React.FC<KnowledgeListProps> = ({
  items,
  counts,
  filter,
  onFilterChange,
  searchQuery,
  onSearchChange,
  onOpenCreateModal,
  onSelectKnowledge,
}) => {
  const filterOptions: [string, string, number][] = [
    ["all", "Semua", counts.all],
    ["unfinished", "Draft", counts.unfinished],
    ["processing", "Processing", counts.processing],
    ["done", "Done", counts.done],
  ];

  return (
    <>
      <div className="hd">
        <div>
          <h1>Knowledge</h1>
          <p className="sub">Kumpulan dokumen yang dipakai AI untuk menjawab pertanyaan.</p>
        </div>
        <button type="button" className="btn p" onClick={onOpenCreateModal}>
          + Buat knowledge
        </button>
      </div>

      <div className="tb">
        <input
          className="in"
          type="search"
          placeholder="Cari knowledge…"
          aria-label="Cari knowledge"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        {filterOptions.map(([key, label, count]) => (
          <button
            key={key}
            type="button"
            className={`chip ${filter === key ? "on" : ""}`}
            onClick={() => onFilterChange(key)}
          >
            {label} ({count})
          </button>
        ))}
      </div>

      {items.length > 0 ? (
        <div className="grid">
          {items.map((k) => {
            const isProcessing = k.status === "processing";
            const percent = k.doc_count > 0 ? (k.embedded_doc_count / k.doc_count) * 100 : 0;

            return (
              <button
                key={k.id}
                type="button"
                className="card"
                onClick={() => onSelectKnowledge(k.id)}
              >
                <span className="row">
                  {statusBadge(k.status)}
                  <span className="v">v{k.current_version}</span>
                </span>
                <span className="t">{k.name}</span>
                <span className="card-desc">{k.description || "Tidak ada deskripsi"}</span>

                {isProcessing && (
                  <>
                    <div className="bar">
                      <i style={{ width: `${percent}%` }} />
                    </div>
                    <div className="pl">
                      {k.embedded_doc_count} dari {k.doc_count} dokumen sudah di-embed
                    </div>
                  </>
                )}

                <span className="m">
                  <span>{k.doc_count} dokumen</span>
                  <span>Diperbarui {formatDate(k.updated_at)}</span>
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="box emp">
          <h2>{counts.all > 0 ? "Tidak ada hasil" : "Belum ada knowledge"}</h2>
          <p>
            {counts.all > 0
              ? "Coba ubah kata kunci pencarian atau filter status."
              : "Upload dokumen pertama Anda untuk memulai."}
          </p>
          {counts.all === 0 && (
            <button type="button" className="btn p" onClick={onOpenCreateModal}>
              + Buat knowledge
            </button>
          )}
        </div>
      )}
    </>
  );
};
