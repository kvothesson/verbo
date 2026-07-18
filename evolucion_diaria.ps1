# Evolución diaria de VERBO — pensado para correr como tarea programada de Windows.
# Corre UNA iteración de auto-mejora (lo que el tier gratis banca por día),
# y pushea a GitHub las mejoras que la selección natural aceptó.
#
# Registrada como tarea: schtasks /Query /TN "VERBO Evolucion Diaria"
# Para desactivarla:      schtasks /Delete /TN "VERBO Evolucion Diaria" /F
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$log = Join-Path $here "evals\evolucion.log"

Set-Location (Join-Path $here "evals")
python evolucionar.py --iteraciones 1 -r 1 --pausa 20 2>> (Join-Path $here "evals\evolucion_errores.log")

Set-Location $here
$push = git push origin main 2>&1 | Out-String
Add-Content -Path $log -Value "[push $(Get-Date -Format s)] $($push.Trim())" -Encoding utf8
