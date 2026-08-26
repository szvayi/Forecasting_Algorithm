# Execute database write
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Execute database write" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Set-Location "C:\Users\VY0814\Forecasting_Algorithm"

Write-Host ""
Write-Host "1. Execute database write..." -ForegroundColor Yellow
python write_db_full.py

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Done!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
