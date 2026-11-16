export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  if (bytes > 1024 * 1024) {
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }
  return Math.max(1, Math.round(bytes / 1024)) + " KB";
}

export function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("id-ID", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}
