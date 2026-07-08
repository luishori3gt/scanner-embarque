# Script para iniciar la app con Turso configurado (desarrollo local)
# Ejecutar: .\start_turso.ps1

$env:TURSO_DATABASE_URL = "libsql://scanner-vpc-luishori3gt.aws-us-east-1.turso.io"
$env:TURSO_AUTH_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODM0ODQ0MjUsImlkIjoiMDE5ZjNmZjMtYjAwMS03ZmMwLWE3MzgtZWE0YmZhMGE4NzcwIiwia2lkIjoiRUR3WjlJeE5IZlBxR0ZQa1Q0MWlBUkdpU3I2aFVWYmFaOHVBNEc3dnhhNCIsInJpZCI6ImNhN2Q5NjY0LWYyZjItNDVjNC05ZTg2LTkxOTczNzQ3MmRhZiJ9.5vC8cKP7Y_40vQqD3yvFxx2UZSovDehAzgCcK-a8pnWhroaXH3UqwTcT2Rb0MevWTPJy5s4OLyjZ3VTx8QUpCQ"

Write-Host "Iniciando Scanner VPC con Turso..." -ForegroundColor Green
python app_multi_v3.py
