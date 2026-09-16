#!/bin/sh
# Install lens_scan with uv on Linux or macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.sh | sh
#
# Installs uv if it is missing, then installs lens_scan as a uv tool and puts
# it on PATH.
#
# Prefer this over install.sh: it fetches roughly 15 MB instead of 22-37, it
# updates with one command, and nothing is frozen into an executable. uv brings
# its own Python, so none is needed beforehand.
#
# install.sh remains for machines where installing uv is not wanted.

set -eu

# The clipboard extra comes along: --sharex is the whole point of the ShareX
# workflow, and without pyperclip it degrades to a log line telling you to
# install this anyway.
PACKAGE='chrome-lens-py[clipboard]'

step() { printf '\033[36m==>\033[0m %s\n' "$1"; }
die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

# uv may be installed and simply not on PATH: its own installer writes to the
# shell profile, and a non-interactive shell never reads that. Look where it
# puts things before concluding it is missing, or we reinstall it needlessly.
if ! command -v uv >/dev/null 2>&1; then
  for candidate in "$HOME/.local/bin" "${XDG_BIN_HOME:-}" "${CARGO_HOME:-$HOME/.cargo}/bin"; do
    if [ -n "$candidate" ] && [ -x "$candidate/uv" ]; then
      PATH="$candidate:$PATH"
      export PATH
      break
    fi
  done
fi

if command -v uv >/dev/null 2>&1; then
  step "uv is already installed ($(uv --version))"
else
  command -v curl >/dev/null 2>&1 || die 'curl is required.'
  step 'Installing uv'
  curl -fsSL https://astral.sh/uv/install.sh | sh

  # The uv installer edits your shell profile, which does not reach a shell
  # that is already running - including this one. Add it for this session so
  # the rest of the script can proceed.
  for candidate in "$HOME/.local/bin" "${XDG_BIN_HOME:-}" "${CARGO_HOME:-$HOME/.cargo}/bin"; do
    [ -n "$candidate" ] && [ -x "$candidate/uv" ] && PATH="$candidate:$PATH" && export PATH
  done

  command -v uv >/dev/null 2>&1 || die 'uv was installed but is not on PATH here. Open a new terminal and run this again.'
fi

# --upgrade covers both cases: a first install, and moving an existing one to
# the current release.
step 'Installing lens_scan'
uv tool install --upgrade "$PACKAGE"

step 'Putting it on your PATH'
uv tool update-shell >/dev/null 2>&1 || true

bin_dir=$(uv tool dir --bin)
binary="$bin_dir/lens_scan"
[ -x "$binary" ] || die "uv reported success but there is no lens_scan in $bin_dir."

# Checked with --help rather than --version: --version only exists from 3.5.1,
# and this script has to be able to verify whatever release it just installed.
step 'Checking it runs'
"$binary" --help >/dev/null 2>&1 || die 'lens_scan did not start.'

printf '\n'
"$binary" --version 2>/dev/null || true
printf '\nInstalled to %s\n' "$binary"

# Another lens_scan earlier on PATH wins, and that is easy to miss: a pip
# install in an active virtualenv, or an older standalone build.
found=$(command -v lens_scan 2>/dev/null || true)
if [ -n "$found" ] && [ "$found" != "$binary" ]; then
  printf '\033[33mNote: typing '"'"'lens_scan'"'"' runs %s, not the copy just installed.\033[0m\n' "$found"
  printf '      That one comes earlier on your PATH. Run '"'"'lens_scan --version'"'"' to see which is which.\n'
fi
printf '\n'
case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *) printf '\033[33m%s is not on this shell'"'"'s PATH yet - open a new terminal.\033[0m\n' "$bin_dir" ;;
esac
printf '\033[32m  lens_scan image.png -t ru        translate an image\033[0m\n'
printf '  lens_scan --serve                run as a local daemon\n'
printf '\n'
printf '  uv tool upgrade chrome-lens-py   update later\n'
printf '  uv tool uninstall chrome-lens-py remove it\n'
