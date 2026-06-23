# Script PowerShell para agendar o Atualizador do Memorial da Copa 2026 no Windows
$ErrorActionPreference = "Stop"

Write-Host "===================================================" -ForegroundColor Green
Write-Host "  Agendador do Memorial da Copa 2026 para Windows" -ForegroundColor Green
Write-Host "===================================================" -ForegroundColor Green
Write-Host ""

# Detect python path
$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Host "[AVISO] Python.exe não foi encontrado no PATH. Usando comando padrão 'python.exe'." -ForegroundColor Yellow
    $python = "python.exe"
} else {
    Write-Host "[INFO] Python encontrado em: $python" -ForegroundColor Green
}

$scriptPath = Join-Path $PSScriptRoot "updater.py"
Write-Host "[INFO] Caminho do script: $scriptPath" -ForegroundColor Green
Write-Host ""
Write-Host "[INFO] Criando tarefa agendada no Windows..."
Write-Host "[INFO] A tarefa rodará a cada 1 hora para manter os jogos atualizados."
Write-Host ""

# Create task using schtasks to run hourly
$taskCommand = 'schtasks /create /tn "Copa2026Memorial" /tr "\"' + $python + '\" \"' + $scriptPath + '\"" /sc hourly /mo 1 /f'
Invoke-Expression $taskCommand

Write-Host ""
Write-Host "===================================================" -ForegroundColor Green
Write-Host "  [SUCESSO] Tarefa 'Copa2026Memorial' criada!" -ForegroundColor Green
Write-Host "  Ela rodará a cada 1 hora no seu PC para atualizar placares e vídeos." -ForegroundColor Green
Write-Host "===================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Pressione Enter para fechar..."
