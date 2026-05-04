#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

VERSION_ARG="${1:-}"
DEPLOY_CHOICE="${2:-}"

if [ "$VERSION_ARG" = "help" ] || [ "$VERSION_ARG" = "--help" ] || [ "$VERSION_ARG" = "-h" ]; then
  cat <<'EOF'
Usage:
  ./create-version.sh patch [--deploy|--no-deploy]
  ./create-version.sh minor [--deploy|--no-deploy]
  ./create-version.sh major [--deploy|--no-deploy]
  ./create-version.sh 0.1.1 [--deploy|--no-deploy]

Examples:
  ./create-version.sh patch
  ./create-version.sh 0.2.0 --deploy
EOF
  exit 0
fi

if [ -z "$VERSION_ARG" ]; then
  printf '\nEnter new version or bump type.\n'
  printf 'Examples: patch, minor, major, 0.2.0\n'
  printf 'Version [patch]: '
  read -r VERSION_ARG
  VERSION_ARG="${VERSION_ARG:-patch}"
fi

printf '\nContrack local server release\n'
printf '=============================\n'
printf 'Version argument: %s\n\n' "$VERSION_ARG"

if ! command -v npm >/dev/null 2>&1; then
  printf 'ERROR: npm was not found in PATH.\n' >&2
  exit 1
fi

printf 'Updating package version...\n'
npm version "$VERSION_ARG" --no-git-tag-version

NEW_VERSION=$(node -p "require('./package.json').version")
if [ -z "$NEW_VERSION" ]; then
  printf 'ERROR: Could not read package.json version.\n' >&2
  exit 1
fi

printf '\nBuilding web and local server release for version %s...\n' "$NEW_VERSION"
npm run build

printf '\nRelease artifacts created:\n'
printf '  build_output/web\n'
printf '  build_output/local-server\n'
printf '  build_output/releases/local-server/latest.json\n'
printf '  build_output/releases/local-server/contrack-local-server-%s.bundle.json.gz\n\n' "$NEW_VERSION"

case "$DEPLOY_CHOICE" in
  --deploy|deploy)
    DEPLOY=1
    ;;
  --no-deploy|no-deploy)
    DEPLOY=0
    ;;
  *)
    printf 'Deploy Docker now with docker compose up --build -d? [y/N]: '
    read -r ANSWER
    case "$ANSWER" in
      y|Y|yes|YES|Yes) DEPLOY=1 ;;
      *) DEPLOY=0 ;;
    esac
    ;;
esac

if [ "$DEPLOY" = "1" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    printf 'ERROR: docker was not found in PATH.\n' >&2
    exit 1
  fi
  printf '\nDeploying Docker services...\n'
  docker compose up --build -d
fi

printf '\nDone. Current release version: %s\n' "$NEW_VERSION"
