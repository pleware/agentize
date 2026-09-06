$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$pyproject = Join-Path $here "pyproject.toml"
if ((Test-Path $pyproject) -and (
    Select-String -LiteralPath $pyproject -Pattern '^name = "agentize"' -Quiet
)) {
    & uv run --project $here agentize @args
    exit $LASTEXITCODE
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    [Console]::Error.WriteLine("agentize: uv is not on PATH")
    exit 1
}
$uvx = @()
if ($env:AGENTIZE_OFFLINE) {
    $uvx += "--offline"
} else {
    $uvx += "--refresh"
}
& uvx @uvx --from git+https://github.com/pleware/agentize.git agentize @args
exit $LASTEXITCODE
