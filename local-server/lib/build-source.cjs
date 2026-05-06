const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const { getBuildToolDir } = require("./settings.cjs");

const LOG_STORAGE_LIMIT = 1000;
const LOG_RESPONSE_LIMIT = 300;

const jobs = new Map();
let zipQueue = Promise.resolve();
let zipQueueDepth = 0;

function startBuildJob(input) {
  const jobId = crypto.randomBytes(16).toString("hex");
  const buildClient = Boolean(input && input.buildClient);
  const buildServer = Boolean(input && input.buildServer);
  const job = {
    job_id: jobId,
    status: "queued",
    error: null,
    logs: [],
    log_seq: 0,
    artifacts: [],
    cancel_requested: false,
    children: new Set(),
    target_jobs: {
      ...(buildClient ? { client: createTargetJob(jobId, "client") } : {}),
      ...(buildServer ? { server: createTargetJob(jobId, "server") } : {}),
    },
    created_at: Date.now() / 1000,
    updated_at: Date.now() / 1000,
  };
  jobs.set(jobId, job);
  setImmediate(() => runBuild(job, input).catch((error) => fail(job, error)));
  return snapshot(job);
}

function createTargetJob(parentJobId, target) {
  const now = Date.now() / 1000;
  return {
    job_id: `${parentJobId}:${target}`,
    target,
    status: "queued",
    error: null,
    logs: [],
    log_seq: 0,
    artifacts: [],
    cancel_requested: false,
    children: new Set(),
    created_at: now,
    updated_at: now,
  };
}

function getBuildJob(jobId) {
  const resolved = resolveBuildJob(jobId);
  if (!resolved) {
    return null;
  }
  return snapshot(resolved.job);
}

function cancelBuildJob(jobId) {
  const resolved = resolveBuildJob(jobId);
  if (!resolved) {
    return null;
  }

  requestCancel(resolved.job);
  if (resolved.job === resolved.parent) {
    for (const targetJob of Object.values(resolved.parent.target_jobs || {})) {
      requestCancel(targetJob);
    }
  } else if (allTargetsCancelRequested(resolved.parent)) {
    requestCancel(resolved.parent);
  }
  syncParentStatus(resolved.parent);
  return snapshot(resolved.job);
}

function resolveBuildJob(jobId) {
  const id = String(jobId || "");
  const parentId = id.includes(":") ? id.split(":", 1)[0] : id;
  const parent = jobs.get(parentId);
  if (!parent) {
    return null;
  }
  if (id === parentId) {
    return { parent, job: parent };
  }
  const target = id.slice(parentId.length + 1);
  const targetJob = parent.target_jobs && parent.target_jobs[target];
  return targetJob ? { parent, job: targetJob } : null;
}

function snapshot(job) {
  return {
    job_id: job.job_id,
    target: job.target,
    status: job.status,
    error: job.error,
    logs: job.logs.slice(-LOG_RESPONSE_LIMIT),
    total_logs: job.log_seq,
    artifacts: job.artifacts,
    cancel_requested: Boolean(job.cancel_requested),
    target_jobs: snapshotTargets(job.target_jobs),
    created_at: job.created_at,
    updated_at: job.updated_at,
  };
}

function snapshotTargets(targetJobs) {
  if (!targetJobs) {
    return undefined;
  }
  return Object.fromEntries(Object.entries(targetJobs).map(([target, targetJob]) => [target, snapshot(targetJob)]));
}

function log(job, level, source, message) {
  if (job.broadcast_targets && job.target_jobs) {
    for (const targetJob of Object.values(job.target_jobs)) {
      log(targetJob, level, source, message);
    }
  }
  job.log_seq += 1;
  job.logs.push({ seq: job.log_seq, ts: Date.now() / 1000, level, source, message });
  if (job.logs.length > LOG_STORAGE_LIMIT) {
    job.logs.splice(0, job.logs.length - LOG_STORAGE_LIMIT);
  }
  job.updated_at = Date.now() / 1000;
}

