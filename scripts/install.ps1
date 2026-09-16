<#
.SYNOPSIS
    Install lens_scan on Windows and put it on PATH.

.DESCRIPTION
    Downloads the latest standalone build, unpacks it into
    %LOCALAPPDATA%\Programs\lens-scan and adds that folder to the user PATH.

    Run with:
      irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.ps1 | iex

    If you already have Python, `uv tool install chrome-lens-py` is smaller,
    updates with one command, and gives antivirus heuristics nothing to react
    to. This script exists for machines without it.
#>

$ErrorActionPreference = 'Stop'

$Repo = 'bropines/chrome-lens-py'
$Asset = 'lens_scan-windows-amd64.zip'
$InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\lens-scan'

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }

Write-Step 'Looking up the latest release'
$release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" `
    -Headers @{ 'User-Agent' = 'lens-scan-installer' }

$download = $release.assets | Where-Object { $_.name -eq $Asset } | Select-Object -First 1
if (-not $download) {
    # Releases before the switch to a standalone folder shipped a single .exe.
    Write-Error @"
$($release.tag_name) has no $Asset.
Releases before the standalone change shipped a single-file .exe, which this
script deliberately does not install - it self-extracts on every run, which is
both slow and what antivirus heuristics flag.
Use 'uv tool install chrome-lens-py' instead, or grab an asset by hand from
https://github.com/$Repo/releases
"@
}

Write-Step "Downloading $($release.tag_name) ($([math]::Round($download.size / 1MB, 1)) MB)"
$temp = Join-Path ([System.IO.Path]::GetTempPath()) "lens-scan-$([guid]::NewGuid())"
New-Item -ItemType Directory -Path $temp -Force | Out-Null
$zip = Join-Path $temp $Asset
Invoke-WebRequest $download.browser_download_url -OutFile $zip -UseBasicParsing

Write-Step 'Unpacking'
Expand-Archive -Path $zip -DestinationPath $temp -Force

# The archive holds one folder; its name has changed before, so find it rather
# than assuming.
$payload = Get-ChildItem $temp -Directory | Select-Object -First 1
if (-not $payload) { Write-Error 'The archive did not contain a folder.' }

if (Test-Path $InstallDir) {
    Write-Step 'Replacing the existing install'
    Remove-Item $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Path (Split-Path $InstallDir) -Force | Out-Null
Move-Item $payload.FullName $InstallDir
Remove-Item $temp -Recurse -Force

$exe = Join-Path $InstallDir 'lens_scan.exe'
if (-not (Test-Path $exe)) { Write-Error "No lens_scan.exe under $InstallDir." }

Write-Step 'Checking it runs'
& $exe --help | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error 'The binary did not start.' }

# Read the *user* PATH from the registry rather than $env:PATH, which is the
# merged machine+user value and would write the machine half into the user half.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $InstallDir) {
    Write-Step 'Adding to your PATH'
    $updated = if ([string]::IsNullOrEmpty($userPath)) { $InstallDir }
               else { "$($userPath.TrimEnd(';'));$InstallDir" }
    [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
    $env:Path = "$env:Path;$InstallDir"
    Write-Host ''
    Write-Host 'PATH updated. Open a new terminal for it to take effect.' -ForegroundColor Yellow
} else {
    Write-Step 'Already on your PATH'
}

Write-Host ''
Write-Host "Installed $($release.tag_name) to $InstallDir" -ForegroundColor Green
Write-Host '  lens_scan image.png -t ru        translate an image'
Write-Host '  lens_scan --setup-sharex         wire it into ShareX'
Write-Host '  lens_scan --serve                run as a local daemon'
