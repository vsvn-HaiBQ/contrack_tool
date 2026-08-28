const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const sessions = new Map();
const previewJobs = new Map();
const exactDiffCellLimit = 50_000_000;

function git(repoPath, args, options = {}) {
  const result = spawnSync("git", args, {
    cwd: repoPath,
    encoding: options.encoding || "buffer",
    env: { ...tokenEnv(options.token), ...(options.env || {}) },
    input: options.input,
    maxBuffer: 1024 * 1024 * 100,
  });
  if (result.error) {
    throw new Error(result.error.code === "ENOENT" ? "git command is not available" : result.error.message);
  }
  if (options.check !== false && result.status !== 0) {
    const stderr = Buffer.isBuffer(result.stderr) ? result.stderr.toString("utf8") : String(result.stderr || "");
    const stdout = Buffer.isBuffer(result.stdout) ? result.stdout.toString("utf8") : String(result.stdout || "");
    throw new Error((stderr || stdout || `git ${args.join(" ")} failed`).trim());
  }
  return result.stdout;
}

function gitAsync(repoPath, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn("git", args, {
      cwd: repoPath,
      env: { ...tokenEnv(options.token), ...(options.env || {}) },
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => {
      stderr.push(chunk);
      if (typeof options.onProgress === "function") {
        for (const rawLine of chunk.toString("utf8").split(/[\r\n]+/)) {
          const line = rawLine.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "").trim();
          if (line) options.onProgress(line);
        }
      }
    });
    child.on("error", (error) => {
      reject(new Error(error.code === "ENOENT" ? "git command is not available" : error.message));
    });
    child.on("close", (code) => {
      const output = Buffer.concat(stdout);
      if (code === 0 || options.check === false) {
        resolve(output);
        return;
      }
      const errorOutput = Buffer.concat(stderr).toString("utf8").trim() || output.toString("utf8").trim();
      reject(new Error(errorOutput || `git ${args.join(" ")} failed`));
    });
  });
}

function tokenEnv(token) {
  if (!token) {
    return process.env;
  }
  const encoded = Buffer.from(`x-access-token:${token}`, "utf8").toString("base64");
  return {
    ...process.env,
    GIT_TERMINAL_PROMPT: "0",
    GIT_CONFIG_COUNT: "1",
    GIT_CONFIG_KEY_0: "http.https://github.com/.extraheader",
    GIT_CONFIG_VALUE_0: `AUTHORIZATION: basic ${encoded}`,
  };
}

function gitText(repoPath, args, options = {}) {
  return git(repoPath, args, { ...options, encoding: "buffer" }).toString("utf8").replace(/\r?\n$/, "");
}

function ensureRepo(repoPath) {
  if (!repoPath || !fs.existsSync(repoPath)) {
    throw new Error("Source folder does not exist");
  }
  const inside = gitText(repoPath, ["rev-parse", "--is-inside-work-tree"]);
  if (inside.trim() !== "true") {
    throw new Error("Source folder is not a git working tree");
  }
  return gitText(repoPath, ["rev-parse", "--show-toplevel"]).trim();
}

function normalizeRepo(repo) {
  const value = String(repo || "").trim();
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(value)) {
    throw new Error("git_repo must use owner/repo format in system settings");
  }
  return value;
}

function isEmptyDirectory(folder) {
  return fs.existsSync(folder)
    && fs.statSync(folder).isDirectory()
    && fs.readdirSync(folder).length === 0;
}

function normalizeSourceBranch(repoPath, branch) {
  const value = String(branch || "").trim().replace(/^(?:origin\/|refs\/heads\/|refs\/remotes\/origin\/)/, "");
  if (!value || value.startsWith("-")) {
    throw new Error("sourceBranch is required");
  }
  git(repoPath, ["check-ref-format", "--branch", value]);
  return value;
}

async function ensureBranchRepository({ sourceFolder, repo, githubToken, gitUserName, gitUserEmail, onStatus }) {
  const report = onStatus || (() => {});
  const reportProgress = (step) => (line) => report(`${step}: ${line}`);
  const target = path.resolve(String(sourceFolder || "").trim());
  if (!sourceFolder || !String(sourceFolder).trim()) {
    throw new Error("Local clone folder is required");
  }
  if (fs.existsSync(target) && !fs.statSync(target).isDirectory()) {
    throw new Error("Local clone folder must be a directory");
  }
  const normalizedRepo = normalizeRepo(repo);
  const repoUrl = `https://github.com/${normalizedRepo}.git`;
  if (!fs.existsSync(target) || isEmptyDirectory(target)) {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    report(`Cloning ${normalizedRepo} locally`);
    await gitAsync(path.dirname(target), ["-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "clone", "--progress", "--", repoUrl, target], {
      token: githubToken,
      onProgress: reportProgress("Cloning"),
    });
  } else {
    report("Using existing local clone");
  }

  const repoPath = ensureRepo(target);
  report("Configuring local repository");
  git(repoPath, ["config", "core.autocrlf", "false"]);
  git(repoPath, ["config", "core.safecrlf", "false"]);
  if (gitUserName) git(repoPath, ["config", "user.name", String(gitUserName)]);
  if (gitUserEmail) git(repoPath, ["config", "user.email", String(gitUserEmail)]);
  git(repoPath, ["remote", "set-url", "origin", repoUrl]);
  report("Reverting tracked local changes");
  await gitAsync(repoPath, ["reset", "--hard", "HEAD"], {
    token: githubToken,
    onProgress: reportProgress("Reverting"),
  });
  report("Fetching origin");
  await gitAsync(repoPath, ["fetch", "--prune", "--progress", "origin"], {
    token: githubToken,
    onProgress: reportProgress("Fetching"),
  });
  return { repoPath, repo: normalizedRepo };
}

function parseChangedFiles(raw) {
  const tokens = raw
    .toString("utf8")
    .split("\0")
    .filter(Boolean);
  const files = [];
  let index = 0;
  while (index < tokens.length) {
    const statusToken = tokens[index++];
    const code = statusToken[0];
    let oldPath = null;
    let filePath = null;
    if (code === "R" || code === "C") {
      oldPath = tokens[index++];
      filePath = tokens[index++];
    } else {
      filePath = tokens[index++];
    }
    if (!filePath) {
      break;
    }
    files.push({ path: filePath, old_path: oldPath, status: statusName(code) });
  }
  return files;
}

function statusName(code) {
  return {
    A: "added",
    C: "copied",
    D: "deleted",
    M: "modified",
    R: "renamed",
    T: "type_changed",
    U: "unmerged",
  }[code] || String(code || "").toLowerCase();
}

function safeFile(repoPath, relativePath) {
  if (!relativePath || relativePath.includes("\0") || path.isAbsolute(relativePath)) {
    throw new Error("Invalid file path");
  }
  const root = path.resolve(repoPath);
  const target = path.resolve(root, relativePath);
  if (!target.startsWith(root + path.sep) && target !== root) {
    throw new Error("File path is outside source folder");
  }
  return target;
}

function gitObject(repoPath, rev, relativePath) {
  return git(repoPath, ["show", `${rev}:${relativePath}`]);
}

