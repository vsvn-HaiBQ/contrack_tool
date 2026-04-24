from __future__ import annotations

import base64
from dataclasses import dataclass
import difflib
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable
from uuid import uuid4

from app.core.config import settings
from app.core.security import decrypt_secret
from app.core.session_store import session_store
from app.models import User
from app.modules.git_eol.schemas import (
    GitEolFailedFile,
    GitEolFilePreview,
    GitEolFixedFile,
    GitEolFixResponse,
    GitEolPreviewResponse,
    GitEolSkippedFile,
)


Logger = Callable[[str, str, str], None]  # (level, source, message)


class GitEolError(Exception):
    pass


@dataclass
class RawLine:
    content: bytes
    eol: bytes


@dataclass
class DiffStats:
    base_eol: str
    source_eol: str
    changed_lines: int
    eol_only_lines: int


@dataclass
class ChangedFile:
    path: str
    old_path: str | None
    status: str


class GitEolService:
    def preview(
        self,
        *,
        repo: str,
        encrypted_token: str | None,
        user: User,
        base_branch: str,
        source_branch: str,
        log: Logger | None = None,
    ) -> GitEolPreviewResponse:
        emit = log or (lambda *_: None)
        token = self._resolve_token(encrypted_token)
        emit("info", "system", f"Preparing repo {repo} for user {user.username}")
        repo_root = self._ensure_user_repo(repo, user, token, log=emit)
        base_branch = self._normalize_branch(base_branch, "base_branch")
        source_branch = self._normalize_branch(source_branch, "source_branch")
        if source_branch.startswith("origin/") or source_branch.startswith("refs/"):
            raise GitEolError("source_branch must be a local branch name")

        emit("info", "system", f"Preparing worktree for source branch {source_branch}")
        worktree = self._prepare_user_worktree(repo_root, user, source_branch, log=emit)
        base_ref = self._resolve_base_ref(worktree, base_branch)
        emit("info", "system", f"Resolving merge-base of {base_ref} and HEAD")
        merge_base = self._git_text(worktree, ["merge-base", base_ref, "HEAD"]).strip()
        if not merge_base:
            raise GitEolError("Could not find merge-base")
        emit("info", "system", f"merge-base = {merge_base[:12]}")

        emit("info", "system", "Computing changed files")
        files = self._preview_files(worktree, merge_base)
        session_id = uuid4().hex
        self._save_session(
            session_id,
            {
                "user_id": user.id,
                "repo": repo,
                "repo_path": str(repo_root),
                "worktree_path": str(worktree),
                "base_branch": base_branch,
                "base_ref": base_ref,
                "source_branch": source_branch,
                "merge_base": merge_base,
                "files": [file.model_dump() for file in files],
                "fixed_files": [],
                "commit_sha": None,
            },
        )
        emit("info", "system", f"Preview ready: {len(files)} file(s) in diff, session {session_id}")
        return GitEolPreviewResponse(
            session_id=session_id,
            base_branch=base_branch,
            source_branch=source_branch,
            merge_base=merge_base,
            files=files,
        )

    def fix(self, *, user: User, session_id: str, selected_files: list[str]) -> GitEolFixResponse:
        session = self._load_session(session_id, user)
        worktree = Path(session["worktree_path"])
        merge_base = session["merge_base"]
        file_map = {file["path"]: file for file in session["files"]}
        fixed_files: list[GitEolFixedFile] = []
        skipped_files: list[GitEolSkippedFile] = []
        failed_files: list[GitEolFailedFile] = []

        for path in selected_files:
            file = file_map.get(path)
            if not file:
                skipped_files.append(GitEolSkippedFile(path=path, reason="File was not in the preview"))
                continue
            if not file.get("processable"):
                skipped_files.append(GitEolSkippedFile(path=path, reason=file.get("reason") or "File is not processable"))
                continue
            try:
                result = self._fix_file(worktree, merge_base, path, file.get("old_path") or path)
                fixed_files.append(result)
            except GitEolError as exc:
                failed_files.append(GitEolFailedFile(path=path, error=str(exc)))

        session["fixed_files"] = [file.model_dump() for file in fixed_files]
        self._save_session(session_id, session)
        return GitEolFixResponse(
            session_id=session_id,
            fixed_files=fixed_files,
            skipped_files=skipped_files,
            failed_files=failed_files,
            total_restored_eol_lines=sum(file.restored_eol_lines for file in fixed_files),
        )

    def commit(self, *, user: User, session_id: str, message: str | None) -> dict[str, Any]:
        session = self._load_session(session_id, user)
        worktree = Path(session["worktree_path"])
        files = [file["path"] for file in session.get("fixed_files", [])]
        if not files:
            return {
                "session_id": session_id,
                "committed": False,
                "commit_sha": None,
                "message": "No fixed files to commit",
                "changed_files": [],
            }

        for file in files:
            self._stage_exact_file(worktree, file)
        staged_files = self._staged_changed_files(worktree, files)
        if not staged_files:
            return {
                "session_id": session_id,
                "committed": False,
                "commit_sha": None,
                "message": "No committable EOL changes after staging",
                "changed_files": [],
            }

        commit_message = message.strip() if message and message.strip() else "Fix EOL noise"
        self._git(worktree, ["commit", "-m", commit_message])
        commit_sha = self._git_text(worktree, ["rev-parse", "HEAD"]).strip()
        session["commit_sha"] = commit_sha
        session["committed_files"] = staged_files
        self._save_session(session_id, session)
        return {
            "session_id": session_id,
            "committed": True,
            "commit_sha": commit_sha,
            "message": commit_message,
            "changed_files": staged_files,
        }

    def push(self, *, user: User, session_id: str, encrypted_token: str | None) -> dict[str, Any]:
        session = self._load_session(session_id, user)
        token = self._resolve_token(encrypted_token)
        worktree = Path(session["worktree_path"])
        source_branch = session["source_branch"]
        if not session.get("commit_sha"):
            raise GitEolError("Commit is required before push")
        self._git(worktree, ["push", "origin", f"HEAD:refs/heads/{source_branch}"], token=token)
        return {
            "session_id": session_id,
            "pushed": True,
            "source_branch": source_branch,
            "message": f"Pushed {source_branch}",
        }

    def _preview_files(self, worktree: Path, merge_base: str) -> list[GitEolFilePreview]:
        previews: list[GitEolFilePreview] = []
        for changed in self._changed_files(worktree, merge_base):
            if changed.status not in {"modified", "renamed"}:
                previews.append(
                    GitEolFilePreview(
                        path=changed.path,
                        old_path=changed.old_path,
                        status=changed.status,
                        selected=False,
                        processable=False,
                        reason=f"{changed.status}",
                    )
                )
                continue
            try:
                base_bytes = self._git_object(worktree, merge_base, changed.old_path or changed.path)
                source_bytes = self._git_object(worktree, "HEAD", changed.path)
                if self._is_binary(base_bytes) or self._is_binary(source_bytes):
                    previews.append(
                        GitEolFilePreview(
                            path=changed.path,
                            old_path=changed.old_path,
                            status=changed.status,
                            selected=False,
                            processable=False,
                            reason="Binary file",
                        )
                    )
                    continue
                stats = self._diff_stats(base_bytes, source_bytes)
                previews.append(
                    GitEolFilePreview(
                        path=changed.path,
                        old_path=changed.old_path,
                        status=changed.status,
                        selected=True,
                        processable=True,
                        base_eol=stats.base_eol,
                        source_eol=stats.source_eol,
                        changed_lines=stats.changed_lines,
                        eol_only_lines=stats.eol_only_lines,
                    )
                )
            except GitEolError as exc:
                previews.append(
                    GitEolFilePreview(
                        path=changed.path,
                        old_path=changed.old_path,
                        status=changed.status,
                        selected=False,
                        processable=False,
                        reason=str(exc),
                    )
                )
        return previews

    def _fix_file(self, worktree: Path, merge_base: str, path: str, old_path: str) -> GitEolFixedFile:
        base_bytes = self._git_object(worktree, merge_base, old_path)
        source_path = self._safe_worktree_file(worktree, path)
        source_bytes = self._git_object(worktree, "HEAD", path)
        if self._is_binary(base_bytes) or self._is_binary(source_bytes):
            raise GitEolError("Binary file")

        base_lines = self._split_lines(base_bytes)
        source_lines = self._split_lines(source_bytes)
        restored = self._restore_equal_line_eols(base_lines, source_lines)
        next_bytes = self._join_lines(source_lines)
        worktree_changed = next_bytes != source_bytes
        if worktree_changed:
            source_path.write_bytes(next_bytes)
        remaining = self._diff_stats(base_bytes, next_bytes)
        message = None
        if restored > 0 and not worktree_changed:
            message = "EOL was already aligned with the source blob"
        elif restored == 0:
            message = "No EOL changes were needed"
        return GitEolFixedFile(
            path=path,
            restored_eol_lines=restored,
            remaining_changed_lines=remaining.changed_lines,
            remaining_eol_only_lines=remaining.eol_only_lines,
            worktree_changed=worktree_changed,
            message=message,
        )

    def _restore_equal_line_eols(self, base_lines: list[RawLine], source_lines: list[RawLine]) -> int:
        matcher = difflib.SequenceMatcher(
            None,
            [line.content for line in base_lines],
            [line.content for line in source_lines],
            autojunk=False,
        )
        restored = 0
        for tag, base_start, base_end, source_start, _source_end in matcher.get_opcodes():
            if tag != "equal":
                continue
            for offset in range(base_end - base_start):
                base_line = base_lines[base_start + offset]
                source_line = source_lines[source_start + offset]
                if source_line.eol != base_line.eol:
                    source_line.eol = base_line.eol
                    restored += 1
        return restored

    def _diff_stats(self, base_bytes: bytes, source_bytes: bytes) -> DiffStats:
        base_lines = self._split_lines(base_bytes)
        source_lines = self._split_lines(source_bytes)
        matcher = difflib.SequenceMatcher(
            None,
            [line.content for line in base_lines],
            [line.content for line in source_lines],
            autojunk=False,
        )
        changed_lines = 0
        eol_only_lines = 0
        for tag, base_start, base_end, source_start, source_end in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(base_end - base_start):
                    if source_lines[source_start + offset].eol != base_lines[base_start + offset].eol:
                        eol_only_lines += 1
            else:
                changed_lines += max(base_end - base_start, source_end - source_start)
        return DiffStats(
            base_eol=self._eol_summary(base_lines),
            source_eol=self._eol_summary(source_lines),
            changed_lines=changed_lines,
            eol_only_lines=eol_only_lines,
        )

    def _split_lines(self, data: bytes) -> list[RawLine]:
        lines: list[RawLine] = []
        start = 0
        index = 0
        while index < len(data):
            byte = data[index : index + 1]
            if byte == b"\n":
                eol = b"\r\n" if index > start and data[index - 1 : index] == b"\r" else b"\n"
                content_end = index - 1 if eol == b"\r\n" else index
                lines.append(RawLine(data[start:content_end], eol))
                index += 1
                start = index
            elif byte == b"\r":
                if index + 1 < len(data) and data[index + 1 : index + 2] == b"\n":
                    index += 1
                    continue
                lines.append(RawLine(data[start:index], b"\r"))
                index += 1
                start = index
            else:
                index += 1
        if start < len(data):
            lines.append(RawLine(data[start:], b""))
        return lines

    def _join_lines(self, lines: list[RawLine]) -> bytes:
        return b"".join(line.content + line.eol for line in lines)

    def _eol_summary(self, lines: list[RawLine]) -> str:
        counts = {
            "lf": sum(1 for line in lines if line.eol == b"\n"),
            "crlf": sum(1 for line in lines if line.eol == b"\r\n"),
            "cr": sum(1 for line in lines if line.eol == b"\r"),
        }
        found = [name for name, count in counts.items() if count]
        if len(found) > 1:
            return "mixed"
        if found:
            return found[0]
        return "none"

    def _is_binary(self, data: bytes) -> bool:
        return b"\x00" in data

    def _changed_files(self, worktree: Path, merge_base: str) -> list[ChangedFile]:
        output = self._git_bytes(worktree, ["diff", "--name-status", "-z", "-M", merge_base, "HEAD", "--"])
        tokens = [token.decode("utf-8", errors="surrogateescape") for token in output.split(b"\x00") if token]
        files: list[ChangedFile] = []
        index = 0
        while index < len(tokens):
            status_token = tokens[index]
            index += 1
            status_code = status_token[0]
            if status_code in {"R", "C"}:
                if index + 1 >= len(tokens):
                    break
                old_path = tokens[index]
                path = tokens[index + 1]
                index += 2
            else:
                if index >= len(tokens):
                    break
                old_path = None
                path = tokens[index]
                index += 1
            files.append(ChangedFile(path=path, old_path=old_path, status=self._status_name(status_code)))
        return files

    def _status_name(self, status_code: str) -> str:
        return {
            "A": "added",
            "C": "copied",
            "D": "deleted",
            "M": "modified",
            "R": "renamed",
            "T": "type_changed",
            "U": "unmerged",
        }.get(status_code, status_code.lower())

    def _ensure_user_repo(self, repo: str, user: User, token: str, *, log: Logger | None = None) -> Path:
        emit = log or (lambda *_: None)
        repo = self._normalize_repo(repo)
        repo_root = self._repo_cache_path(repo, user)
        repo_url = f"https://github.com/{repo}.git"
        repo_root.parent.mkdir(parents=True, exist_ok=True)

        if not repo_root.exists():
            emit("info", "git", f"Cloning {repo_url} into {repo_root.name} (first-time pull)")
            self._git_streaming(repo_root.parent, ["clone", "--progress", "--", repo_url, str(repo_root)], token=token, log=emit)
        elif not self._is_git_worktree(repo_root):
            raise GitEolError(f"User git cache exists but is not a git repo: {repo_root}")
        else:
            emit("info", "git", f"Using cached repo at {repo_root.name}")

        self._git(repo_root, ["config", "user.name", user.username])
        self._git(repo_root, ["config", "user.email", f"{user.username}@contrack.local"])
        self._git(repo_root, ["config", "core.autocrlf", "false"])
        self._git(repo_root, ["config", "core.safecrlf", "false"])
        self._git(repo_root, ["remote", "set-url", "origin", repo_url])
        self._git(repo_root, ["checkout", "--detach", "--force"])
        self._git(repo_root, ["reset", "--hard", "HEAD"])
        self._git(repo_root, ["clean", "-ffdx"])
        emit("info", "git", "Fetching origin (this may take a while)")
        self._git_streaming(repo_root, ["fetch", "--prune", "--progress", "origin"], token=token, log=emit)
        self._git(repo_root, ["checkout", "--detach", "--force"])
        return repo_root

    def _prepare_user_worktree(self, repo_root: Path, user: User, source_branch: str, *, log: Logger | None = None) -> Path:
        emit = log or (lambda *_: None)
        worktree = self._worktree_path(repo_root, user)
        worktree.parent.mkdir(parents=True, exist_ok=True)
        remote_branch = f"origin/{source_branch}"
        if not self._ref_exists(repo_root, remote_branch):
            raise GitEolError(f"Source branch does not exist on origin: {source_branch}")

        emit("info", "git", "Removing existing user worktree to clear stale local changes")
        self._remove_user_worktree(repo_root, worktree, log=emit)
        self._git(repo_root, ["worktree", "prune"])
        emit("info", "git", f"Adding clean detached worktree from {remote_branch}")
        self._git_streaming(repo_root, ["worktree", "add", "--force", "--detach", str(worktree), remote_branch], log=emit)
        self._git(worktree, ["reset", "--hard", remote_branch])
        self._git(worktree, ["clean", "-ffdx"])
        emit("info", "git", f"Clean worktree ready at {worktree.name}")
        return worktree

    def _remove_user_worktree(self, repo_root: Path, worktree: Path, *, log: Logger | None = None) -> None:
        emit = log or (lambda *_: None)
        if not worktree.exists():
            return
        try:
            self._git(repo_root, ["worktree", "remove", "--force", str(worktree)])
            return
        except GitEolError as exc:
            emit("warn", "git", f"git worktree remove failed; deleting worktree directory directly: {exc}")
        self._remove_workspace_tree(worktree)

    def _remove_workspace_tree(self, path: Path) -> None:
        root = (self._workspace_root() / "worktrees").resolve()
        target = path.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise GitEolError(f"Refusing to delete path outside worktree workspace: {target}") from exc
        if target.exists():
            shutil.rmtree(target)

    def _add_worktree(self, repo_root: Path, worktree: Path, source_branch: str, *, log: Logger | None = None) -> None:
        emit = log or (lambda *_: None)
        remote_branch = f"origin/{source_branch}"
        if self._ref_exists(repo_root, remote_branch):
            emit("info", "git", f"git worktree add -B {source_branch} <- {remote_branch}")
            self._git_streaming(repo_root, ["worktree", "add", "--force", "-B", source_branch, str(worktree), remote_branch], log=emit)
            return
        if self._local_branch_exists(repo_root, source_branch):
            emit("info", "git", f"git worktree add (local branch) {source_branch}")
            self._git_streaming(repo_root, ["worktree", "add", "--force", str(worktree), source_branch], log=emit)
            return
        raise GitEolError(f"Source branch does not exist: {source_branch}")

    def _checkout_source_branch(self, worktree: Path, source_branch: str, *, log: Logger | None = None) -> None:
        emit = log or (lambda *_: None)
        if self._ref_exists(worktree, f"origin/{source_branch}"):
            emit("info", "git", f"checkout -B {source_branch} origin/{source_branch}")
            self._git_streaming(worktree, ["checkout", "--force", "-B", source_branch, f"origin/{source_branch}"], log=emit)
            return
        current_branch = self._git_text(worktree, ["branch", "--show-current"]).strip()
        if current_branch == source_branch:
            emit("info", "git", f"Already on {source_branch}")
            return
        try:
            emit("info", "git", f"checkout {source_branch}")
            self._git_streaming(worktree, ["checkout", "--force", source_branch], log=emit)
        except GitEolError:
            emit("warn", "git", f"checkout failed; retrying with --ignore-other-worktrees")
            self._git_streaming(worktree, ["checkout", "--force", "--ignore-other-worktrees", source_branch], log=emit)

    def _resolve_base_ref(self, worktree: Path, base_branch: str) -> str:
        remote_branch = f"origin/{base_branch}"
        if not base_branch.startswith("origin/") and self._ref_exists(worktree, remote_branch):
            return remote_branch
        if self._ref_exists(worktree, base_branch):
            return base_branch
        raise GitEolError(f"Base branch does not exist: {base_branch}")

    def _worktree_path(self, repo_root: Path, user: User) -> Path:
        root = self._workspace_root() / "worktrees"
        repo_hash = hashlib.sha1(str(repo_root).encode("utf-8")).hexdigest()[:10]
        safe_username = re.sub(r"[^A-Za-z0-9_.-]+", "_", user.username).strip("_")[:40] or str(user.id)
        return root / f"{repo_root.name}-{repo_hash}-user-{user.id}-{safe_username}"

    def _repo_cache_path(self, repo: str, user: User) -> Path:
        safe_repo = repo.replace("/", "__")
        repo_hash = hashlib.sha1(repo.encode("utf-8")).hexdigest()[:10]
        safe_username = re.sub(r"[^A-Za-z0-9_.-]+", "_", user.username).strip("_")[:40] or str(user.id)
        return self._workspace_root() / "repos" / f"user-{user.id}-{safe_username}" / f"{safe_repo}-{repo_hash}"

    def _workspace_root(self) -> Path:
        if settings.git_workspace_root.strip():
            return Path(settings.git_workspace_root).expanduser().resolve()
        return (Path.cwd() / ".contrack-git").resolve()

    def _normalize_repo(self, repo: str) -> str:
        repo = repo.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise GitEolError("git_repo must use owner/repo format")
        return repo

    def _normalize_branch(self, branch: str, field_name: str) -> str:
        branch = branch.strip()
        if not branch:
            raise GitEolError(f"{field_name} is required")
        if branch.startswith("-"):
            raise GitEolError(f"{field_name} is invalid")
        self._git(Path.cwd(), ["check-ref-format", "--branch", branch])
        return branch

    def _safe_worktree_file(self, worktree: Path, path: str) -> Path:
        if not path or "\x00" in path:
            raise GitEolError("Invalid file path")
        worktree_root = worktree.resolve()
        file_path = (worktree_root / Path(path)).resolve()
        try:
            file_path.relative_to(worktree_root)
        except ValueError as exc:
            raise GitEolError("File path is outside the worktree") from exc
        return file_path

    def _read_worktree_file(self, worktree: Path, path: str) -> bytes:
        file_path = self._safe_worktree_file(worktree, path)
        if not file_path.is_file():
            raise GitEolError("File does not exist in source branch")
        return file_path.read_bytes()

    def _git_object(self, worktree: Path, rev: str, path: str) -> bytes:
        return self._git_bytes(worktree, ["show", f"{rev}:{path}"])

    def _is_git_worktree(self, path: Path) -> bool:
        if not path.is_dir():
            return False
        try:
            return self._git_text(path, ["rev-parse", "--is-inside-work-tree"]).strip() == "true"
        except GitEolError:
            return False

    def _local_branch_exists(self, cwd: Path, branch: str) -> bool:
        return self._git(cwd, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], check=False).returncode == 0

    def _ref_exists(self, cwd: Path, ref: str) -> bool:
        return self._git(cwd, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], check=False).returncode == 0

    def _has_file_changes(self, worktree: Path, path: str) -> bool:
        result = self._git(worktree, ["diff", "--quiet", "--", path], check=False)
        if result.returncode == 0:
            return False
        if result.returncode == 1:
            return True
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitEolError(stderr or "Failed to inspect file changes")

    def _stage_exact_file(self, worktree: Path, path: str) -> None:
        file_path = self._safe_worktree_file(worktree, path)
        if not file_path.is_file():
            raise GitEolError(f"Fixed file no longer exists: {path}")
        mode = self._tracked_file_mode(worktree, path)
        blob_sha = self._git_text(worktree, ["hash-object", "-w", "--no-filters", "--", path]).strip()
        self._git(worktree, ["update-index", "--add", "--cacheinfo", f"{mode},{blob_sha},{path}"])

    def _tracked_file_mode(self, worktree: Path, path: str) -> str:
        output = self._git_text(worktree, ["ls-files", "-s", "--", path]).strip()
        if not output:
            return "100644"
        return output.split(maxsplit=1)[0]

    def _staged_changed_files(self, worktree: Path, files: list[str]) -> list[str]:
        result = self._git(worktree, ["diff", "--cached", "--name-only", "-z", "--", *files])
        return [token.decode("utf-8", errors="surrogateescape") for token in result.stdout.split(b"\x00") if token]

    def _git_text(self, cwd: Path, args: list[str], *, token: str | None = None, combine_output: bool = False) -> str:
        result = self._git(cwd, args, token=token)
        output = result.stdout
        if combine_output:
            output += result.stderr
        return output.decode("utf-8", errors="replace")

    def _git_bytes(self, cwd: Path, args: list[str], *, token: str | None = None) -> bytes:
        return self._git(cwd, args, token=token).stdout

    def _git(self, cwd: Path, args: list[str], *, check: bool = True, token: str | None = None) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                check=False,
                env=self._git_env(token),
            )
        except FileNotFoundError as exc:
            raise GitEolError("git command is not available") from exc
        except OSError as exc:
            raise GitEolError(str(exc)) from exc
        if check and result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            stdout = result.stdout.decode("utf-8", errors="replace").strip()
            raise GitEolError(stderr or stdout or f"git command failed: {' '.join(args)}")
        return result

    def _git_streaming(
        self,
        cwd: Path,
        args: list[str],
        *,
        token: str | None = None,
        log: Logger | None = None,
    ) -> None:
        emit = log or (lambda *_: None)
        emit("info", "git", "$ git " + " ".join(args))
        try:
            process = subprocess.Popen(
                ["git", *args],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self._git_env(token),
                bufsize=1,
                text=True,
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise GitEolError("git command is not available") from exc
        except OSError as exc:
            raise GitEolError(str(exc)) from exc

        last_lines: list[str] = []
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            emit("info", "git", line)
            last_lines.append(line)
            if len(last_lines) > 50:
                last_lines.pop(0)
        process.stdout.close()
        return_code = process.wait()
        if return_code != 0:
            tail = "\n".join(last_lines[-10:]) or f"git {' '.join(args)} failed"
            raise GitEolError(tail)

    def unified_diff(self, *, user: User, session_id: str, path: str) -> str:
        session = self._load_session(session_id, user)
        worktree = Path(session["worktree_path"])
        merge_base = session["merge_base"]
        file_map = {file["path"]: file for file in session.get("files", [])}
        file_entry = file_map.get(path)
        if not file_entry:
            raise GitEolError("File is not part of the preview")
        old_path = file_entry.get("old_path") or path
        args = [
            "diff",
            "--no-color",
            "--find-renames",
            "--unified=3",
            merge_base,
            "HEAD",
            "--",
        ]
        if old_path != path:
            args.append(old_path)
        args.append(path)
        return self._git_text(worktree, args)

    def structured_diff(self, *, user: User, session_id: str, path: str) -> dict[str, Any]:
        """Compute a side-by-side diff that also tracks EOL differences.

        Before a fix, the source side is read from the HEAD blob so checkout EOL
        conversion cannot affect the preview. After a fix, it is read from the
        worktree so the result reflects the repaired bytes.
        """
        session = self._load_session(session_id, user)
        worktree = Path(session["worktree_path"])
        merge_base = session["merge_base"]
        file_map = {file["path"]: file for file in session.get("files", [])}
        file_entry = file_map.get(path)
        if not file_entry:
            raise GitEolError("File is not part of the preview")
        old_path = file_entry.get("old_path") or path

        try:
            base_bytes = self._git_object(worktree, merge_base, old_path)
        except GitEolError:
            base_bytes = b""
        fixed_paths = {file.get("path") for file in session.get("fixed_files", [])}
        if path in fixed_paths:
            source_path = self._safe_worktree_file(worktree, path)
            source_bytes = source_path.read_bytes() if source_path.is_file() else b""
        else:
            try:
                source_bytes = self._git_object(worktree, "HEAD", path)
            except GitEolError:
                source_bytes = b""

        binary = self._is_binary(base_bytes) or self._is_binary(source_bytes)
        if binary:
            return {
                "path": path,
                "binary": True,
                "rows": [],
                "stats": {"added": 0, "removed": 0, "changed": 0, "eol_only": 0},
            }

        base_lines = self._split_lines(base_bytes)
        source_lines = self._split_lines(source_bytes)
        rows, stats = self._build_side_by_side_rows(base_lines, source_lines)
        return {
            "path": path,
            "binary": False,
            "rows": rows,
            "stats": stats,
        }

    def _build_side_by_side_rows(
        self, base_lines: list[RawLine], source_lines: list[RawLine]
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        matcher = difflib.SequenceMatcher(
            None,
            [line.content for line in base_lines],
            [line.content for line in source_lines],
            autojunk=False,
        )
        rows: list[dict[str, Any]] = []
        added = removed = changed = eol_only = 0

        def render_text(line: RawLine | None) -> str | None:
            if line is None:
                return None
            return line.content.decode("utf-8", errors="replace")

        def eol_name(line: RawLine | None) -> str | None:
            if line is None:
                return None
            if line.eol == b"\n":
                return "lf"
            if line.eol == b"\r\n":
                return "crlf"
            if line.eol == b"\r":
                return "cr"
            return "none"

        def make_side(line: RawLine | None, lineno: int | None) -> dict[str, Any] | None:
            if line is None:
                return None
            return {"lineno": lineno, "text": render_text(line), "eol": eol_name(line)}

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(i2 - i1):
                    base_line = base_lines[i1 + offset]
                    source_line = source_lines[j1 + offset]
                    eol_diff = base_line.eol != source_line.eol
                    if eol_diff:
                        eol_only += 1
                    rows.append(
                        {
                            "type": "eol" if eol_diff else "equal",
                            "left": make_side(base_line, i1 + offset + 1),
                            "right": make_side(source_line, j1 + offset + 1),
                        }
                    )
            elif tag == "replace":
                # Pair up replaced lines, pad the shorter side.
                left_count = i2 - i1
                right_count = j2 - j1
                pair_count = max(left_count, right_count)
                changed += pair_count
                for offset in range(pair_count):
                    base_line = base_lines[i1 + offset] if offset < left_count else None
                    source_line = source_lines[j1 + offset] if offset < right_count else None
                    rows.append(
                        {
                            "type": "replace" if base_line and source_line else ("delete" if base_line else "insert"),
                            "left": make_side(base_line, i1 + offset + 1 if base_line else None),
                            "right": make_side(source_line, j1 + offset + 1 if source_line else None),
                        }
                    )
            elif tag == "delete":
                removed += i2 - i1
                for offset in range(i2 - i1):
                    base_line = base_lines[i1 + offset]
                    rows.append(
                        {
                            "type": "delete",
                            "left": make_side(base_line, i1 + offset + 1),
                            "right": None,
                        }
                    )
            elif tag == "insert":
                added += j2 - j1
                for offset in range(j2 - j1):
                    source_line = source_lines[j1 + offset]
                    rows.append(
                        {
                            "type": "insert",
                            "left": None,
                            "right": make_side(source_line, j1 + offset + 1),
                        }
                    )
        stats = {"added": added, "removed": removed, "changed": changed, "eol_only": eol_only}
        return rows, stats

    def get_session(self, *, user: User, session_id: str) -> dict[str, Any]:
        return self._load_session(session_id, user)

    def _resolve_token(self, encrypted_token: str | None) -> str:
        if not encrypted_token:
            raise GitEolError("GitHub token is not configured")
        token = decrypt_secret(encrypted_token)
        if not token:
            raise GitEolError("GitHub token is invalid")
        return token

    def _git_env(self, token: str | None) -> dict[str, str] | None:
        if not token:
            return None
        encoded = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {encoded}"
        return env

    def _session_key(self, session_id: str) -> str:
        return f"git_eol:{session_id}"

    def _save_session(self, session_id: str, payload: dict[str, Any]) -> None:
        session_store.set(self._session_key(session_id), payload)

    def _load_session(self, session_id: str, user: User) -> dict[str, Any]:
        if not session_id:
            raise GitEolError("session_id is required")
        session = session_store.get(self._session_key(session_id))
        if not session:
            raise GitEolError("Git EOL session has expired")
        if session.get("user_id") != user.id:
            raise GitEolError("Git EOL session belongs to another user")
        return session
