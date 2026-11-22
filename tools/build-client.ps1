param([string]$Flutter)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$clientRoot = Join-Path $repoRoot 'build/native_client'

if (-not $Flutter) {
    $localSdk = Join-Path $repoRoot 'build/flutter-sdk/bin/flutter.bat'
    $command = Get-Command flutter -ErrorAction SilentlyContinue
    if (Test-Path $localSdk) {
        $Flutter = $localSdk
    } elseif ($command) {
        $Flutter = $command.Source
    } else {
        $Flutter = Get-ChildItem "$env:USERPROFILE/flutter/*/bin/flutter.bat" |
            Sort-Object FullName -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
}

if (-not $Flutter) {
    throw 'Flutter is required. Pass its path with -Flutter.'
}

if (-not (Test-Path (Join-Path $clientRoot 'windows'))) {
    & $Flutter create --platforms windows --project-name dependency_client --empty --no-pub $clientRoot
    if ($LASTEXITCODE) { throw 'Flutter project creation failed.' }
}

Copy-Item -LiteralPath (Join-Path $repoRoot 'flutter_client/pubspec.yaml') -Destination $clientRoot
Copy-Item -Path (Join-Path $repoRoot 'flutter_client/lib/*.dart') -Destination (Join-Path $clientRoot 'lib')

Push-Location $clientRoot
try {
    & $Flutter pub get
    if ($LASTEXITCODE) { throw 'Flutter dependency resolution failed.' }

    & $Flutter analyze lib
    if ($LASTEXITCODE) { throw 'Flutter analysis failed.' }

    & $Flutter build windows --release --no-tree-shake-icons
    if ($LASTEXITCODE) { throw 'Flutter client build failed.' }

    Copy-Item -LiteralPath 'build/windows/x64/runner/Release/dependency_client.exe' `
        -Destination 'build/windows/x64/runner/Release/flet.exe'
} finally {
    Pop-Location
}