function fail(job, error) {
  if (isCanceledError(error) || job.cancel_requested) {
    markCanceled(job);
    return;
  }
  job.broadcast_targets = false;
  job.status = "failed";
  job.error = error && error.message ? error.message : String(error);
  log(job, "error", "system", job.error);
  for (const targetJob of Object.values(job.target_jobs || {})) {
    if (!isTerminal(targetJob.status)) {
      fail(targetJob, error);
    }
  }
  job.updated_at = Date.now() / 1000;
}

function isTerminal(status) {
  return status === "succeeded" || status === "failed" || status === "canceled";
}

function markRunning(job) {
  throwIfCanceled(job);
  job.status = "running";
  job.updated_at = Date.now() / 1000;
}

function markSucceeded(job, artifact) {
  throwIfCanceled(job);
  job.status = "succeeded";
  job.error = null;
  if (artifact) {
    job.artifacts.push(artifact);
  }
  job.updated_at = Date.now() / 1000;
}

function markCanceled(job) {
  job.broadcast_targets = false;
  job.cancel_requested = true;
  job.status = "canceled";
  job.error = "Stopped by user";
  job.updated_at = Date.now() / 1000;
}

function requestCancel(job) {
  if (!job || isTerminal(job.status)) {
    return;
  }
  job.cancel_requested = true;
  job.status = "canceled";
  job.error = "Stopped by user";
  log(job, "warn", "system", "Stop requested by user");
  killJobChildren(job);
}

function allTargetsCancelRequested(parentJob) {
  const targetJobs = Object.values(parentJob.target_jobs || {});
  return Boolean(targetJobs.length && targetJobs.every((targetJob) => targetJob.cancel_requested || targetJob.status === "canceled"));
}

function createCanceledError() {
  const error = new Error("Stopped by user");
  error.name = "CanceledError";
  return error;
}

function isCanceledError(error) {
  return Boolean(error && (error.name === "CanceledError" || error.code === "ERR_CANCELED"));
}

function throwIfCanceled(job) {
  if (job && job.cancel_requested) {
    throw createCanceledError();
  }
}

function trackChild(job, child) {
  if (!job.children) {
    job.children = new Set();
  }
  job.children.add(child);
}

function untrackChild(job, child) {
  job.children?.delete(child);
}

function killJobChildren(job) {
  for (const child of Array.from(job.children || [])) {
    terminateChild(child);
  }
}

