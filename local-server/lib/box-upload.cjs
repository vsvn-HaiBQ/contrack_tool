const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const BOX_API_BASE = "https://api.box.com/2.0";
const BOX_UPLOAD_BASE = "https://upload.box.com/api/2.0";

async function uploadArtifactsToBox(input) {
  const accessToken = stringValue(input && (input.accessToken || input.access_token), "accessToken");
  const artifacts = Array.isArray(input && input.artifacts) ? input.artifacts : [];
  if (!artifacts.length) {
    throw new Error("No artifacts to upload");
  }
  const folderMap = normalizeFolderMap(input || {});
  const sharedLinkAccess = normalizeSharedLinkAccess(input && (input.sharedLinkAccess || input.shared_link_access));
  const overwriteOnConflict = Boolean(input && (input.overwrite || input.overwrite_on_conflict));
  const dateFolderName = currentDateFolderName();
  const items = [];

  for (const artifact of artifacts) {
    const artifactType = stringValue(artifact && artifact.type, "artifact.type").toLowerCase();
    const filePath = path.resolve(stringValue(artifact && artifact.path, "artifact.path"));
    const stat = fs.existsSync(filePath) ? fs.statSync(filePath) : null;
    if (!stat || !stat.isFile()) {
      throw new Error(`Artifact file not found: ${filePath}`);
    }
    const parentFolderId = folderMap[artifactType];
    if (!parentFolderId) {
      throw new Error(`Box folder id is not configured for artifact type: ${artifactType}`);
    }
    const dayFolder = await ensureFolder(accessToken, parentFolderId, dateFolderName);
    const requestedName = stringValue(artifact.file_name || artifact.fileName || path.basename(filePath), "artifact.file_name");
    const uploaded = await uploadFileWithConflictRetry(accessToken, dayFolder.id, filePath, requestedName, { overwriteOnConflict });
    const linked = await ensureSharedLink(accessToken, uploaded.id, sharedLinkAccess);
    items.push({
      type: artifactType,
      fileName: linked.name || uploaded.name || requestedName,
      sourcePath: filePath,
      parentFolderId,
      dateFolderId: dayFolder.id,
      dateFolderName,
      boxFileId: linked.id || uploaded.id,
      sharedLink: linked.shared_link && linked.shared_link.url,
    });
  }

  return { date_folder_name: dateFolderName, items };
}

function normalizeFolderMap(input) {
  const rawMap = input.folderMap || input.folder_map || {};
  const clientFolderId = input.clientFolderId || input.client_folder_id || rawMap.client;
  const serverFolderId = input.serverFolderId || input.server_folder_id || rawMap.server;
  return {
    client: normalizeFolderId(clientFolderId),
    server: normalizeFolderId(serverFolderId),
  };
}

function normalizeFolderId(value) {
  if (value === 0 || value === "0") {
    return "0";
  }
  const text = String(value || "").trim();
  return text || null;
}

function normalizeSharedLinkAccess(value) {
  const text = String(value || "company").trim();
  if (!["open", "company", "collaborators"].includes(text)) {
    throw new Error("sharedLinkAccess must be open, company, or collaborators");
  }
  return text;
}

function stringValue(value, name) {
  const text = String(value || "").trim();
  if (!text) {
    throw new Error(`${name} is required`);
  }
  return text;
}

function currentDateFolderName(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}${month}${day}`;
}

async function ensureFolder(accessToken, parentFolderId, folderName) {
  const existing = await findChildFolder(accessToken, parentFolderId, folderName);
  if (existing) {
    return existing;
  }
  try {
    return await boxJson(accessToken, `${BOX_API_BASE}/folders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: folderName, parent: { id: parentFolderId } }),
    });
  } catch (error) {
    if (error.status === 409) {
      const retry = await findChildFolder(accessToken, parentFolderId, folderName);
      if (retry) {
        return retry;
      }
    }
    throw error;
  }
}

async function findChildFolder(accessToken, parentFolderId, folderName) {
  let offset = 0;
  const limit = 1000;
  while (true) {
    const url = `${BOX_API_BASE}/folders/${encodeURIComponent(parentFolderId)}/items?limit=${limit}&offset=${offset}&fields=id,type,name`;
    const payload = await boxJson(accessToken, url);
    const entries = Array.isArray(payload.entries) ? payload.entries : [];
    const found = entries.find((entry) => entry && entry.type === "folder" && entry.name === folderName);
    if (found) {
      return found;
    }
    const total = Number(payload.total_count || 0);
    offset += entries.length;
    if (!entries.length || offset >= total) {
      return null;
    }
  }
}

