#!/usr/bin/env bash
# Install the pinned review engine (opencode CLI) release into ENGINE_DIR.
set -euo pipefail

: "${ENGINE_VERSION:?ENGINE_VERSION must be set}"
: "${ENGINE_DIR:?ENGINE_DIR must be set}"

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) echo "::error title=Skopos::Unsupported runner OS $(uname -s)"; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64 | amd64) arch=x64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) echo "::error title=Skopos::Unsupported runner architecture $(uname -m)"; exit 1 ;;
esac

if [ "$os" = linux ]; then
  asset="opencode-linux-${arch}.tar.gz"
else
  asset="opencode-darwin-${arch}.zip"
fi
url="https://github.com/anomalyco/opencode/releases/download/${ENGINE_VERSION}/${asset}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "Installing review engine ${ENGINE_VERSION} (${asset})"
curl -fsSL --retry 3 "$url" -o "$tmp/$asset"
mkdir -p "$tmp/x" "$ENGINE_DIR"
if [ "$os" = linux ]; then
  tar -xzf "$tmp/$asset" -C "$tmp/x"
else
  unzip -q "$tmp/$asset" -d "$tmp/x"
fi
bin="$(find "$tmp/x" -type f -name opencode | head -n 1)"
if [ -z "$bin" ]; then
  echo "::error title=Skopos::Engine binary not found in ${asset}"
  exit 1
fi
install -m 0755 "$bin" "$ENGINE_DIR/opencode"
"$ENGINE_DIR/opencode" --version