function terminateChild(child) {
  if (!child || child.killed) {
    return;
  }
  if (process.platform === "win32" && child.pid) {
    spawnSync("taskkill.exe", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
    return;
  }
  child.kill("SIGTERM");
}

function syncParentStatus(job) {
  const targetJobs = Object.values(job.target_jobs || {});
  job.artifacts = targetJobs.flatMap((targetJob) => targetJob.artifacts || []);
  if (!targetJobs.length) {
    return;
  }
  if (targetJobs.some((targetJob) => targetJob.status === "queued" || targetJob.status === "running")) {
    job.status = "running";
  } else if (targetJobs.every((targetJob) => targetJob.status === "succeeded")) {
    job.status = "succeeded";
  } else if (targetJobs.every((targetJob) => targetJob.status === "canceled")) {
    markCanceled(job);
    return;
  } else if (targetJobs.every((targetJob) => targetJob.status === "failed")) {
    job.status = "failed";
  } else {
    job.status = "partial";
  }
  job.error = targetJobs
    .filter((targetJob) => (targetJob.status === "failed" || targetJob.status === "canceled") && targetJob.error)
    .map((targetJob) => `${targetJob.target}: ${targetJob.error}`)
    .join("\n") || null;
  job.updated_at = Date.now() / 1000;
}

async function runBuild(job, input) {
  markRunning(job);
  const targetBranch = cleanBranch(input.targetBranch);
  const sourceFolder = path.resolve(String(input.sourceFolder || ""));
  const buildFolder = path.resolve(String(input.buildFolder || ""));
  const repo = normalizeRepo(input.repo);
  const buildClient = Boolean(input.buildClient);
  const buildServer = Boolean(input.buildServer);
  if (!buildClient && !buildServer) {
    throw new Error("Select Client, Server, or both before build");
  }
  job.broadcast_targets = true;
  log(job, "info", "system", `Build started for branch ${targetBranch}`);
  log(job, "info", "system", `Source folder: ${sourceFolder}`);
  log(job, "info", "system", `Build folder: ${buildFolder}`);
  fs.mkdirSync(buildFolder, { recursive: true });

  throwIfCanceled(job);
  await ensureSource(job, sourceFolder, repo, input.githubToken);
  throwIfCanceled(job);
  await prepareBranch(job, sourceFolder, targetBranch, input.githubToken);
  throwIfCanceled(job);
  job.broadcast_targets = false;

  const targetTasks = [];
  if (buildClient) {
    targetTasks.push(
      runTargetBuild(job, "client", async (targetJob) => {
        await restoreNugetIfNeeded(targetJob, sourceFolder);
        return buildClientArtifact(targetJob, sourceFolder, buildFolder, targetBranch);
      })
    );
  }
  if (buildServer) {
    targetTasks.push(runTargetBuild(job, "server", (targetJob) => buildServerArtifact(targetJob, sourceFolder, buildFolder, targetBranch)));
  }

  await Promise.allSettled(targetTasks);
  syncParentStatus(job);
  log(job, job.status === "failed" ? "error" : job.status === "partial" || job.status === "canceled" ? "warn" : "info", "system", `Build finished with status ${job.status}`);
}

async function runTargetBuild(parentJob, target, buildFn) {
  const targetJob = parentJob.target_jobs[target];
  try {
    markRunning(targetJob);
    syncParentStatus(parentJob);
    log(targetJob, "info", "system", `${targetLabel(target)} build started`);
  } catch (error) {
    fail(targetJob, error);
    syncParentStatus(parentJob);
    return;
  }
  try {
    const artifact = await buildFn(targetJob);
    markSucceeded(targetJob, artifact);
    log(targetJob, "info", "system", `${targetLabel(target)} build completed`);
  } catch (error) {
    if (isCanceledError(error) || targetJob.cancel_requested) {
      markCanceled(targetJob);
      log(targetJob, "warn", "system", `${targetLabel(target)} build stopped`);
    } else {
      fail(targetJob, error);
    }
  } finally {
    syncParentStatus(parentJob);
  }
}

function targetLabel(target) {
  return target === "client" ? "Client" : target === "server" ? "Server" : target;
}

function cleanBranch(value) {
  const branch = String(value || "").trim();
  if (!branch || branch.startsWith("-")) {
    throw new Error("Target branch is required");
  }
  return branch;
}

function normalizeRepo(value) {
  const repo = String(value || "").trim();
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo)) {
    throw new Error("git_repo must use owner/repo format in system settings");
  }
  return repo;
}

function isEmptyDirectory(folder) {
  if (!fs.existsSync(folder)) {
    return true;
  }
  return fs.statSync(folder).isDirectory() && fs.readdirSync(folder).length === 0;
}

async function ensureSource(job, sourceFolder, repo, githubToken) {
  const repoUrl = `https://github.com/${repo}.git`;
  if (!fs.existsSync(sourceFolder) || isEmptyDirectory(sourceFolder)) {
    fs.mkdirSync(path.dirname(sourceFolder), { recursive: true });
    log(job, "info", "git", `Cloning ${repoUrl}`);
    await run(job, "git", ["clone", "--progress", "--", repoUrl, sourceFolder], {
      cwd: path.dirname(sourceFolder),
      env: gitEnv(githubToken),
      source: "git",
    });
    return;
  }
  if (!fs.existsSync(path.join(sourceFolder, ".git"))) {
    throw new Error(`Source folder exists but is not a git repo: ${sourceFolder}`);
  }
  log(job, "info", "git", "Using existing source folder");
}

