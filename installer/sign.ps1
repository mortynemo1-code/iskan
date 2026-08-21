param(
  [Parameter(Mandatory = $true)][string]$MsiPath,
  [string]$CertificateThumbprint = $env:WINDOWS_SIGNING_CERT_THUMBPRINT,
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $MsiPath)) { throw "MSI not found: $MsiPath" }
if ([string]::IsNullOrWhiteSpace($CertificateThumbprint)) {
  throw "Set WINDOWS_SIGNING_CERT_THUMBPRINT or pass -CertificateThumbprint"
}

$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Filter signtool.exe -Recurse |
  Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
  Sort-Object FullName -Descending |
  Select-Object -First 1
if (-not $signtool) { throw "signtool.exe from Windows SDK was not found" }

& $signtool.FullName sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $MsiPath
if ($LASTEXITCODE -ne 0) { throw "signtool failed with exit code $LASTEXITCODE" }
& $signtool.FullName verify /pa /all /v $MsiPath
if ($LASTEXITCODE -ne 0) { throw "signature verification failed with exit code $LASTEXITCODE" }
Write-Host "Signed and verified: $MsiPath"