async function uploadFileWithConflictRetry(accessToken, folderId, filePath, fileName, options = {}) {
  const overwriteOnConflict = Boolean(options && options.overwriteOnConflict);
  try {
    return await uploadFile(accessToken, folderId, filePath, fileName);
  } catch (error) {
    if (error.status !== 409) {
      throw error;
    }
    if (overwriteOnConflict) {
      const conflictId = extractConflictFileId(error.payload);
      if (conflictId) {
        return uploadFileVersion(accessToken, conflictId, filePath, fileName);
      }
    }
    return uploadFile(accessToken, folderId, filePath, timestampedFileName(fileName));
  }
}

function extractConflictFileId(payload) {
  const conflicts = payload && payload.context_info && payload.context_info.conflicts;
  if (!conflicts) return null;
  if (Array.isArray(conflicts)) {
    const item = conflicts.find((entry) => entry && entry.type === "file" && entry.id);
    return item ? item.id : null;
  }
  if (conflicts.type === "file" && conflicts.id) {
    return conflicts.id;
  }
  return null;
}

async function uploadFileVersion(accessToken, fileId, filePath, fileName) {
  const boundary = `----contrack-box-${crypto.randomBytes(12).toString("hex")}`;
  const attributes = JSON.stringify({ name: fileName });
  const fileBuffer = fs.readFileSync(filePath);
  const body = Buffer.concat([
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="attributes"\r\nContent-Type: application/json\r\n\r\n${attributes}\r\n`, "utf8"),
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${safeFileName(fileName)}"\r\nContent-Type: application/octet-stream\r\n\r\n`, "utf8"),
    fileBuffer,
    Buffer.from(`\r\n--${boundary}--\r\n`, "utf8"),
  ]);
  const payload = await boxJson(accessToken, `${BOX_UPLOAD_BASE}/files/${encodeURIComponent(fileId)}/content`, {
    method: "POST",
    headers: { "Content-Type": `multipart/form-data; boundary=${boundary}` },
    body,
  });
  const entry = Array.isArray(payload.entries) ? payload.entries[0] : null;
  if (!entry || !entry.id) {
    throw new Error("Box version upload response did not include a file id");
  }
  return entry;
}

async function uploadFile(accessToken, folderId, filePath, fileName) {
  const boundary = `----contrack-box-${crypto.randomBytes(12).toString("hex")}`;
  const attributes = JSON.stringify({ name: fileName, parent: { id: folderId } });
  const fileBuffer = fs.readFileSync(filePath);
  const body = Buffer.concat([
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="attributes"\r\nContent-Type: application/json\r\n\r\n${attributes}\r\n`, "utf8"),
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${safeFileName(fileName)}"\r\nContent-Type: application/octet-stream\r\n\r\n`, "utf8"),
    fileBuffer,
    Buffer.from(`\r\n--${boundary}--\r\n`, "utf8"),
  ]);
  const payload = await boxJson(accessToken, `${BOX_UPLOAD_BASE}/files/content`, {
    method: "POST",
    headers: { "Content-Type": `multipart/form-data; boundary=${boundary}` },
    body,
  });
  const entry = Array.isArray(payload.entries) ? payload.entries[0] : null;
  if (!entry || !entry.id) {
    throw new Error("Box upload response did not include a file id");
  }
  return entry;
}

async function ensureSharedLink(accessToken, fileId, access) {
  return boxJson(accessToken, `${BOX_API_BASE}/files/${encodeURIComponent(fileId)}?fields=id,name,shared_link`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shared_link: { access } }),
  });
}

async function boxJson(accessToken, url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { message: text };
    }
  }
  if (!response.ok) {
    const error = new Error(boxErrorMessage(payload, `Box request failed with status ${response.status}`));
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function boxErrorMessage(payload, fallback) {
  if (payload && typeof payload === "object") {
    for (const key of ["message", "error_description", "error"]) {
      const value = payload[key];
      if (typeof value === "string" && value.trim()) {
        return value.trim();
      }
    }
  }
  return fallback;
}

function timestampedFileName(fileName) {
  const ext = path.extname(fileName);
  const base = path.basename(fileName, ext);
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
  return `${base}_${stamp}${ext}`;
}

function safeFileName(fileName) {
  return String(fileName).replace(/["\r\n]/g, "_");
}

module.exports = {
  currentDateFolderName,
  uploadArtifactsToBox,
};