async function prepareBranch(job, sourceFolder, targetBranch, githubToken) {
  await run(job, "git", ["check-ref-format", "--branch", targetBranch], { cwd: sourceFolder, source: "git" });
  log(job, "info", "git", "Saving local changes with git stash");
  const stashOutput = await run(job, "git", ["stash", "push", "-u", "-m", `contrack-build-${Date.now()}`], {
    cwd: sourceFolder,
    source: "git",
    env: gitEnv(githubToken),
    allowFailure: true,
    captureOutput: true,
  });
  const hasStash = !/No local changes to save/i.test(stashOutput);

  log(job, "info", "git", "Fetching origin");
  await run(job, "git", ["fetch", "--prune", "--progress", "origin"], {
    cwd: sourceFolder,
    source: "git",
    env: gitEnv(githubToken),
  });
  await run(job, "git", ["rev-parse", "--verify", "--quiet", `origin/${targetBranch}^{commit}`], {
    cwd: sourceFolder,
    source: "git",
  });
  log(job, "info", "git", `Checking out ${targetBranch}`);
  await run(job, "git", ["checkout", "--force", "-B", targetBranch, `origin/${targetBranch}`], {
    cwd: sourceFolder,
    source: "git",
  });
  await run(job, "git", ["pull", "--ff-only", "origin", targetBranch], {
    cwd: sourceFolder,
    source: "git",
    env: gitEnv(githubToken),
  });
  if (hasStash) {
    log(job, "info", "git", "Restoring stashed local changes");
    await run(job, "git", ["stash", "pop"], { cwd: sourceFolder, source: "git" });
  }
  await resetDocumentParserFromOrigin(job, sourceFolder, targetBranch);
  await verifyCurrentBranchBeforeBuild(job, sourceFolder, targetBranch);
}

async function verifyCurrentBranchBeforeBuild(job, sourceFolder, targetBranch) {
  log(job, "info", "git", `Checking branch before build: ${targetBranch}`);
  const currentBranch = (await run(job, "git", ["branch", "--show-current"], {
    cwd: sourceFolder,
    source: "git",
    quiet: true,
    captureOutput: true,
  })).trim();
  if (currentBranch !== targetBranch) {
    throw new Error(`Branch check failed before build. Expected ${targetBranch}, got ${currentBranch || "(detached HEAD)"}`);
  }
  const headCommit = (await run(job, "git", ["rev-parse", "HEAD"], {
    cwd: sourceFolder,
    source: "git",
    quiet: true,
    captureOutput: true,
  })).trim();
  const originCommit = (await run(job, "git", ["rev-parse", `origin/${targetBranch}^{commit}`], {
    cwd: sourceFolder,
    source: "git",
    quiet: true,
    captureOutput: true,
  })).trim();
  if (headCommit !== originCommit) {
    throw new Error(`Branch check failed before build. ${targetBranch} is not aligned with origin/${targetBranch}`);
  }
  log(job, "info", "git", `Branch check passed: ${targetBranch} (${headCommit.slice(0, 12)})`);
}

async function resetDocumentParserFromOrigin(job, sourceFolder, targetBranch) {
  const documentParserProject = "src/w-SCMS.DocumentParser/w-SCMS.DocumentParser.csproj";
  log(job, "info", "git", "Restoring DocumentParser project from origin before build patch");
  await run(job, "git", ["checkout", `origin/${targetBranch}`, "--", documentParserProject], {
    cwd: sourceFolder,
    source: "git",
  });
}

async function restoreNugetIfNeeded(job, sourceFolder) {
  const packageFolder = path.join(sourceFolder, "src", "CCM.ClientManage", "packages", "BouncyCastle.1.8.9");
  if (fs.existsSync(packageFolder)) {
    log(job, "info", "nuget", "NuGet packages already restored");
    return;
  }
  const toolDir = getBuildToolDir();
  const nuget = path.join(toolDir, "nuget.exe");
  if (!fs.existsSync(nuget)) {
    throw new Error(`nuget.exe not found: ${nuget}`);
  }
  const solution = findNugetSolutionFile(sourceFolder);
  log(job, "info", "nuget", `Restoring ${solution}`);
  await run(job, nuget, ["restore", solution], { cwd: toolDir, source: "nuget" });
  log(job, "info", "nuget", "Restoring CCM.ClientManage.csproj");
  await run(
    job,
    nuget,
    [
      "restore",
      path.join(sourceFolder, "src", "CCM.ClientManage", "CCM.ClientManage.csproj"),
      "-PackagesDirectory",
      path.join(sourceFolder, "src", "CCM.ClientManage", "packages"),
    ],
    { cwd: toolDir, source: "nuget" }
  );
}

