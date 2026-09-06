# Plant agentize launchers in the current project (Windows).
# If uv/uvx is missing, download a verified GitHub release into ~/.local/bin.
# Usage:
#   iex (curl.exe -fsSL https://raw.githubusercontent.com/pleware/agentize/main/scripts/install.ps1)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Do not assign to the automatic Windows flag: names are case-insensitive
# and that variable is constant. `irm | iex` runs in the current scope.
if ($env:OS -ne "Windows_NT" -and $env:AGENTIZE_SKIP_OS_CHECK -ne "1") {
  throw "agentize: this installer is for Windows; on Linux or macOS use the sh installers"
}

$Dest = if ($env:AGENTIZE_DEST) { $env:AGENTIZE_DEST } else { "." }
$Base = if ($env:AGENTIZE_INSTALL_BASE) {
  $env:AGENTIZE_INSTALL_BASE
} else {
  "https://raw.githubusercontent.com/pleware/agentize/main/scripts"
}
$UvRelease = if ($env:AGENTIZE_UV_RELEASE) {
  $env:AGENTIZE_UV_RELEASE
} else {
  "https://github.com/astral-sh/uv/releases/latest/download"
}
$UvBin = if ($env:AGENTIZE_UV_BIN) {
  $env:AGENTIZE_UV_BIN
} else {
  Join-Path $HOME ".local\bin"
}

function Write-AgentizeLog([string]$Message) {
  Write-Host "agentize: $Message"
}

$https = $Base.StartsWith("https://")
$local = -not $https
if (-not $https -and -not [IO.Path]::IsPathRooted($Base) -and $Base -notmatch '^[A-Za-z]:[\\/]') {
  throw "agentize: AGENTIZE_INSTALL_BASE must be an https URL or a local path"
}

$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("agentize-install-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null

function Get-RemoteFile([string]$Url, [string]$OutFile) {
  if ($Url.StartsWith("https://")) {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $OutFile
    return
  }
  if (-not (Test-Path -LiteralPath $Url)) { throw "agentize: missing $Url" }
  Copy-Item -LiteralPath $Url -Destination $OutFile
}

function Get-AgentizeFile([string]$Rel, [string]$OutFile) {
  Get-RemoteFile "$Base/$Rel" $OutFile
}

function Get-UvAsset {
  if ($env:AGENTIZE_UV_ASSET) { return $env:AGENTIZE_UV_ASSET }
  $raw = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
  switch -Regex ($raw.ToLowerInvariant()) {
    "amd64|x64" { return "uv-x86_64-pc-windows-msvc.zip" }
    "arm64" { return "uv-aarch64-pc-windows-msvc.zip" }
    default { throw "agentize: no uv build for Windows/$raw" }
  }
}

function Install-UvIfMissing {
  $uv = Get-Command uv -ErrorAction SilentlyContinue
  $uvx = Get-Command uvx -ErrorAction SilentlyContinue
  if ($uv -and $uvx) { return }

  $asset = Get-UvAsset
  Write-AgentizeLog "uv not found; downloading $asset"
  $archive = Join-Path $TempRoot $asset
  $sidecar = Join-Path $TempRoot "$asset.sha256"
  Get-RemoteFile "$UvRelease/$asset" $archive
  Get-RemoteFile "$UvRelease/$asset.sha256" $sidecar
  $expected = ((Get-Content -LiteralPath $sidecar -Raw -Encoding utf8) -split "\s+")[0].ToLowerInvariant()
  if (-not $expected) { throw "agentize: uv checksum file is empty" }
  $actual = Get-Sha256 $archive
  if ($actual -ne $expected) { throw "agentize: checksum failed for $asset" }

  $extract = Join-Path $TempRoot "uv-extract"
  New-Item -ItemType Directory -Force -Path $extract, $UvBin | Out-Null
  Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
  $uvFile = Get-ChildItem -LiteralPath $extract -Recurse -File | Where-Object { $_.Name -eq "uv.exe" } | Select-Object -First 1
  $uvxFile = Get-ChildItem -LiteralPath $extract -Recurse -File | Where-Object { $_.Name -eq "uvx.exe" } | Select-Object -First 1
  if (-not $uvFile) { throw "agentize: uv archive had no uv.exe" }
  Copy-Item -LiteralPath $uvFile.FullName -Destination (Join-Path $UvBin "uv.exe") -Force
  if ($uvxFile) {
    Copy-Item -LiteralPath $uvxFile.FullName -Destination (Join-Path $UvBin "uvx.exe") -Force
  } else {
    Copy-Item -LiteralPath (Join-Path $UvBin "uv.exe") -Destination (Join-Path $UvBin "uvx.exe") -Force
  }
  $env:Path = "$UvBin;$env:Path"
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "agentize: installed uv but it is not on PATH"
  }
  if ($env:AGENTIZE_UV_SKIP_PATH_WRITE -ne "1") {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    if ($userPath -notlike "*$UvBin*") {
      $joined = if ($userPath) { "$UvBin;$userPath" } else { $UvBin }
      [Environment]::SetEnvironmentVariable("Path", $joined, "User")
    }
  }
  Write-AgentizeLog "installed uv to $UvBin (open a new terminal if the next command cannot find uvx)"
}

function Get-Sha256([string]$Path) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $stream = [System.IO.File]::OpenRead($Path)
    try {
      return -join ($sha.ComputeHash($stream) | ForEach-Object { $_.ToString("x2") })
    } finally {
      $stream.Dispose()
    }
  } finally {
    $sha.Dispose()
  }
}

function Get-ExpectedHash([string]$Checksums, [string]$Name) {
  $escaped = [regex]::Escape($Name)
  $line = (
    $Checksums -split "\r?\n" |
    Where-Object { $_ -match "^[0-9a-fA-F]{64}\s+\*?$escaped\s*$" } |
    Select-Object -First 1
  )
  if (-not $line) { throw "agentize: checksums.txt does not contain $Name" }
  return ($line -split "\s+")[0].ToLowerInvariant()
}

try {
  Install-UvIfMissing
  $checksumsFile = Join-Path $TempRoot "checksums.txt"
  Get-AgentizeFile "checksums.txt" $checksumsFile
  $checksums = Get-Content -LiteralPath $checksumsFile -Raw -Encoding utf8
  if ([string]::IsNullOrWhiteSpace($checksums)) {
    throw "agentize: downloaded checksums.txt is empty"
  }

  foreach ($name in @("agentize", "agentize.ps1", "agentize.cmd")) {
    $staged = Join-Path $TempRoot $name
    Get-AgentizeFile "launchers/$name" $staged
    $expected = Get-ExpectedHash $checksums $name
    $actual = Get-Sha256 $staged
    if ($actual -ne $expected) { throw "agentize: checksum failed for $name" }
  }

  New-Item -ItemType Directory -Force -Path $Dest | Out-Null
  foreach ($name in @("agentize", "agentize.ps1", "agentize.cmd")) {
    Copy-Item -LiteralPath (Join-Path $TempRoot $name) -Destination (Join-Path $Dest $name) -Force
  }
  Write-AgentizeLog "wrote launchers in $Dest"
  Write-AgentizeLog "PowerShell will not run agentize from here without a prefix"
  $yaml = Join-Path $Dest "agentize.yaml"
  if (Test-Path -LiteralPath $yaml) {
    Write-AgentizeLog "next: .\agentize fetch"
  } else {
    Write-AgentizeLog "next: add agentize.yaml, then .\agentize fetch"
  }
} finally {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $TempRoot
}