function gitObjectForWorktree(repoPath, rev, relativePath) {
  return git(repoPath, ["cat-file", "--filters", `--path=${relativePath}`, `${rev}:${relativePath}`]);
}

function worktreeBytes(repoPath, relativePath) {
  const absolute = safeFile(repoPath, relativePath);
  if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) {
    throw new Error(`File does not exist in working tree: ${relativePath}`);
  }
  return fs.readFileSync(absolute);
}

function isBinary(buffer) {
  return buffer.includes(0);
}

function splitLines(buffer) {
  const lines = [];
  let start = 0;
  let index = 0;
  while (index < buffer.length) {
    const byte = buffer[index];
    if (byte === 10) {
      const crlf = index > start && buffer[index - 1] === 13;
      const contentEnd = crlf ? index - 1 : index;
      lines.push({ content: buffer.subarray(start, contentEnd), eol: crlf ? "\r\n" : "\n" });
      index += 1;
      start = index;
    } else if (byte === 13) {
      if (index + 1 < buffer.length && buffer[index + 1] === 10) {
        index += 1;
      } else {
        lines.push({ content: buffer.subarray(start, index), eol: "\r" });
        index += 1;
        start = index;
      }
    } else {
      index += 1;
    }
  }
  if (start < buffer.length) {
    lines.push({ content: buffer.subarray(start), eol: "" });
  }
  return lines;
}

function joinLines(lines) {
  return Buffer.concat(lines.map((line) => Buffer.concat([line.content, Buffer.from(line.eol)])));
}

function eolSummary(lines) {
  const counts = {
    lf: lines.filter((line) => line.eol === "\n").length,
    crlf: lines.filter((line) => line.eol === "\r\n").length,
    cr: lines.filter((line) => line.eol === "\r").length,
  };
  const found = Object.entries(counts).filter(([, count]) => count > 0).map(([key]) => key);
  if (found.length > 1) return "mixed";
  if (found.length === 1) return found[0];
  return "none";
}

function lineKeys(lines) {
  return lines.map((line) => line.content.toString("latin1"));
}

function opcodes(leftLines, rightLines) {
  const left = lineKeys(leftLines);
  const right = lineKeys(rightLines);
  return normalizeOpcodes(diffRangeOpcodes(left, right, 0, left.length, 0, right.length));
}

function diffRangeOpcodes(left, right, i1, i2, j1, j2) {
  const raw = [];
  let prefix = 0;
  while (i1 + prefix < i2 && j1 + prefix < j2 && left[i1 + prefix] === right[j1 + prefix]) {
    prefix += 1;
  }
  if (prefix > 0) {
    raw.push({ tag: "equal", i1, i2: i1 + prefix, j1, j2: j1 + prefix });
  }

  let suffix = 0;
  while (
    i1 + prefix + suffix < i2 &&
    j1 + prefix + suffix < j2 &&
    left[i2 - suffix - 1] === right[j2 - suffix - 1]
  ) {
    suffix += 1;
  }

  const middleI1 = i1 + prefix;
  const middleI2 = i2 - suffix;
  const middleJ1 = j1 + prefix;
  const middleJ2 = j2 - suffix;
  if (middleI1 < middleI2 || middleJ1 < middleJ2) {
    raw.push(...middleOpcodes(left, right, middleI1, middleI2, middleJ1, middleJ2));
  }

  if (suffix > 0) {
    raw.push({ tag: "equal", i1: i2 - suffix, i2, j1: j2 - suffix, j2 });
  }
  return normalizeOpcodes(raw);
}

function middleOpcodes(left, right, i1, i2, j1, j2) {
  if (i1 >= i2) {
    return [{ tag: "insert", i1, i2, j1, j2 }];
  }
  if (j1 >= j2) {
    return [{ tag: "delete", i1, i2, j1, j2 }];
  }
  if ((i2 - i1) * (j2 - j1) <= exactDiffCellLimit) {
    return exactOpcodes(left, right, i1, i2, j1, j2);
  }

  const anchors = uniqueAnchors(left, right, i1, i2, j1, j2);
  if (!anchors.length) {
    return positionalOpcodes(left, right, i1, i2, j1, j2);
  }

  const raw = [];
  let lastI = i1;
  let lastJ = j1;
  for (const anchor of anchors) {
    raw.push(...diffRangeOpcodes(left, right, lastI, anchor.i, lastJ, anchor.j));
    raw.push({ tag: "equal", i1: anchor.i, i2: anchor.i + 1, j1: anchor.j, j2: anchor.j + 1 });
    lastI = anchor.i + 1;
    lastJ = anchor.j + 1;
  }
  raw.push(...diffRangeOpcodes(left, right, lastI, i2, lastJ, j2));
  return normalizeOpcodes(raw);
}

