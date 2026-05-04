const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { getBuildToolDir } = require("./settings.cjs");

const LOG_STORAGE_LIMIT = 1000;
const LOG_RESPONSE_LIMIT = 300;

const jobs = new Map();

function startBuildJob(input) {
  const jobId = crypto.randomBytes(16).toString("hex");
  const job = {
    job_id: jobId,
    status: "queued",
    error: null,
    logs: [],
    log_seq: 0,
    artifacts: [],
    created_at: Date.now() / 1000,
    updated_at: Date.now() / 1000,
  };
  jobs.set(jobId, job);
  setImmediate(() => runBuild(job, input).catch((error) => fail(job, error)));
  return snapshot(job);
}

function getBuildJob(jobId) {
  const job = jobs.get(jobId);
  if (!job) {
    return null;
  }
  return snapshot(job);
}

function snapshot(job) {
  return {
    job_id: job.job_id,
    status: job.status,
    error: job.error,
    logs: job.logs.slice(-LOG_RESPONSE_LIMIT),
    total_logs: job.log_seq,
    artifacts: job.artifacts,
    created_at: job.created_at,
    updated_at: job.updated_at,
  };
}

function log(job, level, source, message) {
  job.log_seq += 1;
  job.logs.push({ seq: job.log_seq, ts: Date.now() / 1000, level, source, message });
  if (job.logs.length > LOG_STORAGE_LIMIT) {
    job.logs.splice(0, job.logs.length - LOG_STORAGE_LIMIT);
  }
  job.updated_at = Date.now() / 1000;
}

function fail(job, error) {
  job.status = "failed";
  job.error = error && error.message ? error.message : String(error);
  log(job, "error", "system", job.error);
}

async function runBuild(job, input) {
  job.status = "running";
  const targetBranch = cleanBranch(input.targetBranch);
  const sourceFolder = path.resolve(String(input.sourceFolder || ""));
  const buildFolder = path.resolve(String(input.buildFolder || ""));
  const repo = normalizeRepo(input.repo);
  const buildClient = Boolean(input.buildClient);
  const buildServer = Boolean(input.buildServer);
  if (!buildClient && !buildServer) {
    throw new Error("Select Client, Server, or both before build");
  }
  log(job, "info", "system", `Build started for branch ${targetBranch}`);
  log(job, "info", "system", `Source folder: ${sourceFolder}`);
  log(job, "info", "system", `Build folder: ${buildFolder}`);
  fs.mkdirSync(buildFolder, { recursive: true });

  await ensureSource(job, sourceFolder, repo, input.githubToken);
  await prepareBranch(job, sourceFolder, targetBranch, input.githubToken);
  await restoreNugetIfNeeded(job, sourceFolder);

  if (buildClient) {
    const artifact = await buildClientArtifact(job, sourceFolder, buildFolder, targetBranch);
    job.artifacts.push(artifact);
  }
  if (buildServer) {
    const artifact = await buildServerArtifact(job, sourceFolder, buildFolder, targetBranch);
    job.artifacts.push(artifact);
  }
  job.status = "succeeded";
  log(job, "info", "system", `Build completed with ${job.artifacts.length} artifact(s)`);
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

async function compressArchive(job, sourcePattern, destination) {
  if (!sourcePattern || !destination) {
    throw new Error(`Invalid zip paths. Source: ${sourcePattern || "(empty)"}, destination: ${destination || "(empty)"}`);
  }
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  const script = [
    "$ErrorActionPreference = 'Stop'",
    "$ProgressPreference = 'SilentlyContinue'",
    "$sourcePath = $env:CONTRACK_ARCHIVE_SOURCE",
    "$destinationPath = $env:CONTRACK_ARCHIVE_DESTINATION",
    "if ([string]::IsNullOrWhiteSpace($sourcePath)) { throw 'Archive source path is empty' }",
    "if ([string]::IsNullOrWhiteSpace($destinationPath)) { throw 'Archive destination path is empty' }",
    "Compress-Archive -Path $sourcePath -DestinationPath $destinationPath -Force",
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
    const source = options.source || path.basename(command);
    if (!options.quiet) {
      log(job, "info", source, `$ ${command} ${args.join(" ")}`);
    }
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env || process.env,
      windowsVerbatimArguments: Boolean(options.windowsVerbatimArguments),
      windowsHide: true,
    });
    let stdout = "";
    let tail = [];

    const handleChunk = (chunk) => {
      const text = chunk.toString();
      stdout += text;
      for (const raw of text.split(/\r?\n/)) {
        const line = raw.trimEnd();
        if (!line) continue;
        const redacted = line.replace(/x-access-token:[A-Za-z0-9_\-]+/g, "x-access-token:***");
        tail.push(redacted);
        if (tail.length > 20) tail.shift();
        if (!options.quiet) {
          log(job, "info", source, redacted);
        }
      }
    };
    child.stdout.on("data", handleChunk);
    child.stderr.on("data", handleChunk);
    child.on("error", reject);
    child.on("close", (code) => {
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
  getBuildJob,
  startBuildJob,
};