async function buildClientArtifact(job, sourceFolder, buildFolder, targetBranch) {
  const toolDir = getBuildToolDir();
  const solution = findDevenvSolutionFile(sourceFolder);
  patchDocumentParser(job, sourceFolder);
  copyRequiredBuildFiles(job, sourceFolder, toolDir);
  const msbuild = findRequiredTool("MSBuild.exe", [
    process.env.MSBUILD_EXE,
    "C:\\Program Files (x86)\\Microsoft Visual Studio\\2019\\Professional\\MSBuild\\Current\\Bin\\MSBuild.exe",
    "C:\\Program Files\\Microsoft Visual Studio\\2022\\Professional\\MSBuild\\Current\\Bin\\MSBuild.exe",
    "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\MSBuild\\Current\\Bin\\MSBuild.exe",
    "C:\\Program Files\\Microsoft Visual Studio\\2022\\BuildTools\\MSBuild\\Current\\Bin\\MSBuild.exe",
  ]);
  const installerProject = "ConTrackClientInstaller-Obfucar-x64";
  const devenv = findRequiredTool("devenv.com", [
    process.env.DEVENV_EXE,
    "C:\\Program Files (x86)\\Microsoft Visual Studio\\2019\\Professional\\Common7\\IDE\\devenv.com",
    "C:\\Program Files\\Microsoft Visual Studio\\2022\\Professional\\Common7\\IDE\\devenv.com",
    "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\Common7\\IDE\\devenv.com",
  ]);

  log(job, "info", "build", "Building CCM.ClientManage");
  await run(job, msbuild, ["CCM.ClientManage.csproj", "/t:Clean", "/p:Configuration=Debug", "/p:Platform=x64"], {
    cwd: path.join(sourceFolder, "src", "CCM.ClientManage"),
    source: "msbuild",
  });
  await run(job, msbuild, ["CCM.ClientManage.csproj", "/t:ReBuild", "/p:Configuration=Debug", "/p:Platform=x64"], {
    cwd: path.join(sourceFolder, "src", "CCM.ClientManage"),
    source: "msbuild",
  });

  log(job, "info", "build", "Building w-SCMS client");
  await run(job, msbuild, ["w-SCMS.csproj", "/t:Clean", "/p:Configuration=Debug", "/p:Platform=x64"], {
    cwd: path.join(sourceFolder, "src", "w-SCMS"),
    source: "msbuild",
  });
  await run(job, msbuild, ["w-SCMS.csproj", "/t:ReBuild", "/p:Configuration=Debug", "/p:Platform=x64"], {
    cwd: path.join(sourceFolder, "src", "w-SCMS"),
    source: "msbuild",
  });

  log(job, "info", "build", "Building ConTrackClientInstaller-Obfucar-x64");
  log(job, "info", "build", `Using solution ${solution}`);
  log(job, "info", "build", `Using installer project ${installerProject}`);
  await runDevenv(job, devenv, solution, "/Clean", "ConTrackClientInstaller-Obfucar|x64", installerProject);
  await runDevenv(job, devenv, solution, "/Rebuild", "ConTrackClientInstaller-Obfucar|x64", installerProject);

  cleanupClientAuthFiles(job, sourceFolder);
  fs.copyFileSync(path.join(toolDir, "network.xml"), path.join(sourceFolder, "src", "w-SCMS", "bin", "x64", "Debug", "network.xml"));
  const zipPath = path.join(buildFolder, `ConTrack_Client_${safeVersion(targetBranch)}.zip`);
  log(job, "info", "zip", `Zipping client to ${zipPath}`);
  await compressArchive(job, path.join(sourceFolder, "src", "w-SCMS", "bin", "x64", "Debug", "*"), zipPath);
  return { type: "client", path: zipPath, file_name: path.basename(zipPath) };
}

