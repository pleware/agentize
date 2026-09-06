#!/bin/sh
# Plant agentize launchers in the current project (Linux).
# If uv/uvx is missing, download a verified GitHub release into ~/.local/bin.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/pleware/agentize/main/scripts/install.sh | sh
set -eu

if [ "${AGENTIZE_SKIP_OS_CHECK:-}" != 1 ] && [ "$(uname -s)" != Linux ]; then
  printf '%s\n' "agentize: this installer is for Linux; on macOS use install-macos.sh" >&2
  exit 1
fi

DEST="${AGENTIZE_DEST:-.}"
BASE="${AGENTIZE_INSTALL_BASE:-https://raw.githubusercontent.com/pleware/agentize/main/scripts}"
UV_RELEASE="${AGENTIZE_UV_RELEASE:-https://github.com/astral-sh/uv/releases/latest/download}"
UV_BIN="${AGENTIZE_UV_BIN:-$HOME/.local/bin}"

log() { printf '%s\n' "agentize: $*"; }
die() { printf '%s\n' "agentize: $*" >&2; exit 1; }

case "$BASE" in
  https://*|/*|[A-Za-z]:[\\/]*) ;;
  *) die "AGENTIZE_INSTALL_BASE must be an https URL or a local path" ;;
esac

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT INT TERM

fetch_url() {
  url="$1"
  out="$2"
  case "$url" in
    https://*)
      command -v curl >/dev/null 2>&1 || die "missing required command: curl"
      curl -fsSL "$url" -o "$out"
      ;;
    /*|[A-Za-z]:[\\/]*)
      [ -f "$url" ] || die "missing $url"
      cp "$url" "$out"
      ;;
    *)
      die "refusing to fetch $url"
      ;;
  esac
}

fetch() {
  fetch_url "$BASE/$1" "$2"
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    die "missing sha256sum or shasum"
  fi
}

expected_hash() {
  awk -v name="$1" '$2 == name || $2 == "*" name { print $1; exit }' "$TMP/checksums.txt"
}

uv_asset() {
  if [ -n "${AGENTIZE_UV_ASSET:-}" ]; then
    printf '%s\n' "$AGENTIZE_UV_ASSET"
    return
  fi
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) printf '%s\n' "uv-x86_64-unknown-linux-gnu.tar.gz" ;;
    aarch64|arm64) printf '%s\n' "uv-aarch64-unknown-linux-gnu.tar.gz" ;;
    *) die "no uv build for Linux/$arch" ;;
  esac
}

append_path_line() {
  file="$1"
  line="$2"
  [ -f "$file" ] || return 0
  grep -F "$UV_BIN" "$file" >/dev/null 2>&1 && return 0
  printf '\n# agentize: uv\n%s\n' "$line" >> "$file"
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1 && command -v uvx >/dev/null 2>&1; then
    return
  fi
  asset="$(uv_asset)"
  log "uv not found; downloading $asset"
  fetch_url "$UV_RELEASE/$asset" "$TMP/$asset"
  fetch_url "$UV_RELEASE/${asset}.sha256" "$TMP/$asset.sha256"
  expected="$(awk '{print $1}' "$TMP/$asset.sha256")"
  [ -n "$expected" ] || die "uv checksum file is empty"
  actual="$(sha256_file "$TMP/$asset")"
  [ "$actual" = "$expected" ] || die "checksum failed for $asset"

  mkdir -p "$TMP/uv-extract" "$UV_BIN"
  tar -xzf "$TMP/$asset" -C "$TMP/uv-extract"
  uv_bin=""
  uvx_bin=""
  for path in "$TMP/uv-extract"/* "$TMP/uv-extract"/*/*; do
    [ -f "$path" ] || continue
    case "$(basename "$path")" in
      uv) uv_bin="$path" ;;
      uvx) uvx_bin="$path" ;;
    esac
  done
  [ -n "$uv_bin" ] || die "uv archive had no uv binary"
  cp "$uv_bin" "$UV_BIN/uv"
  chmod +x "$UV_BIN/uv"
  if [ -n "$uvx_bin" ]; then
    cp "$uvx_bin" "$UV_BIN/uvx"
  else
    cp "$UV_BIN/uv" "$UV_BIN/uvx"
  fi
  chmod +x "$UV_BIN/uvx"
  PATH="$UV_BIN:$PATH"
  export PATH
  [ -x "$UV_BIN/uv" ] && [ -x "$UV_BIN/uvx" ] || die "installed uv but the files are not executable"
  if [ "${AGENTIZE_UV_SKIP_PATH_WRITE:-}" != 1 ]; then
    append_path_line "$HOME/.profile" "export PATH=\"$UV_BIN:\$PATH\""
    append_path_line "$HOME/.bashrc" "export PATH=\"$UV_BIN:\$PATH\""
  fi
  log "installed uv to $UV_BIN (open a new terminal if the next command cannot find uvx)"
}

ensure_uv

fetch checksums.txt "$TMP/checksums.txt"
[ -s "$TMP/checksums.txt" ] || die "downloaded checksums.txt is empty"

for name in agentize agentize.ps1 agentize.cmd; do
  fetch "launchers/$name" "$TMP/$name"
  expected="$(expected_hash "$name")"
  [ -n "$expected" ] || die "checksums.txt does not contain $name"
  actual="$(sha256_file "$TMP/$name")"
  [ "$actual" = "$expected" ] || die "checksum failed for $name"
done

mkdir -p "$DEST"
for name in agentize agentize.ps1 agentize.cmd; do
  cp "$TMP/$name" "$DEST/$name"
done
chmod +x "$DEST/agentize"

log "wrote launchers in $DEST"
log "next: add agentize.yaml, then ./agentize fetch"
