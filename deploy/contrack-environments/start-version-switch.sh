#!/usr/bin/env bash
# Run on the Linux host after configuring the restricted SSH host runner.
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
CT_ENV_ROOT="$(realpath -e -- "${CT_ENV_ROOT:-$PROJECT_DIR/../Contrack-Recreate/contrack-env}")"
CT_ENV_CONFIG="${CT_ENV_CONFIG:-$(dirname -- "$CT_ENV_ROOT")/config/switch-version.yaml}"
CT_SWITCH_SSH_DIR="${CT_SWITCH_SSH_DIR:-$(dirname -- "$CT_ENV_ROOT")/secrets/switch-ssh}"
export CT_ENV_ROOT CT_ENV_CONFIG CT_SWITCH_SSH_DIR

# Key mode requires id_ed25519; password mode does not. The rebuilt backend validates
# the selected authentication method and its credential before calling the host.
for required in "$CT_ENV_CONFIG" "$CT_SWITCH_SSH_DIR/known_hosts"; do
  test -f "$required" || { printf 'Missing required file: %s\nRead docs/contrack-version-switch.md first.\n' "$required" >&2; exit 1; }
done
test -d "$CT_ENV_ROOT/runtime/server/webapps"
test -f "$CT_ENV_ROOT/runtime/server/conf/server.xml"

cd -- "$PROJECT_DIR"
compose() {
  docker compose --project-directory "$PROJECT_DIR" -f "$PROJECT_DIR/docker-compose.yml" \
    -f "$SCRIPT_DIR/compose.switch-version.override.yaml" "$@"
}
compose config --quiet
# Preserve the original backend's bundled frontend and local-server artifacts.
docker build -f "$PROJECT_DIR/backend/Dockerfile" -t contrack-tool-backend:switch-base "$PROJECT_DIR"
compose build backend frontend
compose up -d postgres redis
compose up -d --no-deps --force-recreate backend frontend
compose exec -T backend python - <<'PYTHON'
from app.modules.contrack_environments.config import load_settings
from app.modules.contrack_environments.version_switch import VersionSwitchService
settings = load_settings()
if not settings.enabled or settings.operation_mode != "switch_version":
    raise SystemExit("Backend must load enabled switch_version configuration.")
service = VersionSwitchService(settings)
service._check_host()
catalog = service.catalog()
print("VERIFIED: switch_version enabled; host runner, JDBC selector, PostgreSQL and shared root checked.")
print("SSH authentication:", settings.switch_version.auth_method)
print("WARs:", len(catalog["wars"]), "database baselines:", len(catalog["databases"]))
PYTHON
printf '\nReload with Ctrl+F5, choose ConTrack WAR and Database Profile, then Validate selection / Switch Version.\n'
printf 'No application WAR or database has been switched by this launcher.\n'
