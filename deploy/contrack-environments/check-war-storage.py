"""Run inside backend: python - < deploy/contrack-environments/check-war-storage.py

Creates, syncs, renames and removes its own small temporary files. Never edits a WAR or Tomcat config.
"""
import errno
import os
import shutil
import socket
import stat
import sys
import uuid

from app.modules.contrack_environments.config import contained, load_settings

settings = load_settings()
webapps = contained(settings.path("server"), "webapps")
print("container:", socket.gethostname())
print("config file:", os.environ.get("CONTRACK_ENV_CONFIG", "NOT SET"))
print("root override:", os.environ.get("CONTRACK_ENV_ROOT", "NOT SET"))
print("enabled:", settings.enabled)
print("mode:", getattr(settings, "operation_mode", "UNSUPPORTED"))
print("root:", settings.root)
print("webapps:", webapps)
if not settings.enabled or getattr(settings, "operation_mode", None) != "deploy_war":
    print("FAIL: This container has not loaded enabled Deploy WAR configuration. Recreate the intended backend with start-war-deploy.sh before checking storage.")
    sys.exit(2)
if not webapps.is_dir():
    print("FAIL: Configured webapps directory is missing inside this container. Check its effective root and Docker bind mount; no directory was created.")
    sys.exit(2)
print("UID/GID:", os.getuid(), os.getgid())
war_files = sorted(path for path in webapps.iterdir() if path.suffix.lower() == ".war")[:20]
if not war_files:
    print("existing WAR files: none")
for path in (settings.root, settings.path("server"), webapps, *war_files):
    try:
        info = path.lstat()
        print("path:", path, "mode:", stat.filemode(info.st_mode), "owner:", f"{info.st_uid}:{info.st_gid}")
    except FileNotFoundError:
        print("path:", path, "not present")
usage = shutil.disk_usage(webapps)
print("free MiB:", usage.free // (1024 * 1024))
fs = os.statvfs(webapps)
print("free inodes:", fs.f_favail)
print("filesystem read-only:", bool(fs.f_flag & getattr(os, "ST_RDONLY", 1)))

first = webapps / f".contrack-storage-probe-{uuid.uuid4().hex}.tmp"
second = webapps / f".contrack-storage-probe-{uuid.uuid4().hex}.tmp"
operation = "create temporary file"
failed = False
try:
    with first.open("xb") as output:
        operation = "chmod temporary file"
        os.chmod(first, 0o644)
        operation = "write and flush temporary file"
        output.write(b"ConTrack storage probe\n")
        output.flush()
        operation = "fsync temporary file"
        os.fsync(output.fileno())
    operation = "rename temporary file"
    os.replace(first, second)
    print("PASS: create / chmod / write / fsync / rename in webapps")
except OSError as exc:
    failed = True
    print("FAIL:", operation, "errno:", exc.errno,
          errno.errorcode.get(exc.errno, type(exc).__name__),
          os.strerror(exc.errno) if exc.errno is not None else "filesystem operation failed")
finally:
    for path in (first, second):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            failed = True
            print("FAIL: cleanup own temporary file", path.name, "errno:", exc.errno)
sys.exit(1 if failed else 0)
