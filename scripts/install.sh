#!/bin/sh
# Install lens_scan on Linux or macOS and put it on PATH.
#
#   curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.sh | sh
#
# Unpacks the latest standalone build into ~/.local/share/lens-scan and links
# the binary into ~/.local/bin.
#
# If you already have Python, `uv tool install chrome-lens-py` is smaller and
# updates with one command. This script is for machines without it.

set -eu

REPO='bropines/chrome-lens-py'
SHARE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/lens-scan"
BIN_DIR="$HOME/.local/bin"

step() { printf '\033[36m==>\033[0m %s\n' "$1"; }
die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

case "$(uname -s)" in
  Linux)  asset='lens_scan-linux-amd64.zip' ;;
  Darwin) asset='lens_scan-macos-arm64.zip' ;;
  *)      die "Unsupported system: $(uname -s). Try: uv tool install chrome-lens-py" ;;
esac

command -v curl >/dev/null 2>&1 || die 'curl is required.'
command -v unzip >/dev/null 2>&1 || die 'unzip is required.'

step 'Looking up the latest release'
api="https://api.github.com/repos/$REPO/releases/latest"
release=$(curl -fsSL -H 'User-Agent: lens-scan-installer' "$api")

tag=$(printf '%s' "$release" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)
url=$(printf '%s' "$release" \
  | tr ',' '\n' \
  | grep 'browser_download_url' \
  | grep "$asset" \
  | sed -n 's/.*"\(https[^"]*\)".*/\1/p' \
  | head -1)

if [ -z "${url:-}" ]; then
  # Releases before the switch to a standalone folder shipped a bare binary.
  die "$tag has no $asset.
Releases before the standalone change shipped a single self-extracting file,
which this script deliberately does not install. Use
  uv tool install chrome-lens-py
or take an asset by hand from https://github.com/$REPO/releases"
fi

step "Downloading $tag"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "$url" -o "$tmp/payload.zip"

# The checksum ships as its own release asset. Worth being clear about what it
# buys: it catches a truncated or corrupted download, and a CDN serving
# something other than what was uploaded. It is not a signature - anyone able
# to rewrite the release could rewrite this too.
sum_url=$(printf '%s' "$release" \
  | tr ',' '\n' \
  | grep 'browser_download_url' \
  | grep "$asset.sha256" \
  | sed -n 's/.*"\(https[^"]*\)".*/\1/p' \
  | head -1)

if [ -n "${sum_url:-}" ]; then
  step 'Verifying the checksum'
  # Pull the digest out by shape rather than by position: GNU sha256sum
  # prefixes the line with a backslash when the filename contains one, so the
  # first whitespace-delimited field is not always the hash.
  hex='[0-9a-f]\{64\}'
  expected=$(curl -fsSL "$sum_url" | tr 'A-F' 'a-f' | grep -o "$hex" | head -1)
  if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$tmp/payload.zip" | tr 'A-F' 'a-f' | grep -o "$hex" | head -1)
  else
    actual=$(shasum -a 256 "$tmp/payload.zip" | tr 'A-F' 'a-f' | grep -o "$hex" | head -1)
  fi
  [ -n "$expected" ] || die 'Could not read a SHA-256 out of the checksum file.'
  if [ "$expected" != "$actual" ]; then
    die "Checksum mismatch - not installing.
  expected $expected
  got      $actual
Try again; if it keeps failing, open an issue at
https://github.com/$REPO/issues rather than running the file."
  fi
else
  printf '  note: %s publishes no checksum, so the download was not verified.\n' "$tag"
fi

step 'Unpacking'
unzip -q "$tmp/payload.zip" -d "$tmp/out"
# The archive holds one folder; its name has changed before, so find it.
payload=$(find "$tmp/out" -mindepth 1 -maxdepth 1 -type d | head -1)
[ -n "$payload" ] || die 'The archive did not contain a folder.'

rm -rf "$SHARE_DIR"
mkdir -p "$(dirname "$SHARE_DIR")" "$BIN_DIR"
mv "$payload" "$SHARE_DIR"

binary="$SHARE_DIR/lens_scan.bin"
[ -f "$binary" ] || binary="$SHARE_DIR/lens_scan"
[ -f "$binary" ] || die "No lens_scan binary under $SHARE_DIR."
chmod +x "$binary"

step 'Checking it runs'
"$binary" --help >/dev/null 2>&1 || die 'The binary did not start.'

ln -sf "$binary" "$BIN_DIR/lens_scan"

printf '\n\033[32mInstalled %s to %s\033[0m\n' "$tag" "$SHARE_DIR"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '\033[33m%s is not on your PATH. Add it to your shell profile:\033[0m\n' "$BIN_DIR"
     printf '  export PATH="%s:$PATH"\n' "$BIN_DIR" ;;
esac
printf '  lens_scan image.png -t ru        translate an image\n'
printf '  lens_scan --serve                run as a local daemon\n'
