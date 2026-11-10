# Full pipeline: OCR -> table reconstruction -> verification
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $py (Join-Path $PSScriptRoot "src\run_ocr.py");     if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $py (Join-Path $PSScriptRoot "src\reconstruct.py"); if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $py (Join-Path $PSScriptRoot "src\verify.py");      if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $py (Join-Path $PSScriptRoot "src\review.py");      exit $LASTEXITCODE
