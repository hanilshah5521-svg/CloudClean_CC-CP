import { request } from "./api.js";

const post = (path, body) => request(path, { method: "POST", ...(body ? { body: JSON.stringify(body) } : {}) });

export const s3Api = {
  overview: () => request("/api/s3"),
  iamPolicy: () => request("/api/s3/iam-policy"),
  connect: (accessKeyId, secretAccessKey, region) =>
    post("/api/s3/connect", { access_key_id: accessKeyId, secret_access_key: secretAccessKey, region }),
  connectDemo: () => post("/api/s3/connect-demo"),
  disconnect: () => request("/api/s3/connection", { method: "DELETE" }),
  scan: () => post("/api/s3/scan"),
  preview: (recId) => request(`/api/s3/recommendations/${recId}/preview`),
  apply: (recId) => post(`/api/s3/recommendations/${recId}/apply`),
  duplicates: () => request("/api/s3/duplicates"),
  trashDuplicates: (bucketId, group, keepObjectId) =>
    post("/api/s3/duplicates/trash", { bucket_id: bucketId, group, keep_object_id: keepObjectId }),
  compression: () => request("/api/s3/compression"),
  compress: (objectId) => post(`/api/s3/objects/${objectId}/compress`),
  history: () => request("/api/s3/history"),
  undo: (actionId) => post(`/api/s3/history/${actionId}/undo`),
};

export function formatUsd(value) {
  if (!value) return "$0.00";
  if (value > 0 && value < 0.01) return "<$0.01";
  return `$${value.toFixed(2)}`;
}

// Storage classes on an emerald ramp (colors in index.css): stronger = pricier / more frequently accessed.
export const CLASS_META = {
  STANDARD: { label: "Standard", color: "rgb(var(--cls-standard))" },
  REDUCED_REDUNDANCY: { label: "Reduced Redundancy", color: "rgb(var(--cls-rrs))" },
  INTELLIGENT_TIERING: { label: "Intelligent-Tiering", color: "rgb(var(--cls-intelligent))" },
  STANDARD_IA: { label: "Standard-IA", color: "rgb(var(--cls-ia))" },
  ONEZONE_IA: { label: "One Zone-IA", color: "rgb(var(--cls-onezone))" },
  GLACIER_IR: { label: "Glacier Instant", color: "rgb(var(--cls-glacier-ir))" },
  GLACIER: { label: "Glacier Flexible", color: "rgb(var(--cls-glacier))" },
  DEEP_ARCHIVE: { label: "Deep Archive", color: "rgb(var(--cls-deep))" },
};