async function buildServerArtifact(job, sourceFolder, buildFolder, targetBranch) {
  const packageBat = path.join(sourceFolder, "src-server", "packageObfuscate.bat");
  if (!fs.existsSync(packageBat)) {
    throw new Error(`Server build script not found: ${packageBat}`);
  }
  log(job, "info", "build", "Building ConTrack server");
  const serverDir = path.dirname(packageBat);
  await run(job, "cmd.exe", ["/d", "/s", "/c", "call packageObfuscate.bat < NUL"], {
    cwd: serverDir,
    source: "server",
  });
  const zipPath = path.join(buildFolder, `ConTrack_API_${safeVersion(targetBranch)}.zip`);
  log(job, "info", "zip", `Zipping server to ${zipPath}`);
  await compressArchive(job, path.join(sourceFolder, "src-server", "build", "*.war"), zipPath);
  return { type: "server", path: zipPath, file_name: path.basename(zipPath) };
}

function patchDocumentParser(job, sourceFolder) {
  const file = path.join(sourceFolder, "src", "w-SCMS.DocumentParser", "w-SCMS.DocumentParser.csproj");
  if (!fs.existsSync(file)) {
    log(job, "warn", "build", `DocumentParser project not found: ${file}`);
    return;
  }
  let content = fs.readFileSync(file, "utf8");
  if (!content.includes("<!--<PreBuildEvent>")) {
    content = content.replace(/<PreBuildEvent>/g, "<!--<PreBuildEvent>");
    content = content.replace(/<\/PreBuildEvent>/g, "</PreBuildEvent>-->");
    fs.writeFileSync(file, content, "utf8");
    log(job, "info", "build", "Removed DocumentParser pre-build event");
  }
}

function copyRequiredBuildFiles(job, sourceFolder, toolDir) {
  const copies = [
    [path.join(toolDir, "Interop.MLApp.dll"), path.join(sourceFolder, "src", "3rdParty", "MATLAB", "Interop.MLApp.dll")],
    [path.join(toolDir, "CCM.ClientManage.csproj"), path.join(sourceFolder, "src", "CCM.ClientManage", "CCM.ClientManage.csproj")],
  ];
  for (const [from, to] of copies) {
    if (!fs.existsSync(from)) {
      throw new Error(`Required build file not found: ${from}`);
    }
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(from, to);
    log(job, "info", "build", `Copied ${path.basename(from)}`);
  }
}

function cleanupClientAuthFiles(job, sourceFolder) {
  const debugDir = path.join(sourceFolder, "src", "w-SCMS", "bin", "x64", "Debug");
  const files = [
    "recent.xml",
    "session.xml",
    "repository_auth.xml",
    "repositoryGit_auth.xml",
    "repositoryGitlab_auth.xml",
    "repositoryBitbucket_auth.xml",
  ];
  for (const file of files) {
    const target = path.join(debugDir, file);
    if (fs.existsSync(target)) {
      fs.rmSync(target, { force: true });
      log(job, "info", "build", `Removed ${file}`);
    }
  }
}

function findRequiredTool(name, candidates) {
  const found = candidates.filter(Boolean).find((candidate) => fs.existsSync(candidate));
  if (!found) {
    throw new Error(`${name} not found. Set environment variable ${name === "MSBuild.exe" ? "MSBUILD_EXE" : "DEVENV_EXE"} or install Visual Studio build tools.`);
  }
  return found;
}

function findNugetSolutionFile(sourceFolder) {
  const candidates = [
    path.join(sourceFolder, "src", "w-SCMS.sln"),
    path.join(sourceFolder, "src", "w-SCMS", "w-SCMS.sln"),
  ];
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) {
    throw new Error(`w-SCMS.sln not found. Checked: ${candidates.join(", ")}`);
  }
  return found;
}

