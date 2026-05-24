#!/usr/bin/env bash
set -euo pipefail

: "${SKILL_MANAGER_BIN_DIR:?}"
: "${SKILL_MANAGER_CACHE_DIR:?}"
: "${SKILL_DIR:?}"

PACKAGE_DIR="$SKILL_DIR/sources/python"
WHEELHOUSE="$SKILL_MANAGER_CACHE_DIR/tracing-observability-wheelhouse"
mkdir -p "$WHEELHOUSE"

if command -v uv >/dev/null 2>&1; then
  uv build --wheel --out-dir "$WHEELHOUSE" "$PACKAGE_DIR"

  if [[ -n "${UV_PROJECT_ENVIRONMENT:-}" ]]; then
    uv pip install --python "$UV_PROJECT_ENVIRONMENT/bin/python" "$PACKAGE_DIR"
  elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
    uv pip install --python "$VIRTUAL_ENV/bin/python" "$PACKAGE_DIR"
  fi
else
  python3 -m pip wheel --wheel-dir "$WHEELHOUSE" "$PACKAGE_DIR"

  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    "$VIRTUAL_ENV/bin/python" -m pip install "$PACKAGE_DIR"
  fi
fi

cat > "$SKILL_MANAGER_BIN_DIR/tracing-observability-install" <<SH
#!/usr/bin/env bash
set -euo pipefail

SOURCE="$PACKAGE_DIR"
if command -v uv >/dev/null 2>&1; then
  if [[ "\${1:-}" == "--project" && -n "\${2:-}" ]]; then
    uv pip install --project "\$2" "\$SOURCE"
  elif [[ "\${1:-}" == "--python" && -n "\${2:-}" ]]; then
    uv pip install --python "\$2" "\$SOURCE"
  elif [[ -n "\${VIRTUAL_ENV:-}" ]]; then
    uv pip install --python "\$VIRTUAL_ENV/bin/python" "\$SOURCE"
  else
    echo "Pass --project /path/to/project or --python /path/to/python, or activate a virtualenv." >&2
    exit 2
  fi
else
  if [[ -n "\${VIRTUAL_ENV:-}" ]]; then
    "\$VIRTUAL_ENV/bin/python" -m pip install "\$SOURCE"
  else
    echo "uv is not installed and no virtualenv is active. Pass an environment by activating one first." >&2
    exit 2
  fi
fi
SH

chmod +x "$SKILL_MANAGER_BIN_DIR/tracing-observability-install"
