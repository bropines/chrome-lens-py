<#
.SYNOPSIS
    Install lens_scan with uv on Windows.

.DESCRIPTION
    Installs uv if it is missing, then installs lens_scan as a uv tool and puts
    it on PATH.

    Run with:
      irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.ps1 | iex

    Prefer this over install.ps1. It fetches roughly 15 MB instead of 25, it
    updates with one command, and because nothing is frozen into an executable
    there is no self-extraction for antivirus heuristics to react to. uv brings
    its own Python, so none is needed beforehand.

    install.ps1 remains for machines where installing uv is not wanted.
#>

$ErrorActionPreference = 'Stop'

# The clipboard extra comes along: --sharex is the whole point of the ShareX
# workflow, and without pyperclip it degrades to a log line telling you to
# install this anyway.
$Package = 'chrome-lens-py[clipboard]'

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }

# uv may be installed and simply not on PATH: its own installer edits the
# persisted PATH, which a shell that is already running never picks up. Look
# where it puts things before concluding it is missing, or we reinstall it
# needlessly.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $known = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path (Join-Path $known 'uv.exe')) { $env:Path = "$known;$env:Path" }
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Step "uv is already installed ($(uv --version))"
} else {
    Write-Step 'Installing uv'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression

    # The uv installer edits the persisted PATH, which does not reach a shell
    # that is already running - including this one. Add it for this session so
    # the rest of the script can proceed.
    $uvBin = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path $uvBin) { $env:Path = "$uvBin;$env:Path" }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Error 'uv was installed but is not on PATH here. Open a new terminal and run this again.'
    }
}

# --upgrade covers both cases: a first install, and moving an existing one to
# the current release.
Write-Step 'Installing lens_scan'
uv tool install --upgrade $Package
if ($LASTEXITCODE -ne 0) { Write-Error 'uv tool install failed.' }

Write-Step 'Putting it on your PATH'
uv tool update-shell | Out-Null

$binDir = (uv tool dir --bin).Trim()
$exe = Join-Path $binDir 'lens_scan.exe'
if (-not (Test-Path $exe)) { Write-Error "uv reported success but there is no lens_scan in $binDir." }

# Checked with --help rather than --version: --version only exists from 3.5.1,
# and this script has to be able to verify whatever release it just installed.
Write-Step 'Checking it runs'
& $exe --help | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error 'lens_scan did not start.' }

if (($env:Path -split ';') -notcontains $binDir) {
    $env:Path = "$binDir;$env:Path"
    Write-Host ''
    Write-Host 'PATH updated. Open a new terminal for it to take effect everywhere.' -ForegroundColor Yellow
}

Write-Host ''
& $exe --version 2>$null
Write-Host ''
Write-Host "Installed to $exe"

# Another lens_scan earlier on PATH wins, and that is easy to miss: a pyenv
# shim from a pip install, or an older standalone build.
$found = (Get-Command lens_scan -ErrorAction SilentlyContinue).Source
if ($found -and $found -ne $exe) {
    Write-Host ''
    Write-Host "Note: typing 'lens_scan' runs $found, not the copy just installed." -ForegroundColor Yellow
    Write-Host "      That one comes earlier on your PATH. Run 'lens_scan --version' to see which is which."
}
Write-Host ''
Write-Host '  lens_scan image.png -t ru        translate an image' -ForegroundColor Green
Write-Host '  lens_scan --setup-sharex         wire it into ShareX'
Write-Host '  lens_scan --serve                run as a local daemon'
Write-Host ''
Write-Host '  uv tool upgrade chrome-lens-py   update later'
Write-Host '  uv tool uninstall chrome-lens-py remove it'