function findDevenvSolutionFile(sourceFolder) {
  const candidates = [
    path.join(sourceFolder, "src", "w-SCMS", "w-SCMS.sln"),
    path.join(sourceFolder, "src", "w-SCMS.sln"),
  ];
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) {
    throw new Error(`w-SCMS.sln not found. Checked: ${candidates.join(", ")}`);
  }
  return found;
}

async function runDevenv(job, devenv, solution, action, config, project) {
  const solutionDir = path.dirname(solution);
  return run(job, devenv, [quoteWindowsArg(path.basename(solution)), action, quoteWindowsArg(config), "/Project", quoteWindowsArg(project)], {
    cwd: solutionDir,
    source: "devenv",
    windowsVerbatimArguments: true,
  });
}

function quoteWindowsArg(value) {
  const text = String(value);
  if (/["\r\n]/.test(text)) {
    throw new Error(`Invalid command argument: ${text}`);
  }
  return `"${text}"`;
}

function commandLineForLog(command, args) {
  const safeArgs = [];
  for (let index = 0; index < args.length; index += 1) {
    const arg = String(args[index]);
    safeArgs.push(arg);
    if (arg.toLowerCase() === "-encodedcommand" && index + 1 < args.length) {
      safeArgs.push("<encoded-command>");
      index += 1;
    }
  }
  return `$ ${command} ${safeArgs.join(" ")}`;
}

async function compressArchive(job, sourcePattern, destination) {
  if (!sourcePattern || !destination) {
    throw new Error(`Invalid zip paths. Source: ${sourcePattern || "(empty)"}, destination: ${destination || "(empty)"}`);
  }
  const archiveRoot = archiveRootForPattern(sourcePattern);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  await runZipExclusive(job, () => streamZipArchive(job, sourcePattern, archiveRoot, destination));
}

async function runZipExclusive(job, work) {
  const previous = zipQueue;
  let releaseZipSlot = () => {};
  zipQueue = new Promise((resolve) => {
    releaseZipSlot = resolve;
  });
  if (zipQueueDepth > 0) {
    log(job, "info", "zip", "Waiting for other archive task to finish");
  }
  zipQueueDepth += 1;
  await previous.catch(() => {});
  try {
    return await work();
  } finally {
    zipQueueDepth -= 1;
    releaseZipSlot();
  }
}

function archiveRootForPattern(sourcePattern) {
  const text = String(sourcePattern);
  const wildcardIndex = text.search(/[*?\[]/);
  if (wildcardIndex === -1) {
    return fs.existsSync(text) && fs.statSync(text).isDirectory() ? text : path.dirname(text);
  }
  const beforeWildcard = text.slice(0, wildcardIndex);
  const separatorIndex = Math.max(beforeWildcard.lastIndexOf("\\"), beforeWildcard.lastIndexOf("/"));
  return separatorIndex >= 0 ? beforeWildcard.slice(0, separatorIndex) : process.cwd();
}

async function streamZipArchive(job, sourcePattern, archiveRoot, destination) {
  const script = [
    "$ErrorActionPreference = 'Stop'",
    "$ProgressPreference = 'SilentlyContinue'",
    "$sourcePath = $env:CONTRACK_ARCHIVE_SOURCE",
    "$archiveRoot = $env:CONTRACK_ARCHIVE_ROOT",
    "$destinationPath = $env:CONTRACK_ARCHIVE_DESTINATION",
    "if ([string]::IsNullOrWhiteSpace($sourcePath)) { throw 'Archive source path is empty' }",
    "if ([string]::IsNullOrWhiteSpace($archiveRoot)) { throw 'Archive root path is empty' }",
    "if ([string]::IsNullOrWhiteSpace($destinationPath)) { throw 'Archive destination path is empty' }",
    "Add-Type -AssemblyName System.IO.Compression",
    "Add-Type -AssemblyName System.IO.Compression.FileSystem",
    "$resolvedRoot = (Resolve-Path -LiteralPath $archiveRoot).Path.TrimEnd('\\') + '\\'",
    "$items = @(Get-ChildItem -Path $sourcePath -Force)",
    "if (-not $items.Count) { throw \"Archive source has no files: $sourcePath\" }",
    "$files = @()",
    "foreach ($item in $items) {",
    "  if ($item.PSIsContainer) { $files += Get-ChildItem -LiteralPath $item.FullName -Force -Recurse -File }",
    "  else { $files += $item }",
    "}",
    "if (-not $files.Count) { throw \"Archive source has no files: $sourcePath\" }",
    "if (Test-Path -LiteralPath $destinationPath) { Remove-Item -LiteralPath $destinationPath -Force }",
    "$rootUri = [Uri]::new($resolvedRoot)",
    "$archive = [System.IO.Compression.ZipFile]::Open($destinationPath, [System.IO.Compression.ZipArchiveMode]::Create)",
    "try {",
    "  foreach ($file in $files) {",
    "    $fileUri = [Uri]::new($file.FullName)",
    "    $entryName = [Uri]::UnescapeDataString($rootUri.MakeRelativeUri($fileUri).ToString())",
    "    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $entryName, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null",
    "  }",
    "}",
    "finally { $archive.Dispose() }",
    "Write-Output (\"Archived {0} file(s)\" -f $files.Count)",
  ].join("\r\n");
  await run(
    job,
    "powershell.exe",
    [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-EncodedCommand",
      Buffer.from(script, "utf16le").toString("base64"),
    ],
    {
      cwd: path.dirname(destination),
      source: "zip",
      env: {
        ...process.env,
        CONTRACK_ARCHIVE_SOURCE: sourcePattern,
        CONTRACK_ARCHIVE_ROOT: archiveRoot,
        CONTRACK_ARCHIVE_DESTINATION: destination,
      },
    }
  );
}

function safeVersion(value) {
  return String(value).replace(/[<>:"/\\|?*\x00-\x1F]/g, "_");
}

function gitEnv(token) {
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

function run(job, command, args, options = {}) {
  return new Promise((resolve, reject) => {
    if (job.cancel_requested) {
      reject(createCanceledError());
      return;
    }
    const source = options.source || path.basename(command);
    if (!options.quiet) {
      log(job, "info", source, commandLineForLog(command, args));
    }
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env || process.env,
      windowsVerbatimArguments: Boolean(options.windowsVerbatimArguments),
      windowsHide: true,
    });
    trackChild(job, child);
    if (job.cancel_requested) {
      terminateChild(child);
    }
    const captureOutput = Boolean(options.captureOutput || options.returnResult);
    let stdout = "";
    let tail = [];

    const handleChunk = (chunk) => {
      const text = chunk.toString();
      if (captureOutput) {
        stdout += text;
      }
      for (const raw of text.split(/\r?\n/)) {
        const line = raw.trimEnd();
        if (!line) continue;
        const redacted = line
          .replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, "")
          .replace(/x-access-token:[A-Za-z0-9_\-]+/g, "x-access-token:***");
        tail.push(redacted);
        if (tail.length > 20) tail.shift();
        if (!options.quiet) {
          log(job, "info", source, redacted);
        }
      }
    };
    child.stdout.on("data", handleChunk);
    child.stderr.on("data", handleChunk);
    child.on("error", (error) => {
      untrackChild(job, child);
      reject(job.cancel_requested ? createCanceledError() : error);
    });
    child.on("close", (code) => {
      untrackChild(job, child);
      if (job.cancel_requested) {
        reject(createCanceledError());
        return;
      }
      if (options.returnResult) {
        resolve({ code, stdout });
        return;
      }
      if (code === 0 || options.allowFailure) {
        resolve(stdout);
      } else {
        reject(new Error(tail.slice(-10).join("\n") || `${command} exited with code ${code}`));
      }
    });
  });
}

module.exports = {
  cancelBuildJob,
  getBuildJob,
  startBuildJob,
};
