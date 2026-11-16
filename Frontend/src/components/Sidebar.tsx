import React from "react";
import { BookIcon, BrandLogo, SearchIcon } from "./Icons";

interface SidebarProps {
  currentTab: "knowledge" | "query";
  onTabChange: (tab: "knowledge" | "query") => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentTab, onTabChange }) => {
  return (
    <aside className="sb">
      <div className="logo" onClick={() => onTabChange("knowledge")}>
        <BrandLogo size={24} />
        <span>
          <b>Mii</b>RAG
        </span>
      </div>

      <div className="nav-group">
        <div className="nav-label">Workspace</div>
        <button
          type="button"
          className={`nv ${currentTab === "knowledge" ? "on" : ""}`}
          onClick={() => onTabChange("knowledge")}
          aria-current={currentTab === "knowledge" ? "page" : undefined}
        >
          <BookIcon size={16} />
          <span>Knowledge</span>
        </button>
        <button
          type="button"
          className={`nv ${currentTab === "query" ? "on" : ""}`}
          onClick={() => onTabChange("query")}
          aria-current={currentTab === "query" ? "page" : undefined}
        >
          <SearchIcon size={16} />
          <span>Query Knowledge</span>
        </button>
      </div>

      <div className="sb-footer">
        <div className="sb-badge">
          <span className="dot-live" />
          <span>BAAI/bge-m3 · MinIO</span>
        </div>
      </div>
    </aside>
  );
};
