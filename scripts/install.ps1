<#
.SYNOPSIS
    Install lens_scan on Windows and put it on PATH.

.DESCRIPTION
    Downloads the latest standalone build, unpacks it into
    %LOCALAPPDATA%\Programs\lens-scan and adds that folder to the user PATH.

    Run with:
      irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.ps1 | iex

    Two builds exist:
      nuitka    a compiled lens_scan.exe. Fastest to start, but it is a brand
                new unsigned executable, which some antivirus products
                quarantine.
      portable  the official Python (signed by the Python Software Foundation)
                plus the package as plain files. Slower to start, and contains
                no executable of ours. Run as lens_scan.cmd.

    The compiled build is tried first. If it does not start, or antivirus
    removes it a moment after unpacking, the portable build is installed
    instead.

    Environment:
      LENS_SCAN_FLAVOR   nuitka or portable: install exactly that one
      LENS_SCAN_VERSION  install this release instead of the latest (3.5.4 or v3.5.4)

    If you already have Python, `uv tool install chrome-lens-py` is smaller,
    updates with one command, and gives antivirus heuristics nothing to react
    to. This script exists for machines without it.
#>

$ErrorActionPreference = 'Stop'
# Invoke-WebRequest draws a progress bar by default, and in Windows PowerShell
# 5.1 that makes a 25 MB download take minutes.
$ProgressPreference = 'SilentlyContinue'
# Windows PowerShell 5.1 negotiates TLS 1.0/1.1 unless told otherwise, and
# GitHub refuses those.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

$Repo = 'bropines/chrome-lens-py'
$InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\lens-scan'
$Staging = "$InstallDir.new"
$Backup = "$InstallDir.old"
# Releases from this one on publish a .sha256 next to every archive, so a
# missing one means something is wrong, not that the release is old.
$ChecksumRequiredFrom = [version]'3.5.1'

$Flavors = @{
    nuitka   = @{ Asset = 'lens_scan-windows-amd64.zip';          Entry = 'lens_scan.exe' }
    portable = @{ Asset = 'lens_scan-windows-amd64-portable.zip'; Entry = 'lens_scan.cmd' }
}

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }

function Resolve-Tag {
    if ($env:LENS_SCAN_VERSION) { return 'v' + $env:LENS_SCAN_VERSION.TrimStart('vV') }

    # Straight from the release pages, not the REST API: the API allows 60
    # unauthenticated requests an hour per IP, which shared networks burn
    # through. /releases/latest redirects to /releases/tag/<tag>; read where it
    # points without following it.
    Write-Step 'Looking up the latest release'
    $request = [System.Net.HttpWebRequest]::Create("https://github.com/$Repo/releases/latest")
    $request.AllowAutoRedirect = $false
    $request.Method = 'HEAD'
    $request.UserAgent = 'lens-scan-installer'
    $response = $request.GetResponse()
    try { $location = $response.Headers['Location'] } finally { $response.Close() }
    if (-not $location) { Write-Error 'Could not work out the latest release tag.' }
    return ($location -split '/')[-1]
}

function Get-ExpectedHash($url, $asset, $tag) {
    try {
        $line = (Invoke-WebRequest "$url.sha256" -UseBasicParsing).Content
        if ($line -is [byte[]]) { $line = [System.Text.Encoding]::ASCII.GetString($line) }
    } catch {
        $numeric = ($tag.TrimStart('v') -split '[-+]')[0]
        $parsed = $null
        if ([version]::TryParse($numeric, [ref]$parsed) -and $parsed -ge $ChecksumRequiredFrom) {
            Write-Error "$tag should publish $asset.sha256 but it could not be fetched - not installing an unverified download."
        }
        Write-Host "  note: $tag predates published checksums, so the download was not verified." -ForegroundColor DarkYellow
        return $null
    }
    # Pull the digest out by shape rather than by position: GNU sha256sum
    # prefixes the line with a backslash when the filename contains one, so
    # "first whitespace-delimited field" is not always the hash.
    if ($line -notmatch '([0-9a-fA-F]{64})') { Write-Error "Could not read a SHA-256 out of the checksum file: $line" }
    return $Matches[1].ToLowerInvariant()
}

function Remove-Quietly($path) {
    if (Test-Path $path) { Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue }
}

