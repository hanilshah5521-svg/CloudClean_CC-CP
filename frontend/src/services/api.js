const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed (${status})`);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // Auth
  demoLogin: () => request("/auth/demo", { method: "POST" }),
  googleAuthUrl: () => request("/auth/google/url"),
  logout: () => request("/auth/logout", { method: "POST" }),
  getUser: () => request("/api/user"),

  // Storage
  getStorage: () => request("/api/storage"),
  getSavings: () => request("/api/savings"),

  // Analysis
  analyze: () => request("/api/analyze", { method: "POST" }),
  getAnalysis: () => request("/api/analysis"),

  // Recommendations
  getRecommendations: () => request("/api/recommendations"),

  // Analytics
  getBreakdown: () => request("/api/analytics/breakdown"),
  getStorageHistory: (range = "30d") => request(`/api/analytics/history?range=${range}`),

  // Files
  getFiles: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/api/files${qs ? `?${qs}` : ""}`);
  },

  // Duplicates
  getDuplicates: () => request("/api/duplicates"),
  trashDuplicates: (groupId, keepDriveId) =>
    request(`/api/duplicates/${groupId}/trash`, {
      method: "POST",
      body: JSON.stringify({ keep_drive_id: keepDriveId }),
    }),

  // Compression
  getCompressionCandidates: () => request("/api/compression/candidates"),
  compressFile: (fileId) => request(`/api/compression/${fileId}`, { method: "POST" }),

  // Archive
  archiveFiles: (fileIds, archiveName) =>
    request("/api/archive", {
      method: "POST",
      body: JSON.stringify({ file_ids: fileIds, archive_name: archiveName }),
    }),

  // History
  getHistory: () => request("/api/history"),
  restoreAction: (actionId) => request(`/api/history/${actionId}/restore`, { method: "POST" }),

  // Settings
  getSettings: () => request("/api/settings"),
  updateSettings: (body) => request("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
};

export { ApiError, BASE_URL };
