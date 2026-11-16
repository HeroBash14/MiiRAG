import React from "react";
import { MoonIcon, SunIcon } from "./Icons";

interface TopBarProps {
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({ theme, onToggleTheme }) => {
  return (
    <header className="top">
      <div className="top-breadcrumb">
        <span className="top-dot" />
        <span>Knowledge Base</span>
      </div>
      <div className="r">
        <button
          type="button"
          className="theme-toggle"
          onClick={onToggleTheme}
          aria-label="Ubah tema warna"
          title="Ubah tema"
        >
          {theme === "dark" ? (
            <>
              <SunIcon size={14} />
              <span>Light</span>
            </>
          ) : (
            <>
              <MoonIcon size={14} />
              <span>Dark</span>
            </>
          )}
        </button>
      </div>
    </header>
  );
};