# Download, verify and unpack one build into $Staging, then prove it runs.
# Returns $null on success, or a sentence saying why the build is unusable
# (it did not start, or antivirus took it). Real errors - a bad checksum, no
# such asset - throw instead.
function Stage-Build($flavor, $tag) {
    $asset = $Flavors[$flavor].Asset
    $entry = $Flavors[$flavor].Entry
    $base = "https://github.com/$Repo/releases/download/$tag"

    Write-Step "Downloading $tag ($asset)"
    $temp = Join-Path ([System.IO.Path]::GetTempPath()) "lens-scan-$([guid]::NewGuid())"
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    try {
        $zip = Join-Path $temp $asset
        try {
            Invoke-WebRequest "$base/$asset" -OutFile $zip -UseBasicParsing
        } catch {
            Write-Error @"
Could not download $base/$asset
Either $tag has no '$flavor' build, or the tag does not exist.
Releases before the standalone change shipped a single-file .exe, which this
script deliberately does not install - it self-extracts on every run, which is
both slow and what antivirus heuristics flag.
Use 'uv tool install --python 3.12 chrome-lens-py' instead, or grab an asset by
hand from https://github.com/$Repo/releases
"@
        }

        # The checksum ships as its own release asset. Worth being clear about
        # what that buys: it catches a truncated or corrupted download, and a
        # CDN serving something other than what was uploaded. It is not a
        # signature - anyone able to rewrite the release could rewrite this too.
        Write-Step 'Verifying the checksum'
        $expected = Get-ExpectedHash "$base/$asset" $asset $tag
        if ($expected) {
            # Get-FileHash returns uppercase, sha256sum lowercase; compare one case.
            $actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $expected) {
                Write-Error @"
Checksum mismatch - not installing.
  expected $expected
  got      $actual
Try again; if it keeps failing, open an issue at
https://github.com/$Repo/issues rather than running the file.
"@
            }
        }

        Write-Step 'Unpacking'
        Remove-Quietly $Staging
        $out = Join-Path $temp 'out'
        try {
            Expand-Archive -Path $zip -DestinationPath $out -Force
        } catch {
            return "unpacking failed ($($_.Exception.Message)) - antivirus may have blocked the files"
        }
        # The archive holds one folder; its name has changed before, so find it
        # rather than assuming.
        $payload = Get-ChildItem $out -Directory | Select-Object -First 1
        if (-not $payload) { Write-Error 'The archive did not contain a folder.' }
        New-Item -ItemType Directory -Path (Split-Path $InstallDir) -Force | Out-Null
        Move-Item $payload.FullName $Staging
    } finally {
        Remove-Quietly $temp
    }

    # Antivirus often acts a moment AFTER the files land, not as they land, so
    # look again after a pause rather than trusting the first answer.
    $exe = Join-Path $Staging $entry
    Start-Sleep -Seconds 2
    if (-not (Test-Path $exe)) {
        return "$entry vanished right after unpacking - looks like your antivirus quarantined it"
    }
    Write-Step 'Checking it runs'
    try {
        & $exe --version *> $null
        $code = $LASTEXITCODE
    } catch {
        return "$entry would not start ($($_.Exception.Message))"
    }
    if ($code -ne 0) { return "$entry exited with code $code" }
    Start-Sleep -Seconds 2
    if (-not (Test-Path $exe)) {
        return "$entry disappeared after it was run - looks like your antivirus quarantined it"
    }
    return $null
}

# Replace the live install with the staged one, restoring the old one if
# anything goes wrong on the way.
function Swap-In($entry) {
    Remove-Quietly $Backup
    $hadOld = Test-Path $InstallDir
    try {
        if ($hadOld) {
            Write-Step 'Replacing the existing install'
            Move-Item $InstallDir $Backup
        }
        Move-Item $Staging $InstallDir
        $exe = Join-Path $InstallDir $entry
        & $exe --help *> $null
        if ($LASTEXITCODE -ne 0) { throw "$entry failed its final check" }
    } catch {
        $reason = $_.Exception.Message
        Remove-Quietly $InstallDir
        if ($hadOld -and (Test-Path $Backup)) { Move-Item $Backup $InstallDir }
        Write-Error "Install failed ($reason); the previous install was restored. If lens_scan is running (e.g. --serve), close it and try again."
    }
    Remove-Quietly $Backup
}

$tag = Resolve-Tag

$forced = $env:LENS_SCAN_FLAVOR
if ($forced -and -not $Flavors.ContainsKey($forced)) {
    Write-Error "LENS_SCAN_FLAVOR must be 'nuitka' or 'portable', not '$forced'."
}

$flavor = if ($forced) { $forced } else { 'nuitka' }
$why = Stage-Build $flavor $tag
if ($why -and -not $forced) {
    Remove-Quietly $Staging
    Write-Host ''
    Write-Host "The compiled build is unusable here: $why." -ForegroundColor Yellow
    Write-Host 'Looks like your antivirus quarantined the compiled build; installing the portable build signed by the Python Software Foundation instead.' -ForegroundColor Yellow
    Write-Host ''
    $flavor = 'portable'
    $why = Stage-Build $flavor $tag
}
if ($why) {
    Remove-Quietly $Staging
    Write-Error "The '$flavor' build is unusable here: $why."
}

$entry = $Flavors[$flavor].Entry
Swap-In $entry

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
Write-Host "Installed $tag ($flavor build) to $InstallDir" -ForegroundColor Green
Write-Host '  lens_scan image.png -t ru        translate an image'
Write-Host '  lens_scan sharex                 wire it into ShareX'
Write-Host '  lens_scan status                 check what is installed and running'
Write-Host '  lens_scan update                 update later'
