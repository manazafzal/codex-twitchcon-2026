$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$Log = Join-Path $PWD '.nous-setup.log'
function Run-Checked {
    param([string]$Program, [string[]]$Arguments)
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Program @Arguments *>> $Log
        $ResultCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $PreviousPreference }
    if ($ResultCode -ne 0) { throw 'That step did not finish. Check your internet connection and try setup.bat again.' }
}
try {
    Write-Host 'Finding Python, the helper that runs NOUS...'
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        try {
            & $Launcher.Source -3.11 -c "import sys; assert sys.version_info >= (3,11)" 2>$null
            if ($LASTEXITCODE -ne 0) { $Launcher = $null }
        } catch { $Launcher = $null }
    }
    $ExistingPython = $null
    if (-not $Launcher) {
        $Candidate = Get-Command python -ErrorAction SilentlyContinue
        if ($Candidate -and $Candidate.Source -notlike '*WindowsApps*') {
            try {
                & $Candidate.Source -c "import sys; assert (3,11) <= sys.version_info < (3,14)" 2>$null
                if ($LASTEXITCODE -eq 0) { $ExistingPython = $Candidate.Source }
            } catch { $ExistingPython = $null }
        }
    }
    if ($ExistingPython) {
        Run-Checked $ExistingPython @('-m','venv','.venv')
    } elseif (-not $Launcher) {
        $Winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $Winget) { throw 'Install Python 3.11 from python.org/downloads/windows, then double-click setup.bat again. Tick Add Python to PATH during installation.' }
        Write-Host 'Installing Python. Windows may ask you to allow this...'
        Run-Checked $Winget.Source @('install','--id','Python.Python.3.11','--exact','--scope','user','--silent','--accept-source-agreements','--accept-package-agreements')
        $Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
        if (-not (Test-Path $Python)) { throw 'Python has installed. Close this window and double-click setup.bat once more.' }
        Run-Checked $Python @('-m','venv','.venv')
    } else {
        Run-Checked $Launcher.Source @('-3.11','-m','venv','.venv')
    }
    $Python = Join-Path $PWD '.venv\Scripts\python.exe'
    Write-Host 'Installing the helper tools. The first setup takes a few minutes...'
    Run-Checked $Python @('-m','pip','install','--upgrade','pip')
    Run-Checked $Python @('-m','pip','install','--prefer-binary','-e','.')
    Write-Host 'Getting the AI helper ready. The recording works even if this step pauses...'
    try { Run-Checked $Python @('-m','pip','install','--prefer-binary','-e','.[model]') } catch {
        Write-Host 'The AI helper paused. The recorded demo is ready; run setup.bat again later for the AI.' -ForegroundColor Yellow
    }
    Write-Host 'Downloading the AI brain (about 1 GB)...'
    try { Run-Checked $Python @('-m','nous.install') } catch {
        Write-Host 'The AI download paused. You can still try the recorded demo. Run setup.bat again later to retry.' -ForegroundColor Yellow
    }
    Write-Host 'Ready! Opening NOUS in your browser. Keep this window open while you play.' -ForegroundColor Green
    try { Run-Checked $Python @('-m','nous.cli','start') } catch {
        throw 'NOUS could not open. If an older NOUS window is running, use its browser tab or close that window and try setup.bat again.'
    }
} catch {
    Write-Host ''
    Write-Host ('We hit a snag: ' + $_.Exception.Message) -ForegroundColor Yellow
    Write-Host 'You can safely run setup.bat again. Your saved scores will stay here. Details are in .nous-setup.log.'
    exit 1
}
