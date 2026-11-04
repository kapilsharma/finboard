# Windows entry point for scripts/ci-local.sh (same options: -fast is spelled --fast, etc.).
#   powershell -File scripts\ci-local.ps1 --fast
# Runs the bash script with Git for Windows' bash, which ships with Git.
$ErrorActionPreference = 'Stop'

$bash = $null
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    # ...\Git\cmd\git.exe  ->  ...\Git\bin\bash.exe
    $candidate = Join-Path (Split-Path (Split-Path $git.Source)) 'bin\bash.exe'
    if (Test-Path $candidate) { $bash = $candidate }
}
if (-not $bash) {
    Write-Error 'Git Bash not found. Install Git for Windows (https://git-scm.com), or run scripts/ci-local.sh from WSL.'
}

& $bash (Join-Path $PSScriptRoot 'ci-local.sh') @args
exit $LASTEXITCODE