function exactOpcodes(left, right, leftStart, leftEnd, rightStart, rightEnd) {
  const width = rightEnd - rightStart;
  const height = leftEnd - leftStart;
  const dp = Array.from({ length: height + 1 }, () => new Uint32Array(width + 1));
  for (let i = height - 1; i >= 0; i -= 1) {
    for (let j = width - 1; j >= 0; j -= 1) {
      dp[i][j] = left[leftStart + i] === right[rightStart + j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const raw = [];
  let i = 0;
  let j = 0;
  while (i < height || j < width) {
    if (i < height && j < width && left[leftStart + i] === right[rightStart + j]) {
      const startI = i;
      const startJ = j;
      while (i < height && j < width && left[leftStart + i] === right[rightStart + j]) {
        i += 1;
        j += 1;
      }
      raw.push({ tag: "equal", i1: leftStart + startI, i2: leftStart + i, j1: rightStart + startJ, j2: rightStart + j });
    } else if (j >= width || (i < height && dp[i + 1][j] >= dp[i][j + 1])) {
      const startI = i;
      while (
        i < height &&
        (j >= width || dp[i + 1][j] >= dp[i][j + 1]) &&
        !(j < width && left[leftStart + i] === right[rightStart + j])
      ) {
        i += 1;
      }
      raw.push({ tag: "delete", i1: leftStart + startI, i2: leftStart + i, j1: rightStart + j, j2: rightStart + j });
    } else {
      const startJ = j;
      while (
        j < width &&
        (i >= height || dp[i + 1][j] < dp[i][j + 1]) &&
        !(i < height && left[leftStart + i] === right[rightStart + j])
      ) {
        j += 1;
      }
      raw.push({ tag: "insert", i1: leftStart + i, i2: leftStart + i, j1: rightStart + startJ, j2: rightStart + j });
    }
  }
  return normalizeOpcodes(raw);
}

function uniqueAnchors(left, right, i1, i2, j1, j2) {
  const leftInfo = new Map();
  const rightInfo = new Map();
  for (let i = i1; i < i2; i += 1) {
    const key = left[i];
    const info = leftInfo.get(key);
    if (info) {
      info.count += 1;
    } else {
      leftInfo.set(key, { count: 1, pos: i });
    }
  }
  for (let j = j1; j < j2; j += 1) {
    const key = right[j];
    const info = rightInfo.get(key);
    if (info) {
      info.count += 1;
    } else {
      rightInfo.set(key, { count: 1, pos: j });
    }
  }

  const candidates = [];
  for (let i = i1; i < i2; i += 1) {
    const key = left[i];
    const leftMatch = leftInfo.get(key);
    const rightMatch = rightInfo.get(key);
    if (leftMatch?.count === 1 && rightMatch?.count === 1) {
      candidates.push({ i, j: rightMatch.pos });
    }
  }
  return longestIncreasingAnchors(candidates);
}

function longestIncreasingAnchors(candidates) {
  if (!candidates.length) {
    return [];
  }
  const tails = [];
  const tailIndexes = [];
  const previous = new Array(candidates.length).fill(-1);
  for (let index = 0; index < candidates.length; index += 1) {
    const value = candidates[index].j;
    let low = 0;
    let high = tails.length;
    while (low < high) {
      const mid = Math.floor((low + high) / 2);
      if (tails[mid] < value) {
        low = mid + 1;
      } else {
        high = mid;
      }
    }
    if (low > 0) {
      previous[index] = tailIndexes[low - 1];
    }
    tails[low] = value;
    tailIndexes[low] = index;
  }

  const result = [];
  let index = tailIndexes[tails.length - 1];
  while (index >= 0) {
    result.push(candidates[index]);
    index = previous[index];
  }
  result.reverse();
  return result;
}

function positionalOpcodes(left, right, i1 = 0, i2 = left.length, j1 = 0, j2 = right.length) {
  const raw = [];
  const middleLeftStart = i1;
  const middleRightStart = j1;
  const middleLeftEnd = i2;
  const middleRightEnd = j2;
  const paired = Math.min(middleLeftEnd - middleLeftStart, middleRightEnd - middleRightStart);
  let index = 0;
  while (index < paired) {
    const leftIndex = middleLeftStart + index;
    const rightIndex = middleRightStart + index;
    const tag = left[leftIndex] === right[rightIndex] ? "equal" : "replace";
    const start = index;
    index += 1;
    while (
      index < paired &&
      (left[middleLeftStart + index] === right[middleRightStart + index]) === (tag === "equal")
    ) {
      index += 1;
    }
    raw.push({
      tag,
      i1: middleLeftStart + start,
      i2: middleLeftStart + index,
      j1: middleRightStart + start,
      j2: middleRightStart + index,
    });
  }
  if (middleLeftEnd - middleLeftStart > paired) {
    raw.push({
      tag: "delete",
      i1: middleLeftStart + paired,
      i2: middleLeftEnd,
      j1: middleRightStart + paired,
      j2: middleRightStart + paired,
    });
  }
  if (middleRightEnd - middleRightStart > paired) {
    raw.push({
      tag: "insert",
      i1: middleLeftStart + paired,
      i2: middleLeftStart + paired,
      j1: middleRightStart + paired,
      j2: middleRightEnd,
    });
  }
  return normalizeOpcodes(raw);
}

function normalizeOpcodes(raw) {
  const result = [];
  for (let index = 0; index < raw.length; index += 1) {
    const current = raw[index];
    if (!current || (current.i1 === current.i2 && current.j1 === current.j2)) {
      continue;
    }
    const next = raw[index + 1];
    if (current.tag === "delete" && next && next.tag === "insert" && current.i2 === next.i1 && current.j1 === next.j1) {
      appendOpcode(result, { tag: "replace", i1: current.i1, i2: current.i2, j1: next.j1, j2: next.j2 });
      index += 1;
    } else if (current.tag === "insert" && next && next.tag === "delete" && current.i1 === next.i1 && current.j2 === next.j1) {
      appendOpcode(result, { tag: "replace", i1: next.i1, i2: next.i2, j1: current.j1, j2: current.j2 });
      index += 1;
    } else {
      appendOpcode(result, current);
    }
  }
  return result;
}

function appendOpcode(result, current) {
  const previous = result[result.length - 1];
  if (
    previous &&
    previous.tag === current.tag &&
    previous.i2 === current.i1 &&
    previous.j2 === current.j1
  ) {
    previous.i2 = current.i2;
    previous.j2 = current.j2;
  } else {
    result.push({ ...current });
  }
}

function diffStats(baseBytes, sourceBytes) {
  const baseLines = splitLines(baseBytes);
  const sourceLines = splitLines(sourceBytes);
  let changedLines = 0;
  let eolOnlyLines = 0;
  let spaceOnlyLines = 0;
  for (const op of opcodes(baseLines, sourceLines)) {
    if (op.tag === "equal") {
      for (let offset = 0; offset < op.i2 - op.i1; offset += 1) {
        if (sourceLines[op.j1 + offset].eol !== baseLines[op.i1 + offset].eol) {
          eolOnlyLines += 1;
        }
      }
    } else {
      changedLines += Math.max(op.i2 - op.i1, op.j2 - op.j1);
      if (op.tag === "replace") {
        for (let offset = 0; offset < Math.min(op.i2 - op.i1, op.j2 - op.j1); offset += 1) {
          if (isSpaceOnlyContentChange(baseLines[op.i1 + offset].content, sourceLines[op.j1 + offset].content)) {
            spaceOnlyLines += 1;
          }
        }
      }
    }
  }
  return {
    base_eol: eolSummary(baseLines),
    source_eol: eolSummary(sourceLines),
    changed_lines: changedLines,
    eol_only_lines: eolOnlyLines,
    space_only_lines: spaceOnlyLines,
  };
}

function isSpaceOnlyContentChange(baseContent, sourceContent) {
  return !baseContent.equals(sourceContent)
    && baseContent.toString("latin1").replace(/^[ \t]+|[ \t]+$/g, "")
      === sourceContent.toString("latin1").replace(/^[ \t]+|[ \t]+$/g, "");
}

function prepareWorkingTreePreview({ sourceFolder }) {
  const repoPath = ensureRepo(sourceFolder);
  const head = gitText(repoPath, ["rev-parse", "HEAD"]).trim();
  const branch = gitText(repoPath, ["branch", "--show-current"]).trim() || "HEAD";
  const changed = parseChangedFiles(git(repoPath, ["diff", "--name-status", "-z", "-M", "HEAD", "--"]));
  return { repoPath, head, branch, changed };
}

function finishWorkingTreePreview({ repoPath, head, branch }, files) {
  const sourceSnapshots = new Map();
  for (const file of files) {
    if (!file.processable) {
      continue;
    }
    try {
      sourceSnapshots.set(file.path, worktreeBytes(repoPath, file.path));
    } catch {
      // Preview already captured processability; ignore files that disappear after preview.
    }
  }
  const sessionId = crypto.randomBytes(16).toString("hex");
  const preview = {
    session_id: sessionId,
    base_branch: "HEAD",
    source_branch: branch,
    merge_base: head,
    files,
  };
  sessions.set(sessionId, {
    user_id: "local-node",
    mode: "working_tree",
    repoPath,
    head,
    files,
    fixed_files: [],
    fixed_blobs: new Map(),
    source_snapshots: sourceSnapshots,
    commit_sha: null,
  });
  return preview;
}

function previewWorkingTree(input) {
  const context = prepareWorkingTreePreview(input);
  const files = context.changed
    .map((entry) => previewFile(context.repoPath, entry))
    .filter((file) => file.processable && (file.eol_only_lines > 0 || file.space_only_lines > 0));
  return finishWorkingTreePreview(context, files);
}

function startWorkingTreePreview(input) {
  const jobId = crypto.randomBytes(16).toString("hex");
  const job = {
    job_id: jobId,
    status: "running",
    current: 0,
    total: 0,
    path: "",
    result: null,
    error: null,
  };
  previewJobs.set(jobId, job);

  setImmediate(() => {
    try {
      const context = prepareWorkingTreePreview(input);
      job.total = context.changed.length;
      const files = [];
      let index = 0;
      const scanNext = () => {
        if (index >= context.changed.length) {
          job.result = finishWorkingTreePreview(context, files);
          job.status = "succeeded";
          return;
        }
        const entry = context.changed[index];
        job.current = index + 1;
        job.path = entry.path;
        const file = previewFile(context.repoPath, entry);
        if (file.processable && (file.eol_only_lines > 0 || file.space_only_lines > 0)) {
          files.push(file);
        }
        index += 1;
        setImmediate(scanNext);
      };
      scanNext();
    } catch (error) {
      job.status = "failed";
      job.error = error && error.message ? error.message : String(error);
    }
  });
  return { job_id: jobId, status: job.status };
}

function getWorkingTreePreviewJob(jobId) {
  const job = previewJobs.get(jobId);
  if (!job) {
    throw new Error("Git EOL local preview job has expired");
  }
  return job;
}

function resolveBranchRef(repoPath, branch, fieldName) {
  const value = String(branch || "").trim();
  if (!value || value.startsWith("-")) {
    throw new Error(`${fieldName} is required`);
  }
  const candidates = value.startsWith("origin/") ? [value] : [`origin/${value}`, value];
  for (const candidate of candidates) {
    if (git(repoPath, ["rev-parse", "--verify", "--quiet", `${candidate}^{commit}`], { check: false }).length) {
      return candidate;
    }
  }
  throw new Error(`${fieldName} does not exist locally or on origin`);
}

async function prepareBranchPreview({ sourceFolder, repo, githubToken, gitUserName, gitUserEmail, baseBranch, sourceBranch }, onStatus) {
  const { repoPath } = await ensureBranchRepository({
    sourceFolder,
    repo,
    githubToken,
    gitUserName,
    gitUserEmail,
    onStatus,
  });
  const sourceBranchName = normalizeSourceBranch(repoPath, sourceBranch);
  const baseRef = resolveBranchRef(repoPath, baseBranch, "baseBranch");
  const sourceRef = `origin/${sourceBranchName}`;
  if (!git(repoPath, ["rev-parse", "--verify", "--quiet", `${sourceRef}^{commit}`], { check: false }).length) {
    throw new Error("sourceBranch does not exist on origin");
  }

  const reportProgress = (step) => (line) => {
    if (onStatus) onStatus(`${step}: ${line}`);
  };
  const localSourceRef = `refs/heads/${sourceBranchName}`;
  if (git(repoPath, ["rev-parse", "--verify", "--quiet", `${localSourceRef}^{commit}`], { check: false }).length) {
    if (onStatus) onStatus(`Switching to ${sourceBranchName}`);
    await gitAsync(repoPath, ["checkout", sourceBranchName], {
      token: githubToken,
      onProgress: reportProgress("Switching branch"),
    });
  } else {
    if (onStatus) onStatus(`Creating local branch ${sourceBranchName}`);
    await gitAsync(repoPath, ["checkout", "--track", "-b", sourceBranchName, sourceRef], {
      token: githubToken,
      onProgress: reportProgress("Switching branch"),
    });
  }
  if (onStatus) onStatus(`Pulling latest ${sourceBranchName}`);
  await gitAsync(repoPath, ["pull", "--ff-only", "origin", sourceBranchName], {
    token: githubToken,
    onProgress: reportProgress("Pulling"),
  });
  const mergeBase = gitText(repoPath, ["merge-base", baseRef, "HEAD"]).trim();
  if (!mergeBase) {
    throw new Error("Could not find merge-base");
  }
  const changed = parseChangedFiles(git(repoPath, ["diff", "--name-status", "-z", "-M", mergeBase, "HEAD", "--"]));
  return {
    repoPath,
    baseBranch: String(baseBranch).trim(),
    mergeBase,
    sourceBranch: sourceBranchName,
    changed,
  };
}

function previewBranchFile(context, entry) {
  if (!["modified", "renamed"].includes(entry.status)) {
    return {
      path: entry.path,
      old_path: entry.old_path,
      status: entry.status,
      selected: false,
      processable: false,
      reason: entry.status,
      changed_lines: 0,
      eol_only_lines: 0,
      space_only_lines: 0,
    };
  }
  try {
    const oldPath = entry.old_path || entry.path;
    // Branch compare must use the committed bytes.  Reading the checkout here
    // would let core.autocrlf or .gitattributes change the preview.
    const baseBytes = gitObject(context.repoPath, context.mergeBase, oldPath);
    const sourceBytes = gitObject(context.repoPath, "HEAD", entry.path);
    if (isBinary(baseBytes) || isBinary(sourceBytes)) {
      return { ...entry, selected: false, processable: false, reason: "Binary file", changed_lines: 0, eol_only_lines: 0, space_only_lines: 0 };
    }
    return {
      path: entry.path,
      old_path: entry.old_path,
      status: entry.status,
      selected: true,
      processable: true,
      ...diffStats(baseBytes, sourceBytes),
    };
  } catch (error) {
    return {
      path: entry.path,
      old_path: entry.old_path,
      status: entry.status,
      selected: false,
      processable: false,
      reason: error.message,
      changed_lines: 0,
      eol_only_lines: 0,
      space_only_lines: 0,
    };
  }
}

function finishBranchPreview(context, files) {
  const sessionId = crypto.randomBytes(16).toString("hex");
  const preview = {
    session_id: sessionId,
    base_branch: context.baseBranch,
    source_branch: context.sourceBranch,
    merge_base: context.mergeBase,
    files,
  };
  sessions.set(sessionId, {
    user_id: "local-node",
    mode: "branch",
    repoPath: context.repoPath,
    base_ref: context.mergeBase,
    source_branch: context.sourceBranch,
    files,
    fixed_files: [],
    fixed_blobs: new Map(),
    commit_sha: null,
  });
  return preview;
}

function startBranchPreview(input) {
  const jobId = crypto.randomBytes(16).toString("hex");
  const job = { job_id: jobId, status: "running", current: 0, total: 0, path: "", message: "Preparing local repository", result: null, error: null };
  previewJobs.set(jobId, job);
  setImmediate(async () => {
    let context;
    try {
      context = await prepareBranchPreview(input, (message) => { job.message = message; });
      job.total = context.changed.length;
      job.message = "Scanning changed files";
    } catch (error) {
      job.status = "failed";
      job.error = error && error.message ? error.message : String(error);
      return;
    }
    const files = [];
    let index = 0;
    const scanNext = () => {
      try {
        if (index >= context.changed.length) {
          job.result = finishBranchPreview(context, files);
          job.status = "succeeded";
          return;
        }
        const entry = context.changed[index];
        job.current = index + 1;
        job.path = entry.path;
        const file = previewBranchFile(context, entry);
        if (file.processable && (file.eol_only_lines > 0 || file.space_only_lines > 0)) files.push(file);
        index += 1;
        setImmediate(scanNext);
      } catch (error) {
        job.status = "failed";
        job.error = error && error.message ? error.message : String(error);
      }
    };
    scanNext();
  });
  return { job_id: jobId, status: job.status };
}

function previewFile(repoPath, entry) {
  if (!["modified", "renamed"].includes(entry.status)) {
    return {
      path: entry.path,
      old_path: entry.old_path,
      status: entry.status,
      selected: false,
      processable: false,
      reason: entry.status,
      changed_lines: 0,
      eol_only_lines: 0,
      space_only_lines: 0,
    };
  }
  try {
    const oldPath = entry.old_path || entry.path;
    const baseBytes = gitObjectForWorktree(repoPath, "HEAD", oldPath);
    const sourceBytes = worktreeBytes(repoPath, entry.path);
    if (isBinary(baseBytes) || isBinary(sourceBytes)) {
      return {
        ...entry,
        selected: false,
        processable: false,
        reason: "Binary file",
        changed_lines: 0,
        eol_only_lines: 0,
        space_only_lines: 0,
      };
    }
    const stats = diffStats(baseBytes, sourceBytes);
    return {
      path: entry.path,
      old_path: entry.old_path,
      status: entry.status,
      selected: true,
      processable: true,
      ...stats,
    };
  } catch (error) {
    return {
      path: entry.path,
      old_path: entry.old_path,
      status: entry.status,
      selected: false,
      processable: false,
      reason: error.message,
      changed_lines: 0,
      eol_only_lines: 0,
      space_only_lines: 0,
    };
  }
}

function session(sessionId) {
  const value = sessions.get(sessionId);
  if (!value) {
    throw new Error("Git EOL local session has expired");
  }
  return value;
}

function structuredDiff(input = {}) {
  const sessionId = input.sessionId ?? input.session_id;
  const filePath = input.path;
  const value = session(sessionId);
  const entry = value.files.find((item) => item.path === filePath);
  if (!entry) {
    throw new Error("File is not part of the preview");
  }
  const oldPath = entry.old_path || filePath;
  const includeFixed = Boolean(input.includeFixed || input.include_fixed);
  const isBranch = value.mode === "branch";
  const worktreePath = value.worktreePath || value.repoPath;
  const baseRef = value.base_ref || "HEAD";
  let baseBytes = Buffer.alloc(0);
  let sourceBytes = Buffer.alloc(0);
  try {
    baseBytes = isBranch
      ? gitObject(worktreePath, baseRef, oldPath)
      : gitObjectForWorktree(value.repoPath, "HEAD", oldPath);
  } catch {
    baseBytes = Buffer.alloc(0);
  }
  try {
    if (isBranch) {
      sourceBytes = includeFixed
        ? worktreeBytes(worktreePath, filePath)
        : gitObject(worktreePath, "HEAD", filePath);
    } else {
      sourceBytes = includeFixed
        ? worktreeBytes(value.repoPath, filePath)
        : value.source_snapshots?.get(filePath) || worktreeBytes(value.repoPath, filePath);
    }
  } catch {
    sourceBytes = Buffer.alloc(0);
  }
  if (isBinary(baseBytes) || isBinary(sourceBytes)) {
    return { session_id: sessionId, path: filePath, binary: true, rows: [], stats: { added: 0, removed: 0, changed: 0, eol_only: 0, space_only: 0 } };
  }
  const baseLines = splitLines(baseBytes);
  const sourceLines = splitLines(sourceBytes);
  const fixedEolLines = includeFixed
    ? new Set(
        (value.fixed_files || [])
          .filter((item) => item.path === filePath)
          .flatMap((item) => item.fixed_eol_lines || [])
          .filter((line) => Number.isInteger(line))
      )
    : new Set();
  const fixedSpaceOnlyLines = includeFixed
    ? new Set(
        (value.fixed_files || [])
          .filter((item) => item.path === filePath)
          .flatMap((item) => item.fixed_space_only_lines || [])
          .filter((line) => Number.isInteger(line))
      )
    : new Set();
  const range = hiddenRange(input);
  if (range) {
    const rows = equalRangeRows(baseLines, sourceLines, range, fixedEolLines, fixedSpaceOnlyLines);
    return { session_id: sessionId, path: filePath, binary: false, rows, stats: { added: 0, removed: 0, changed: 0, eol_only: 0, space_only: 0 } };
  }
  return {
    session_id: sessionId,
    path: filePath,
    binary: false,
    ...buildSideBySideRows(baseLines, sourceLines, {
      fixedEolLines,
      fixedSpaceOnlyLines,
      foldUnchanged: parseBoolean(input.foldUnchanged ?? input.fold_unchanged, false),
      context: positiveInt(input.context, 3, 0, 50),
    }),
  };
}

function buildSideBySideRows(baseLines, sourceLines, {
  fixedEolLines = new Set(),
  fixedSpaceOnlyLines = new Set(),
  foldUnchanged = false,
  context = 3,
} = {}) {
  const rows = [];
  const stats = { added: 0, removed: 0, changed: 0, eol_only: 0, space_only: 0 };
  const ops = displayOpcodes(baseLines, sourceLines, fixedEolLines, fixedSpaceOnlyLines);
  for (let opIndex = 0; opIndex < ops.length; opIndex += 1) {
    const op = ops[opIndex];
    if (op.tag === "equal") {
      const count = op.i2 - op.i1;
      const hasBefore = opIndex > 0;
      const hasAfter = opIndex < ops.length - 1;
      const head = foldUnchanged && hasBefore ? Math.min(context, count) : 0;
      const tail = foldUnchanged && hasAfter ? Math.min(context, count - head) : 0;
      const hidden = foldUnchanged ? count - head - tail : 0;
      const shouldFold = hidden > 0 && count >= context * 2 + 1;

      const appendEqualRows = (startOffset, endOffset) => {
        for (let offset = startOffset; offset < endOffset; offset += 1) {
          const left = baseLines[op.i1 + offset];
          const right = sourceLines[op.j1 + offset];
          const eolDiff = left.eol !== right.eol;
          if (eolDiff) stats.eol_only += 1;
          rows.push({ type: eolDiff ? "eol" : "equal", left: side(left, op.i1 + offset + 1), right: side(right, op.j1 + offset + 1) });
        }
      };

      if (!shouldFold) {
        appendEqualRows(0, count);
      } else {
        appendEqualRows(0, head);
        rows.push({
          type: "fold",
          left: null,
          right: null,
          count: hidden,
          left_start: op.i1 + head + 1,
          left_end: op.i1 + head + hidden,
          right_start: op.j1 + head + 1,
          right_end: op.j1 + head + hidden,
        });
        appendEqualRows(head + hidden, count);
      }
    } else if (op.tag === "eol" || op.tag === "fixed_eol" || op.tag === "fixed_space") {
      for (let offset = 0; offset < op.i2 - op.i1; offset += 1) {
        if (op.tag === "eol") stats.eol_only += 1;
        rows.push({
          type: op.tag,
          left: side(baseLines[op.i1 + offset], op.i1 + offset + 1),
          right: side(sourceLines[op.j1 + offset], op.j1 + offset + 1),
        });
      }
    } else if (op.tag === "replace") {
      const leftCount = op.i2 - op.i1;
      const rightCount = op.j2 - op.j1;
      stats.removed += leftCount;
      stats.added += rightCount;
      stats.changed += Math.max(leftCount, rightCount);

      const pairedCount = Math.min(leftCount, rightCount);
      const appendChangedPairs = (start, end) => {
        for (let offset = start; offset < end; offset += 1) {
          rows.push({ type: "delete", left: side(baseLines[op.i1 + offset], op.i1 + offset + 1), right: null });
        }
        for (let offset = start; offset < end; offset += 1) {
          rows.push({ type: "insert", left: null, right: side(sourceLines[op.j1 + offset], op.j1 + offset + 1) });
        }
      };

      let changedStart = 0;
      for (let offset = 0; offset < pairedCount; offset += 1) {
        const left = baseLines[op.i1 + offset];
        const right = sourceLines[op.j1 + offset];
        if (!isSpaceOnlyContentChange(left.content, right.content)) {
          continue;
        }
        appendChangedPairs(changedStart, offset);
        // Keep the established row type so older UI bundles render this as a yellow changed row.
        rows.push({ type: "replace", left: side(left, op.i1 + offset + 1), right: side(right, op.j1 + offset + 1) });
        stats.space_only += 1;
        changedStart = offset + 1;
      }
      appendChangedPairs(changedStart, pairedCount);
      for (let offset = pairedCount; offset < leftCount; offset += 1) {
        rows.push({ type: "delete", left: side(baseLines[op.i1 + offset], op.i1 + offset + 1), right: null });
      }
      for (let offset = pairedCount; offset < rightCount; offset += 1) {
        rows.push({ type: "insert", left: null, right: side(sourceLines[op.j1 + offset], op.j1 + offset + 1) });
      }
    } else if (op.tag === "delete") {
      stats.removed += op.i2 - op.i1;
      for (let i = op.i1; i < op.i2; i += 1) {
        rows.push({ type: "delete", left: side(baseLines[i], i + 1), right: null });
      }
    } else if (op.tag === "insert") {
      stats.added += op.j2 - op.j1;
      for (let j = op.j1; j < op.j2; j += 1) {
        rows.push({ type: "insert", left: null, right: side(sourceLines[j], j + 1) });
      }
    }
  }
  return { rows, stats };
}

function displayOpcodes(baseLines, sourceLines, fixedEolLines = new Set(), fixedSpaceOnlyLines = new Set()) {
  const result = [];
  for (const op of opcodes(baseLines, sourceLines)) {
    if (op.tag !== "equal") {
      result.push(op);
      continue;
    }
    let offset = 0;
    while (offset < op.i2 - op.i1) {
      const currentTag = eolDisplayTag(
        baseLines[op.i1 + offset],
        sourceLines[op.j1 + offset],
        op.j1 + offset + 1,
        fixedEolLines,
        fixedSpaceOnlyLines
      );
      const start = offset;
      offset += 1;
      while (
        offset < op.i2 - op.i1 &&
        eolDisplayTag(
          baseLines[op.i1 + offset],
          sourceLines[op.j1 + offset],
          op.j1 + offset + 1,
          fixedEolLines,
          fixedSpaceOnlyLines
        ) === currentTag
      ) {
        offset += 1;
      }
      result.push({
        tag: currentTag,
        i1: op.i1 + start,
        i2: op.i1 + offset,
        j1: op.j1 + start,
        j2: op.j1 + offset,
      });
    }
  }
  return result;
}

function eolDisplayTag(left, right, rightLineNo, fixedEolLines, fixedSpaceOnlyLines = new Set()) {
  if (fixedSpaceOnlyLines.has(rightLineNo)) return "fixed_space";
  if (fixedEolLines.has(rightLineNo)) return "fixed_eol";
  if (left.eol !== right.eol) return "eol";
  return "equal";
}

function hiddenRange(input = {}) {
  const leftStart = Number(input.leftStart ?? input.left_start);
  const leftEnd = Number(input.leftEnd ?? input.left_end);
  const rightStart = Number(input.rightStart ?? input.right_start);
  const rightEnd = Number(input.rightEnd ?? input.right_end);
  const values = [leftStart, leftEnd, rightStart, rightEnd];
  if (values.every((value) => Number.isNaN(value))) {
    return null;
  }
  if (!values.every((value) => Number.isInteger(value) && value >= 1)) {
    throw new Error("Hidden diff range is invalid");
  }
  if (leftEnd < leftStart || rightEnd < rightStart || leftEnd - leftStart !== rightEnd - rightStart) {
    throw new Error("Hidden diff range is inconsistent");
  }
  return { leftStart, leftEnd, rightStart, rightEnd };
}

function equalRangeRows(baseLines, sourceLines, range, fixedEolLines = new Set(), fixedSpaceOnlyLines = new Set()) {
  const rows = [];
  const count = range.leftEnd - range.leftStart + 1;
  for (let offset = 0; offset < count; offset += 1) {
    const leftIndex = range.leftStart - 1 + offset;
    const rightIndex = range.rightStart - 1 + offset;
    const left = baseLines[leftIndex];
    const right = sourceLines[rightIndex];
    if (!left || !right) {
      throw new Error("Hidden diff range is outside file bounds");
    }
    rows.push({
      type: eolDisplayTag(left, right, rightIndex + 1, fixedEolLines, fixedSpaceOnlyLines),
      left: side(left, leftIndex + 1),
      right: side(right, rightIndex + 1),
    });
  }
  return rows;
}

function side(line, lineno) {
  return {
    lineno,
    text: line.content.toString("utf8"),
    eol: eolName(line.eol),
  };
}

function eolName(eol) {
  if (eol === "\n") return "lf";
  if (eol === "\r\n") return "crlf";
  if (eol === "\r") return "cr";
  return "none";
}

function positiveInt(value, fallback, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  const rounded = Math.floor(parsed);
  return Math.min(Math.max(rounded, min), max);
}

function parseBoolean(value, fallback = false) {
  if (typeof value === "boolean") return value;
  if (value === undefined || value === null || value === "") return fallback;
  return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase());
}

function fixWorkingTree(input = {}) {
  const {
    sessionId,
    files,
    fixSpaceOnly = Boolean(input.fix_space_only),
    resetExisting = Boolean(input.resetExisting ?? input.reset_existing),
  } = input;
  const value = session(sessionId);
  const fileMap = new Map(value.files.map((item) => [item.path, item]));
  const fixedFiles = [];
  const skippedFiles = [];
  const failedFiles = [];
  const fixedBlobs = resetExisting
    ? new Map()
    : new Map(value.fixed_blobs instanceof Map ? value.fixed_blobs : []);
  const existingFixedFiles = resetExisting
    ? new Map()
    : new Map((value.fixed_files || []).map((item) => [item.path, item]));
  for (const filePath of files || []) {
    const entry = fileMap.get(filePath);
    if (!entry) {
      skippedFiles.push({ path: filePath, reason: "File was not in the preview" });
      continue;
    }
    if (!entry.processable) {
      skippedFiles.push({ path: filePath, reason: entry.reason || "File is not processable" });
      continue;
    }
    try {
      if (!entry.eol_only_lines && !entry.space_only_lines) {
        skippedFiles.push({ path: filePath, reason: "File has no EOL-only or space-only changes" });
        continue;
      }
      if (!entry.eol_only_lines && !fixSpaceOnly) {
        skippedFiles.push({ path: filePath, reason: "Enable the space-only option to fix this file" });
        continue;
      }
      const fixed = fixFile(value, entry, { fixSpaceOnly });
      fixedFiles.push(fixed.result);
      existingFixedFiles.set(entry.path, fixed.result);
      fixedBlobs.delete(entry.path);
      if (fixed.blobBytes) {
        fixedBlobs.set(entry.path, fixed.blobBytes);
      }
    } catch (error) {
      failedFiles.push({ path: filePath, error: error.message });
    }
  }
  value.fixed_files = Array.from(existingFixedFiles.values());
  value.fixed_blobs = fixedBlobs;
  return {
    session_id: sessionId,
    fixed_files: fixedFiles,
    skipped_files: skippedFiles,
    failed_files: failedFiles,
    total_restored_eol_lines: fixedFiles.reduce((sum, item) => sum + item.restored_eol_lines, 0),
    total_restored_space_only_lines: fixedFiles.reduce(
      (sum, item) => sum + (item.restored_space_only_lines || 0),
      0
    ),
  };
}

function fixFile(value, entry, { fixSpaceOnly = false } = {}) {
  const repoPath = value.repoPath;
  const isBranch = value.mode === "branch";
  const worktreePath = value.worktreePath || repoPath;
  const baseRef = value.base_ref || "HEAD";
  const oldPath = entry.old_path || entry.path;
  const baseBytes = isBranch
    ? gitObject(worktreePath, baseRef, oldPath)
    : gitObjectForWorktree(repoPath, "HEAD", oldPath);
  const baseBlobBytes = isBranch
    ? baseBytes
    : gitObject(repoPath, "HEAD", oldPath);
  const sourceBytes = isBranch
    ? gitObject(worktreePath, "HEAD", entry.path)
    : worktreeBytes(repoPath, entry.path);
  if (isBinary(baseBytes) || isBinary(baseBlobBytes) || isBinary(sourceBytes)) {
    throw new Error("Binary file");
  }
  const baseLines = splitLines(baseBytes);
  const sourceLines = splitLines(sourceBytes);
  const restoredLines = restoreComparableLineEols(baseLines, sourceLines, { fixSpaceOnly });
  const fixedEolLines = restoredLines.fixedEolLines;
  const fixedSpaceOnlyLines = restoredLines.fixedSpaceOnlyLines;
  const restored = fixedEolLines.length;
  const restoredSpaceOnly = fixedSpaceOnlyLines.length;
  const nextWorktreeBytes = joinLines(sourceLines);
  const worktreeChanged = !sourceBytes.equals(nextWorktreeBytes);
  if (worktreeChanged) {
    fs.writeFileSync(safeFile(worktreePath, entry.path), nextWorktreeBytes);
  }

  if (isBranch) {
    const remaining = diffStats(baseBytes, nextWorktreeBytes);
    let message = null;
    if (!worktreeChanged && (restored > 0 || restoredSpaceOnly > 0)) {
      message = "Selected changes were already aligned with the source blob";
    } else if (restored === 0 && restoredSpaceOnly === 0) {
      message = "No EOL changes were needed";
    }
    return {
      result: {
        path: entry.path,
        restored_eol_lines: restored,
        fixed_eol_lines: fixedEolLines,
        restored_space_only_lines: restoredSpaceOnly,
        fixed_space_only_lines: fixedSpaceOnlyLines,
        remaining_changed_lines: remaining.changed_lines,
        remaining_eol_only_lines: remaining.eol_only_lines,
        remaining_space_only_lines: remaining.space_only_lines,
        worktree_changed: worktreeChanged,
        committable: worktreeChanged,
        message,
      },
      blobBytes: null,
    };
  }

  const baseBlobLines = splitLines(baseBlobBytes);
  const blobLines = splitLines(nextWorktreeBytes);
  restoreComparableLineEols(baseBlobLines, blobLines, { fixSpaceOnly });
  const nextBlobBytes = joinLines(blobLines);
  const remaining = diffStats(baseBytes, nextWorktreeBytes);
  const blobRemaining = diffStats(baseBlobBytes, nextBlobBytes);
  const committable = blobRemaining.changed_lines > 0;
  let message = null;
  if (!committable && (restored > 0 || restoredSpaceOnly > 0)) {
    message = "Only selected EOL or whitespace changes were applied to the working tree file";
  } else if (restored === 0 && restoredSpaceOnly === 0) {
    message = committable ? "Content changes are ready without EOL rewrite" : "No EOL changes were needed";
  } else {
    message = "Applied EOL fix to the working tree file";
  }
  return {
    result: {
      path: entry.path,
      restored_eol_lines: restored,
      fixed_eol_lines: fixedEolLines,
      restored_space_only_lines: restoredSpaceOnly,
      fixed_space_only_lines: fixedSpaceOnlyLines,
      remaining_changed_lines: remaining.changed_lines,
      remaining_eol_only_lines: remaining.eol_only_lines,
      remaining_space_only_lines: remaining.space_only_lines,
      worktree_changed: worktreeChanged,
      committable,
      message,
    },
    blobBytes: committable ? nextBlobBytes : null,
  };
}

function restoreComparableLineEols(baseLines, sourceLines, { fixSpaceOnly = false } = {}) {
  const fixedLines = [];
  const fixedSpaceOnlyLines = [];
  for (const op of opcodes(baseLines, sourceLines)) {
    if (op.tag === "equal") {
      for (let offset = 0; offset < op.i2 - op.i1; offset += 1) {
        const baseLine = baseLines[op.i1 + offset];
        const sourceLine = sourceLines[op.j1 + offset];
        if (!sourceLine || !baseLine) {
          continue;
        }
        if (sourceLine.eol !== baseLine.eol) {
          sourceLine.eol = baseLine.eol;
          fixedLines.push(op.j1 + offset + 1);
        }
      }
    } else if (fixSpaceOnly && op.tag === "replace") {
      for (let offset = 0; offset < Math.min(op.i2 - op.i1, op.j2 - op.j1); offset += 1) {
        const baseLine = baseLines[op.i1 + offset];
        const sourceLine = sourceLines[op.j1 + offset];
        if (!baseLine || !sourceLine || !isSpaceOnlyContentChange(baseLine.content, sourceLine.content)) {
          continue;
        }
        sourceLine.content = baseLine.content;
        sourceLine.eol = baseLine.eol;
        fixedSpaceOnlyLines.push(op.j1 + offset + 1);
      }
    }
  }
  return { fixedEolLines: fixedLines, fixedSpaceOnlyLines };
}

function nearbyBaseEol(lines, index) {
  for (let i = index - 1; i >= 0; i -= 1) {
    if (lines[i] && lines[i].eol) {
      return lines[i].eol;
    }
  }
  for (let i = index; i < lines.length; i += 1) {
    if (lines[i] && lines[i].eol) {
      return lines[i].eol;
    }
  }
  return "";
}

function dominantEol(lines) {
  const counts = new Map();
  for (const line of lines) {
    if (!line.eol) {
      continue;
    }
    counts.set(line.eol, (counts.get(line.eol) || 0) + 1);
  }
  let winner = "";
  let winnerCount = 0;
  for (const [eol, count] of counts) {
    if (count > winnerCount) {
      winner = eol;
      winnerCount = count;
    }
  }
  return winner;
}

function commitWorkingTree({ sessionId, message }) {
  const value = session(sessionId);
  if (value.mode === "branch") {
    return commitBranchRepository(value, sessionId, message);
  }
  const fixedBlobs = value.fixed_blobs instanceof Map ? value.fixed_blobs : new Map();
  const files = (value.fixed_files || []).map((item) => item.path).filter((filePath) => fixedBlobs.has(filePath));
  if (!files.length) {
    return { session_id: sessionId, committed: false, commit_sha: null, message: "No committable content changes after ignoring EOL-only differences", changed_files: [] };
  }
  const branch = gitText(value.repoPath, ["branch", "--show-current"]).trim();
  if (!branch) {
    throw new Error("Current repo is detached; cannot commit without a branch");
  }
  const parent = gitText(value.repoPath, ["rev-parse", "HEAD"]).trim();
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "contrack-git-index-"));
  const tempEnv = { GIT_INDEX_FILE: path.join(tempDir, "index") };
  const stagedBlobs = new Map();
  const commitMessage = message && message.trim() ? message.trim() : "fix eol";
  try {
    git(value.repoPath, ["read-tree", "HEAD"], { env: tempEnv });
    for (const filePath of files) {
      const mode = trackedFileMode(value.repoPath, filePath, tempEnv);
      const blob = writeBlob(value.repoPath, fixedBlobs.get(filePath));
      updateIndexBlob(value.repoPath, filePath, mode, blob, tempEnv);
      stagedBlobs.set(filePath, { mode, blob });
    }
    const tree = gitText(value.repoPath, ["write-tree"], { env: tempEnv }).trim();
    const changed = git(value.repoPath, ["diff", "--name-only", "-z", "HEAD", tree, "--", ...files])
      .toString("utf8")
      .split("\0")
      .filter(Boolean);
    if (!changed.length) {
      return { session_id: sessionId, committed: false, commit_sha: null, message: "No committable EOL changes after staging", changed_files: [] };
    }
    const commitSha = gitText(value.repoPath, ["commit-tree", tree, "-p", parent, "-m", commitMessage]).trim();
    git(value.repoPath, ["update-ref", `refs/heads/${branch}`, commitSha, parent]);
    for (const filePath of changed) {
      const staged = stagedBlobs.get(filePath);
      if (staged) {
        updateIndexBlob(value.repoPath, filePath, staged.mode, staged.blob);
      }
    }
    value.commit_sha = commitSha;
    return { session_id: sessionId, committed: true, commit_sha: commitSha, message: commitMessage, changed_files: changed };
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

function commitBranchRepository(value, sessionId, message) {
  const repoPath = value.repoPath;
  const files = (value.fixed_files || []).map((item) => item.path).filter(Boolean);
  if (!files.length) {
    return { session_id: sessionId, committed: false, commit_sha: null, message: "No fixed files to commit", changed_files: [] };
  }
  if (!repoPath || !fs.existsSync(repoPath)) {
    throw new Error("Local clone folder is no longer available");
  }

  for (const filePath of files) {
    stageExactFile(repoPath, filePath);
  }
  const changed = git(repoPath, ["diff", "--cached", "--name-only", "-z", "--", ...files])
    .toString("utf8")
    .split("\0")
    .filter(Boolean);
  if (!changed.length) {
    return { session_id: sessionId, committed: false, commit_sha: null, message: "No committable EOL changes after staging", changed_files: [] };
  }

  const commitMessage = message && message.trim() ? message.trim() : "fix eol";
  git(repoPath, ["commit", "-m", commitMessage]);
  const commitSha = gitText(repoPath, ["rev-parse", "HEAD"]).trim();
  value.commit_sha = commitSha;
  value.committed_files = changed;
  return { session_id: sessionId, committed: true, commit_sha: commitSha, message: commitMessage, changed_files: changed };
}

function trackedFileMode(repoPath, filePath, env) {
  const modeOutput = gitText(repoPath, ["ls-files", "-s", "--", filePath], { env }).trim();
  return modeOutput ? modeOutput.split(/\s+/, 1)[0] : "100644";
}

function writeBlob(repoPath, blobBytes) {
  return git(repoPath, ["hash-object", "-w", "--stdin"], { input: blobBytes }).toString("utf8").trim();
}

function updateIndexBlob(repoPath, filePath, mode, blob, env) {
  git(repoPath, ["update-index", "--add", "--cacheinfo", `${mode},${blob},${filePath}`], { env });
}

function stageExactFile(repoPath, filePath) {
  const absolute = safeFile(repoPath, filePath);
  if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) {
    throw new Error(`Fixed file no longer exists: ${filePath}`);
  }
  const mode = trackedFileMode(repoPath, filePath);
  const blob = gitText(repoPath, ["hash-object", "-w", "--no-filters", "--", filePath]).trim();
  updateIndexBlob(repoPath, filePath, mode, blob);
}

function pushWorkingTree({ sessionId, githubToken }) {
  const value = session(sessionId);
  if (!value.commit_sha) {
    throw new Error("Commit is required before push");
  }
  if (value.mode === "branch") {
    const repoPath = value.repoPath;
    const branch = value.source_branch;
    if (!repoPath || !branch) {
      throw new Error("Local clone folder is no longer available");
    }
    git(repoPath, ["push", "origin", `HEAD:refs/heads/${branch}`], { token: githubToken });
    return { session_id: sessionId, pushed: true, source_branch: branch, message: `Pushed ${branch}` };
  }
  const branch = gitText(value.repoPath, ["branch", "--show-current"]).trim();
  if (!branch) {
    throw new Error("Current repo is detached; cannot push without a branch");
  }
  git(value.repoPath, ["push", "origin", `HEAD:refs/heads/${branch}`], { token: githubToken });
  return { session_id: sessionId, pushed: true, source_branch: branch, message: `Pushed ${branch}` };
}

module.exports = {
  commitWorkingTree,
  fixWorkingTree,
  getWorkingTreePreviewJob,
  previewWorkingTree,
  pushWorkingTree,
  startBranchPreview,
  startWorkingTreePreview,
  structuredDiff,
};
