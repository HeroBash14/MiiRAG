import React, { useEffect, useState } from "react";
import type { DocumentItem, KnowledgeDetailResponse } from "../types";
import { formatBytes } from "../utils";

export type ModalMode = "create" | "draft" | "renew";

interface KnowledgeModalProps {
  isOpen: boolean;
  mode: ModalMode;
  knowledge?: KnowledgeDetailResponse | null;
  onClose: () => void;
  onSubmitCreate: (name: string, desc: string, files: File[], processNow: boolean) => Promise<void>;
  onSubmitDraft: (
    name: string,
    desc: string,
    keepDocIds: string[],
    newFiles: File[]
  ) => Promise<void>;
  onSubmitRenew: (note: string, keepDocIds: string[], newFiles: File[]) => Promise<void>;
}

export const KnowledgeModal: React.FC<KnowledgeModalProps> = ({
  isOpen,
  mode,
  knowledge,
  onClose,
  onSubmitCreate,
  onSubmitDraft,
  onSubmitRenew,
}) => {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [note, setNote] = useState("");
  const [keptExistingDocs, setKeptExistingDocs] = useState<DocumentItem[]>([]);
  const [newFiles, setNewFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (isOpen) {
      if (mode === "create") {
        setName("");
        setDescription("");
        setNote("");
        setKeptExistingDocs([]);
        setNewFiles([]);
      } else if (knowledge) {
        setName(knowledge.name);
        setDescription(knowledge.description || "");
        setNote("");
        setKeptExistingDocs([...knowledge.documents]);
        setNewFiles([]);
      }
    }
  }, [isOpen, mode, knowledge]);

  const handleFileChange = (incoming: FileList | null) => {
    if (!incoming) return;
    const added: File[] = [];
    for (let i = 0; i < incoming.length; i++) {
      const file = incoming[i];
      const nameLower = file.name.toLowerCase();
      if (
        nameLower.endsWith(".pdf") ||
        nameLower.endsWith(".docx") ||
        nameLower.endsWith(".pptx") ||
        nameLower.endsWith(".xlsx") ||
        nameLower.endsWith(".csv")
      ) {
        if (!newFiles.some((f) => f.name === file.name)) {
          added.push(file);
        }
      }
    }
    setNewFiles((prev) => [...prev, ...added]);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    handleFileChange(e.dataTransfer.files);
  };

  const removeExistingDoc = (docId: string) => {
    setKeptExistingDocs((prev) => prev.filter((d) => d.id !== docId));
  };

  const removeNewFile = (index: number) => {
    setNewFiles((prev) => prev.filter((_, idx) => idx !== index));
  };

  const handleSave = async (processNow: boolean) => {
    setIsSubmitting(true);
    try {
      if (mode === "create") {
        await onSubmitCreate(name, description, newFiles, processNow);
      } else if (mode === "draft") {
        await onSubmitDraft(
          name,
          description,
          keptExistingDocs.map((d) => d.id),
          newFiles
        );
      } else if (mode === "renew") {
        await onSubmitRenew(
          note,
          keptExistingDocs.map((d) => d.id),
          newFiles
        );
      }
      onClose();
    } catch {
      // Error handled by parent toast
    } finally {
      setIsSubmitting(false);
    }
  };

  const titles: Record<ModalMode, string> = {
    create: "Buat knowledge baru",
    draft: "Edit draft",
    renew: `Re-new: ${knowledge?.name || ""}`,
  };

  const subtitles: Record<ModalMode, string> = {
    create:
      "Upload satu atau lebih dokumen (PDF, Word, PowerPoint, Excel, atau CSV). Anda bisa menyimpannya sebagai draft dan memprosesnya nanti.",
    draft: "Perbarui detail draft atau tambahkan/kurangi dokumen.",
    renew: `Perubahan akan disimpan sebagai versi v${
      (knowledge?.current_version || 1) + 1
    }. Dokumen yang tidak berubah tidak di-embed ulang.`,
  };

  if (!isOpen) return null;

  return (
    <div>
      <button type="button" className="back" onClick={onClose} disabled={isSubmitting}>
        ← {mode === "create" ? "Kembali ke daftar" : "Kembali ke detail"}
      </button>

      <div className="hd">
        <div>
          <h1 id="modal-title">{titles[mode]}</h1>
          <p className="sub">{subtitles[mode]}</p>
        </div>
      </div>

      <div className="md">
        {mode === "renew" ? (
          <>
            <label className="f" htmlFor="modal-note" style={{ marginTop: 0 }}>
              Catatan perubahan (opsional)
            </label>
            <input
              className="in"
              id="modal-note"
              placeholder="Contoh: Tambah polis terbaru dan hapus form lama"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={isSubmitting}
              autoFocus
            />
          </>
        ) : (
          <>
            <label className="f" htmlFor="modal-name" style={{ marginTop: 0 }}>
              Nama knowledge
            </label>
            <input
              className="in"
              id="modal-name"
              placeholder="Contoh: SOP Klaim Asuransi"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isSubmitting}
              autoFocus
            />

            <label className="f" htmlFor="modal-desc">
              Deskripsi (opsional)
            </label>
            <input
              className="in"
              id="modal-desc"
              placeholder="Isi singkat knowledge ini"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={isSubmitting}
            />
          </>
        )}

        <label
          className={`dz ${isDragging ? "on" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragEnter={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            setIsDragging(false);
          }}
          onDrop={handleDrop}
        >
          <input
            type="file"
            multiple
            hidden
            accept=".pdf,.docx,.pptx,.xlsx,.csv,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            onChange={(e) => {
              handleFileChange(e.target.files);
              e.target.value = "";
            }}
            disabled={isSubmitting}
          />
          <b>Tarik file PDF, Word, PowerPoint, Excel (.xlsx), atau CSV ke sini</b> atau klik untuk memilih
          <br />
          <small>Mendukung format PDF (.pdf), Word (.docx), PowerPoint (.pptx), Excel (.xlsx), dan CSV (.csv)</small>
        </label>

        <div className="ls">
          {keptExistingDocs.length === 0 && newFiles.length === 0 ? (
            <p className="sub" style={{ textAlign: "center", margin: "14px 0" }}>
              Belum ada dokumen dipilih.
            </p>
          ) : (
            <>
              {keptExistingDocs.map((doc) => (
                <div key={doc.id} className="li">
                  <span className="n">
                    {doc.filename}
                    <small>{formatBytes(doc.file_size)}</small>
                  </span>
                  <button
                    type="button"
                    className="x"
                    onClick={() => removeExistingDoc(doc.id)}
                    aria-label={`Hapus ${doc.filename}`}
                    disabled={isSubmitting}
                  >
                    Hapus
                  </button>
                </div>
              ))}
              {newFiles.map((file, idx) => (
                <div key={idx} className="li">
                  <span className="n">
                    {file.name}
                    <small>{formatBytes(file.size)}</small>
                    <span className="b p" style={{ marginLeft: "8px" }}>
                      Baru
                    </span>
                  </span>
                  <button
                    type="button"
                    className="x"
                    onClick={() => removeNewFile(idx)}
                    aria-label={`Hapus ${file.name}`}
                    disabled={isSubmitting}
                  >
                    Hapus
                  </button>
                </div>
              ))}
            </>
          )}
        </div>

        <div className="ft">
          <button
            type="button"
            className="btn"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Batal
          </button>
          {mode === "renew" ? (
            <button
              type="button"
              className="btn p"
              onClick={() => handleSave(true)}
              disabled={isSubmitting}
            >
              {isSubmitting
                ? "Menyimpan..."
                : `Simpan sebagai v${(knowledge?.current_version || 1) + 1}`}
            </button>
          ) : (
            <>
              <button
                type="button"
                className="btn"
                onClick={() => handleSave(false)}
                disabled={isSubmitting}
              >
                {isSubmitting ? "Menyimpan..." : "Simpan draft"}
              </button>
              <button
                type="button"
                className="btn p"
                onClick={() => handleSave(true)}
                disabled={isSubmitting}
              >
                {isSubmitting ? "Memproses..." : "Simpan & proses"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
