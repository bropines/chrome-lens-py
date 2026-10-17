#!/bin/sh
# Install lens_scan on Linux or macOS and put it on PATH.
#
#   curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.sh | sh
#
# Unpacks the latest standalone build into ~/.local/share/lens-scan and links
# the binary into ~/.local/bin.
#
# Environment:
#   LENS_SCAN_VERSION   install this release instead of the latest (3.5.4 or v3.5.4)
#
# If you already have Python, `uv tool install chrome-lens-py` is smaller and
# updates with one command. This script is for machines without it - and it
# is the one that tells you plainly when your platform has no prebuilt binary.

set -eu

REPO='bropines/chrome-lens-py'
SHARE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/lens-scan"
BIN_DIR="$HOME/.local/bin"
# Releases from this one on publish a .sha256 next to every archive, so a
# missing one means something is wrong, not that the release is old.
CHECKSUM_REQUIRED_FROM='3.5.1'

UV_HINT='  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv tool install --python 3.12 "chrome-lens-py[clipboard]"
or run: curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.sh | sh'

step() { printf '\033[36m==>\033[0m %s\n' "$1"; }
die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

# True when dotted version $1 >= $2 (numeric, up to three fields).
version_ge() {
  awk -v a="$1" -v b="$2" 'BEGIN {
    split(a, x, "."); split(b, y, ".")
    for (i = 1; i <= 3; i++) {
      if ((x[i] + 0) > (y[i] + 0)) exit 0
      if ((x[i] + 0) < (y[i] + 0)) exit 1
    }
    exit 0
  }'
}

system=$(uname -s)
machine=$(uname -m)
case "$system/$machine" in
  Linux/x86_64|Linux/amd64)    platform='linux-amd64' ;;
  Linux/aarch64|Linux/arm64)   platform='linux-arm64' ;;
  Darwin/arm64)                platform='macos-arm64' ;;
  Darwin/x86_64)               platform='macos-x86_64' ;;
  *) die "There is no prebuilt binary for $system on $machine.
Install it with uv instead (it brings its own Python):
$UV_HINT" ;;
esac
asset="lens_scan-$platform.zip"

command -v curl >/dev/null 2>&1 || die 'curl is required.'
command -v unzip >/dev/null 2>&1 || die 'unzip is required.'

# Straight from the release download URLs, not the REST API: the API allows 60
# unauthenticated requests an hour per IP, which shared networks and CI burn
# through, and these URLs are not rate limited that way.
if [ -n "${LENS_SCAN_VERSION:-}" ]; then
  tag="v${LENS_SCAN_VERSION#v}"
  base="https://github.com/$REPO/releases/download/$tag"
else
  step 'Looking up the latest release'
  # The /latest page redirects to /releases/tag/<tag>; read where it points
  # without following it.
  location=$(curl -fsSI -o /dev/null -w '%{redirect_url}' "https://github.com/$REPO/releases/latest") \
    || die 'Could not reach github.com.'
  tag=${location##*/}
  [ -n "$tag" ] || die 'Could not work out the latest release tag.'
  # Pin to the tag just resolved, so the archive and its checksum cannot come
  # from two different releases if one is published between the requests.
  base="https://github.com/$REPO/releases/download/$tag"
fi
version=${tag#v}
numeric=${version%%[-+]*}

tmp=$(mktemp -d)
mkdir -p "$(dirname "$SHARE_DIR")" "$BIN_DIR"
# Staged beside the final location so the swap below is a rename on one
# filesystem, not a copy.
staging="$SHARE_DIR.new.$$"
backup="$SHARE_DIR.old.$$"
cleanup() { rm -rf "$tmp" "$staging"; }
trap cleanup EXIT

step "Downloading $tag ($asset)"
if ! curl -fsSL "$base/$asset" -o "$tmp/payload.zip"; then
  die "Could not download $base/$asset
Either $tag has no build for $platform, or the tag does not exist.
Releases before the standalone change shipped a single self-extracting file,
which this script deliberately does not install. Use:
$UV_HINT"
fi

# The checksum ships as its own release asset. Worth being clear about what it
# buys: it catches a truncated or corrupted download, and a CDN serving
# something other than what was uploaded. It is not a signature - anyone able
# to rewrite the release could rewrite this too.
step 'Verifying the checksum'
if sum_text=$(curl -fsSL "$base/$asset.sha256" 2>/dev/null); then
  # Pull the digest out by shape rather than by position: GNU sha256sum
  # prefixes the line with a backslash when the filename contains one, so the
  # first whitespace-delimited field is not always the hash.
  hex='[0-9a-f]\{64\}'
  expected=$(printf '%s' "$sum_text" | tr 'A-F' 'a-f' | grep -o "$hex" | head -1 || true)
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
elif version_ge "$numeric" "$CHECKSUM_REQUIRED_FROM"; then
  die "$tag should publish $asset.sha256 but it could not be fetched - not installing an unverified download."
else
  printf '  note: %s predates published checksums, so the download was not verified.\n' "$tag"
fi

step 'Unpacking'
mkdir -p "$tmp/out"
unzip -q "$tmp/payload.zip" -d "$tmp/out"
# The archive holds one folder; its name has changed before, so find it.
payload=$(find "$tmp/out" -mindepth 1 -maxdepth 1 -type d | head -1)
[ -n "$payload" ] || die 'The archive did not contain a folder.'
mv "$payload" "$staging"

binary_name='lens_scan.bin'
[ -f "$staging/$binary_name" ] || binary_name='lens_scan'
[ -f "$staging/$binary_name" ] || die "No lens_scan binary in the archive."
chmod +x "$staging/$binary_name"

# Prove the new copy runs before touching the one that works.
step 'Checking it runs'
if ! output=$("$staging/$binary_name" --help 2>&1); then
  die "The binary did not start:
$(printf '%s' "$output" | head -3)
On an older Linux this is usually a glibc that is too old for the build. Use:
$UV_HINT"
fi

step 'Installing'
if [ -e "$SHARE_DIR" ]; then
  mv "$SHARE_DIR" "$backup"
fi
rollback() {
  rm -rf "$SHARE_DIR"
  if [ -e "$backup" ]; then mv "$backup" "$SHARE_DIR"; fi
}
if ! mv "$staging" "$SHARE_DIR"; then
  rollback
  die 'Could not move the new install into place; the previous one was restored.'
fi
binary="$SHARE_DIR/$binary_name"
if ! ln -sf "$binary" "$BIN_DIR/lens_scan" || ! "$BIN_DIR/lens_scan" --help >/dev/null 2>&1; then
  rollback
  if [ -e "$SHARE_DIR/$binary_name" ]; then ln -sf "$SHARE_DIR/$binary_name" "$BIN_DIR/lens_scan"; fi
  die 'The installed copy failed its final check; the previous install was restored.'
fi
rm -rf "$backup"

printf '\n\033[32mInstalled %s to %s\033[0m\n' "$tag" "$SHARE_DIR"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '\033[33m%s is not on your PATH. Add it to your shell profile:\033[0m\n' "$BIN_DIR"
     printf '  export PATH="%s:$PATH"\n' "$BIN_DIR" ;;
esac
printf '  lens_scan image.png -t ru        translate an image\n'
printf '  lens_scan status                 check what is installed and running\n'
printf '  lens_scan update                 update later\n'
