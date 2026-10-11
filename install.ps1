# VRCam Studio installer. Run via install.bat (it handles the execution policy).
# Everything is logged to install.log - send that file if something fails.
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
Start-Transcript -Path (Join-Path $PSScriptRoot "install.log") -Force | Out-Null

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "INSTALL FAILED: $msg" -ForegroundColor Red; Write-Host "Send install.log (in this folder) for help."; Stop-Transcript | Out-Null; exit 1 }

# SpoutGL has wheels for CPython 3.8 - 3.13
$okVersions = @("3.13", "3.12", "3.11", "3.10", "3.9")

function Find-Python {
    # 1) py launcher
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in $okVersions) {
            try { $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() } } catch {}
        }
    }
    # 2) python on PATH (skip the Microsoft Store stub)
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
            try {
                $v = & $cmd.Source -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
                if ($okVersions -contains "$v".Trim()) { return $cmd.Source }
            } catch {}
        }
    }
    # 3) standard install folders
    foreach ($v in $okVersions) {
        $n = $v -replace "\.", ""
        foreach ($root in @("$env:LOCALAPPDATA\Programs\Python\Python$n", "$env:ProgramFiles\Python$n", "C:\Python$n")) {
            $exe = Join-Path $root "python.exe"
            if (Test-Path $exe) { return $exe }
        }
    }
    return $null
}

Step "Looking for Python 3.9-3.13"
$py = Find-Python
if (-not $py) {
    Step "Python not found - installing Python 3.12 with winget"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "winget is not available. Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run install.bat again."
    }
    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    $py = Find-Python
    if (-not $py) { Fail "Python was installed but can't be found yet. Close this window and run install.bat again." }
}
Write-Host "Using $py"

Step "Creating virtual environment (.venv)"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $py -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "could not create .venv" }
}
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Step "Installing Python packages"
& $vpy -m pip install --upgrade pip
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install failed (see messages above)" }

Step "Getting ffmpeg"
$ff = Join-Path $PSScriptRoot "tools\ffmpeg\bin\ffmpeg.exe"
if (-not (Test-Path $ff)) {
    New-Item -ItemType Directory -Force -Path "tools" | Out-Null
    $zip = Join-Path $PSScriptRoot "tools\ff.zip"
    $tmp = Join-Path $PSScriptRoot "tools\ff_tmp"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest ~10x faster
    Write-Host "Downloading ffmpeg (~100 MB)..."
    Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip -UseBasicParsing
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
    if (Test-Path "tools\ffmpeg") { Remove-Item "tools\ffmpeg" -Recurse -Force }
    Move-Item $inner.FullName (Join-Path $PSScriptRoot "tools\ffmpeg")
    Remove-Item $zip -Force
    Remove-Item $tmp -Recurse -Force
    if (-not (Test-Path $ff)) { Fail "ffmpeg download/unzip failed" }
}
Write-Host "ffmpeg: $ff"

Step "Checking everything (doctor)"
& $vpy -m studio doctor

Write-Host ""
Write-Host "Install complete. Start the studio with run.bat" -ForegroundColor Green
Stop-Transcript | Out-Null
