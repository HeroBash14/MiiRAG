import { useCallback, useEffect, useRef, useState } from "react";
import type {
  KnowledgeDetailResponse,
  KnowledgeListItem,
  KnowledgeStatusCounts,
} from "./types";
import {
  createKnowledge,
  deleteKnowledge,
  fetchKnowledgeDetail,
  fetchKnowledges,
  renewKnowledge,
  startKnowledgeEmbedding,
  updateDraftKnowledge,
} from "./api";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { KnowledgeList } from "./components/KnowledgeList";
import { KnowledgeDetail } from "./components/KnowledgeDetail";
import { KnowledgeModal, type ModalMode } from "./components/KnowledgeModal";
import { QueryKnowledgeView } from "./components/QueryKnowledgeView";
import { Toast } from "./components/Toast";

export function App() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = localStorage.getItem("theme");
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  const [currentNav, setCurrentNav] = useState<"knowledge" | "query">("knowledge");
  const [viewMode, setViewMode] = useState<"list" | "detail">("list");
  const [selectedKid, setSelectedKid] = useState<string | null>(null);

  // List data
  const [items, setItems] = useState<KnowledgeListItem[]>([]);
  const [counts, setCounts] = useState<KnowledgeStatusCounts>({
    all: 0,
    unfinished: 0,
    processing: 0,
    done: 0,
  });
  const [filter, setFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Detail data
  const [detail, setDetail] = useState<KnowledgeDetailResponse | null>(null);

  // Modal
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<ModalMode>("create");

  // Toast
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const toastTimeoutRef = useRef<number | null>(null);

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    if (toastTimeoutRef.current) window.clearTimeout(toastTimeoutRef.current);
    toastTimeoutRef.current = window.setTimeout(() => {
      setToastMessage(null);
    }, 3200);
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("theme", next);
    document.documentElement.setAttribute("data-theme", next);
  };

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Load Knowledges List
  const loadList = useCallback(async () => {
    try {
      const res = await fetchKnowledges(searchQuery, filter);
      setItems(res.items);
      setCounts(res.counts);
    } catch (err: unknown) {
      console.error("Gagal memuat daftar knowledge:", err);
    }
  }, [searchQuery, filter]);

  // Load Knowledge Detail
  const loadDetail = useCallback(async (kid: string) => {
    try {
      const res = await fetchKnowledgeDetail(kid);
      setDetail(res);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Gagal memuat detail knowledge");
      setViewMode("list");
    }
  }, [showToast]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    if (viewMode === "detail" && selectedKid) {
      loadDetail(selectedKid);
    }
  }, [viewMode, selectedKid, loadDetail]);

  // Auto-polling when any item is in 'processing' status
  useEffect(() => {
    const hasProcessing =
      counts.processing > 0 || (detail && detail.status === "processing");
    if (!hasProcessing) return;

    const interval = window.setInterval(() => {
      loadList();
      if (viewMode === "detail" && selectedKid) {
        loadDetail(selectedKid);
      }
    }, 2500);

    return () => window.clearInterval(interval);
  }, [counts.processing, detail, viewMode, selectedKid, loadList, loadDetail]);

  // Actions
  const handleSelectKnowledge = (id: string) => {
    setSelectedKid(id);
    setViewMode("detail");
    window.scrollTo(0, 0);
  };

  const handleBackToList = () => {
    setViewMode("list");
    setSelectedKid(null);
    setDetail(null);
    loadList();
  };

  const handleCreateKnowledge = async (
    name: string,
    desc: string,
    files: File[],
    processNow: boolean
  ) => {
    const fd = new FormData();
    fd.append("name", name);
    if (desc) fd.append("description", desc);
    fd.append("process_now", String(processNow));
    files.forEach((f) => fd.append("files", f));

    try {
      const created = await createKnowledge(fd);
      showToast(
        processNow
          ? `“${created.name}” berhasil dibuat, proses embedding dimulai!`
          : `Draft “${created.name}” berhasil disimpan.`
      );
      loadList();
      handleSelectKnowledge(created.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Gagal membuat knowledge";
      showToast(msg);
      throw err;
    }
  };

  const handleUpdateDraft = async (
    name: string,
    desc: string,
    keepDocIds: string[],
    newFiles: File[]
  ) => {
    if (!selectedKid) return;
    const fd = new FormData();
    if (name) fd.append("name", name);
    if (desc !== undefined) fd.append("description", desc);
    keepDocIds.forEach((id) => fd.append("keep_document_ids", id));
    newFiles.forEach((f) => fd.append("files", f));

    try {
      const updated = await updateDraftKnowledge(selectedKid, fd);
      showToast(`Draft “${updated.name}” berhasil diperbarui.`);
      setDetail(updated);
      loadList();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Gagal memperbarui draft";
      showToast(msg);
      throw err;
    }
  };

  const handleRenewKnowledge = async (
    note: string,
    keepDocIds: string[],
    newFiles: File[]
  ) => {
    if (!selectedKid) return;
    const fd = new FormData();
    if (note) fd.append("note", note);
    keepDocIds.forEach((id) => fd.append("keep_document_ids", id));
    newFiles.forEach((f) => fd.append("files", f));

    try {
      const renewed = await renewKnowledge(selectedKid, fd);
      showToast(`Disimpan sebagai versi v${renewed.current_version}`);
      setDetail(renewed);
      loadList();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Gagal melakukan re-new";
      showToast(msg);
      throw err;
    }
  };

  const handleStartProcess = async () => {
    if (!selectedKid) return;
    try {
      const started = await startKnowledgeEmbedding(selectedKid);
      showToast(`Proses embedding untuk “${started.name}” dimulai.`);
      setDetail(started);
      loadList();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Gagal memulai proses embedding.");
    }
  };

  const handleDeleteKnowledge = async () => {
    if (!selectedKid || !detail) return;
    const confirmed = window.confirm(
      `Apakah Anda yakin ingin menghapus knowledge "${detail.name}" beserta seluruh file dan versinya?`
    );
    if (!confirmed) return;

    try {
      await deleteKnowledge(selectedKid);
      showToast(`Knowledge "${detail.name}" berhasil dihapus.`);
      handleBackToList();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Gagal menghapus knowledge.");
    }
  };

  return (
    <div className="app">
      <Sidebar
        currentTab={currentNav}
        onTabChange={(tab) => {
          setCurrentNav(tab);
          if (tab === "knowledge") {
            setViewMode("list");
            setSelectedKid(null);
          }
        }}
      />

      <main className="mn">
        <TopBar theme={theme} onToggleTheme={toggleTheme} />

        <div className="wrap">
          {currentNav === "knowledge" && (
            <>
              {viewMode === "list" ? (
                <KnowledgeList
                  items={items}
                  counts={counts}
                  filter={filter}
                  onFilterChange={setFilter}
                  searchQuery={searchQuery}
                  onSearchChange={setSearchQuery}
                  onOpenCreateModal={() => {
                    setModalMode("create");
                    setModalOpen(true);
                  }}
                  onSelectKnowledge={handleSelectKnowledge}
                />
              ) : (
                detail && (
                  <KnowledgeDetail
                    knowledge={detail}
                    onBack={handleBackToList}
                    onOpenEditDraft={() => {
                      setModalMode("draft");
                      setModalOpen(true);
                    }}
                    onOpenRenew={() => {
                      setModalMode("renew");
                      setModalOpen(true);
                    }}
                    onStartProcess={handleStartProcess}
                    onDelete={handleDeleteKnowledge}
                    onToast={showToast}
                  />
                )
              )}
            </>
          )}

          {currentNav === "query" && (
            <QueryKnowledgeView knowledges={items} onToast={showToast} />
          )}
        </div>
      </main>

      <KnowledgeModal
        isOpen={modalOpen}
        mode={modalMode}
        knowledge={detail}
        onClose={() => setModalOpen(false)}
        onSubmitCreate={handleCreateKnowledge}
        onSubmitDraft={handleUpdateDraft}
        onSubmitRenew={handleRenewKnowledge}
      />

      <Toast message={toastMessage} />
    </div>
  );
}
export default App;
