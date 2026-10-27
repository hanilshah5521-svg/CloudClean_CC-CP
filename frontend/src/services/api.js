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
  // Full-page navigation (not fetch): the server stores OAuth state + PKCE
  // verifier in the session cookie, then redirects to Google.
  googleLoginUrl: `${BASE_URL}/auth/google/login`,
  logout: () => request("/auth/logout", { method: "POST" }),
  getUser: () => request("/api/user"),
  // Which sign-in options the server offers (Google configured? Gmail requested?)
  getAuthStatus: () => request("/auth/status"),

  // Linked Google accounts (one profile, several accounts)
  getAccounts: () => request("/api/accounts"),
  switchAccount: (id) => request(`/api/accounts/${id}/switch`, { method: "POST" }),
  removeAccount: (id) => request(`/api/accounts/${id}`, { method: "DELETE" }),
  addSimulatedAccount: () => request("/api/accounts/simulated", { method: "POST" }),
  // Full-page navigation: sign in to another Google account and link it here.
  googleLinkUrl: `${BASE_URL}/auth/google/link`,
  scanAllAccounts: () => request("/api/accounts/scan", { method: "POST" }),
  activeAccountScans: () => request("/api/accounts/scan"),
  getCrossDuplicates: (accountId) => request(`/api/accounts/duplicates${accountId ? `?account_id=${accountId}` : ""}`),
  removeCrossCopies: (keepFileId, removeFileIds) =>
    request("/api/accounts/duplicates/remove", {
      method: "POST",
      body: JSON.stringify({ keep_file_id: keepFileId, remove_file_ids: removeFileIds }),
    }),

  // Storage
  getStorage: () => request("/api/storage"),
  getSavings: () => request("/api/savings"),

  // Analysis — returns a background job (Demo Mode: already finished)
  analyze: () => request("/api/analyze", { method: "POST" }),
  getAnalysis: () => request("/api/analysis"),

  // Background jobs
  getJob: (jobId) => request(`/api/jobs/${jobId}`),
  listJobs: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/api/jobs${qs ? `?${qs}` : ""}`);
  },

  // Recommendations
  getRecommendations: () => request("/api/recommendations"),

  // Analytics
  getBreakdown: () => request("/api/analytics/breakdown"),
  getStorageHistory: (range = "30d") => request(`/api/analytics/history?range=${range}`),

  // Duplicates
  getDuplicates: () => request("/api/duplicates"),
  trashDuplicates: (groupId, keepDriveId, acknowledgeDifferentContent = false) =>
    request(`/api/duplicates/${groupId}/trash`, {
      method: "POST",
      body: JSON.stringify({ keep_drive_id: keepDriveId, acknowledge_different_content: acknowledgeDifferentContent }),
    }),

  // Compression
  getCompressionCandidates: () => request("/api/compression/candidates"),
  compressFile: (fileId) => request(`/api/compression/${fileId}`, { method: "POST" }),
  getVideoCandidates: () => request("/api/compression/video-candidates"),
  compressVideo: (fileId) => request(`/api/compression/${fileId}/video`, { method: "POST" }),

  // Auto-compression rules
  getRules: () => request("/api/rules"),
  createRule: (body) => request("/api/rules", { method: "POST", body: JSON.stringify(body) }),
  updateRule: (ruleId, body) => request(`/api/rules/${ruleId}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteRule: (ruleId) => request(`/api/rules/${ruleId}`, { method: "DELETE" }),
  runRules: () => request("/api/rules/run", { method: "POST" }),
  getSuggestions: (status = "open") => request(`/api/rules/suggestions?status=${status}`),
  applySuggestion: (id) => request(`/api/rules/suggestions/${id}/apply`, { method: "POST" }),
  dismissSuggestion: (id) => request(`/api/rules/suggestions/${id}/dismiss`, { method: "POST" }),

  // Archive: inactive files the last scan suggested bundling into one ZIP
  getArchiveCandidates: () => request("/api/files?filter=archive_candidate&page_size=200"),
  archiveFiles: (fileIds, archiveName) =>
    request("/api/archive", {
      method: "POST",
      body: JSON.stringify({ file_ids: fileIds, archive_name: archiveName }),
    }),

  // Organize (group files by naming convention into folders)
  getOrganizeSuggestions: () => request("/api/organize"),
  applyOrganize: (id, folderName) =>
    request(`/api/organize/${id}/apply`, { method: "POST", body: JSON.stringify({ folder_name: folderName }) }),
  dismissOrganize: (id) => request(`/api/organize/${id}/dismiss`, { method: "POST" }),

  // History
  getHistory: () => request("/api/history"),
  // Undoing a large/video compression returns { job_id, job } — poll it.
  restoreAction: (actionId) => request(`/api/history/${actionId}/restore`, { method: "POST" }),
  // Permanently delete a compressed file's kept original version (no Undo after).
  freeSpace: (actionId) => request(`/api/history/${actionId}/free-space`, { method: "POST" }),

  // Settings
  getSettings: () => request("/api/settings"),
  updateSettings: (body) => request("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
};

export { ApiError, BASE_URL, request };
