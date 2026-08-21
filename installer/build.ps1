param(
  [string]$Configuration = "Release",
  [string]$Version = "1.0.0",
  [switch]$Sign,
  [string]$CertificateThumbprint = $env:WINDOWS_SIGNING_CERT_THUMBPRINT,
  [string]$FfmpegPath = $env:FFMPEG_PATH
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$publish = Join-Path $PSScriptRoot "publish"
dotnet publish "$root\agent\Workforce.Agent\Workforce.Agent.csproj" -c $Configuration -r win-x64 --self-contained true -p:PublishSingleFile=true -o "$publish\service"
dotnet publish "$root\agent\Workforce.SessionAgent\Workforce.SessionAgent.csproj" -c $Configuration -r win-x64 --self-contained true -p:PublishSingleFile=true -o "$publish\session"
if ([string]::IsNullOrWhiteSpace($FfmpegPath)) {
  $ffmpegCommand = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
  if ($ffmpegCommand) { $FfmpegPath = $ffmpegCommand.Source }
}
if ([string]::IsNullOrWhiteSpace($FfmpegPath) -or -not (Test-Path $FfmpegPath)) {
  throw "ffmpeg.exe is required. Set FFMPEG_PATH or add it to PATH."
}
Copy-Item $FfmpegPath "$publish\session\ffmpeg.exe" -Force
dotnet build "$PSScriptRoot\Workforce.Agent.Installer\Workforce.Agent.Installer.wixproj" -c $Configuration -p:Version=$Version -p:AgentPublish="$publish\service" -p:SessionPublish="$publish\session"
$msi = Get-ChildItem "$PSScriptRoot\Workforce.Agent.Installer\bin\$Configuration" -Filter *.msi -Recurse |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if (-not $msi) { throw "MSI was not produced" }
if ($Sign) {
  & "$PSScriptRoot\sign.ps1" -MsiPath $msi.FullName -CertificateThumbprint $CertificateThumbprint
}
Write-Host "MSI created: $($msi.FullName)"
