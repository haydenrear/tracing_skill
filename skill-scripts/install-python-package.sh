#!/usr/bin/env bash
set -euo pipefail

: "${SKILL_MANAGER_BIN_DIR:?}"
: "${SKILL_MANAGER_CACHE_DIR:?}"
: "${SKILL_DIR:?}"

PACKAGE_DIR="$SKILL_DIR/sources/python"
WHEELHOUSE="$SKILL_MANAGER_CACHE_DIR/tracing-observability-wheelhouse"
mkdir -p "$WHEELHOUSE"
BUILD_MARKER="$WHEELHOUSE/.build-start"
touch "$BUILD_MARKER"

if command -v uv >/dev/null 2>&1; then
  uv build --wheel --out-dir "$WHEELHOUSE" "$PACKAGE_DIR"
  WHEEL="$(find "$WHEELHOUSE" -type f -name 'tracing_skill_observability-*.whl' -newer "$BUILD_MARKER" -print -quit)"

  if [[ -n "${UV_PROJECT_ENVIRONMENT:-}" ]]; then
    uv pip install --python "$UV_PROJECT_ENVIRONMENT/bin/python" "$WHEEL"
  elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
    uv pip install --python "$VIRTUAL_ENV/bin/python" "$WHEEL"
  fi
else
  python3 -m pip wheel --wheel-dir "$WHEELHOUSE" "$PACKAGE_DIR"
  WHEEL="$(find "$WHEELHOUSE" -type f -name 'tracing_skill_observability-*.whl' -newer "$BUILD_MARKER" -print -quit)"

  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    "$VIRTUAL_ENV/bin/python" -m pip install "$WHEEL"
  fi
fi

if [[ -z "$WHEEL" ]]; then
  echo "The observability wheel build did not produce an artifact." >&2
  exit 1
fi

cat > "$SKILL_MANAGER_BIN_DIR/tracing-observability-install" <<SH
#!/usr/bin/env bash
set -euo pipefail

WHEEL="$WHEEL"
if command -v uv >/dev/null 2>&1; then
  if [[ "\${1:-}" == "--project" && -n "\${2:-}" ]]; then
    uv pip install --project "\$2" "\$WHEEL"
  elif [[ "\${1:-}" == "--python" && -n "\${2:-}" ]]; then
    uv pip install --python "\$2" "\$WHEEL"
  elif [[ -n "\${VIRTUAL_ENV:-}" ]]; then
    uv pip install --python "\$VIRTUAL_ENV/bin/python" "\$WHEEL"
  else
    echo "Pass --project /path/to/project or --python /path/to/python, or activate a virtualenv." >&2
    exit 2
  fi
else
  if [[ -n "\${VIRTUAL_ENV:-}" ]]; then
    "\$VIRTUAL_ENV/bin/python" -m pip install "\$WHEEL"
  else
    echo "uv is not installed and no virtualenv is active. Pass an environment by activating one first." >&2
    exit 2
  fi
fi
SH

chmod +x "$SKILL_MANAGER_BIN_DIR/tracing-observability-install"
