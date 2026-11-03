param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist-railway')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$source = $PSScriptRoot
$destination = [IO.Path]::GetFullPath($OutputDirectory)
$bundle = Join-Path $destination 'backend-railway'
$zipPath = Join-Path $destination 'backend-railway.zip'
if ((Test-Path -LiteralPath $bundle) -or (Test-Path -LiteralPath $zipPath)) {
    throw 'El destino ya existe. Usa una carpeta nueva para no sobrescribir entregas.'
}
$files = @(
    'app.py', 'run_kafka_consumer.py', 'gunicorn.conf.py', 'Dockerfile',
    '.dockerignore', '.gitignore', '.env.example', '.env.railway.example',
    'kafka.railway.env.example', 'requirements.txt', 'requirements.railway.txt',
    'compose.verify.yml', 'DEPLOY_RAILWAY.md', 'VALIDACION_BACKEND.md',
    'package-backend.ps1', 'models/modelo_autonomia_residual.pkl',
    'sql/01_create_database.sql', 'sql/02_create_telemetry_table.sql',
    'sql/03_update_constraints_for_ia_mysql.sql', 'sql/04_users_households.sql',
    'tests/test_api_mysql.py', 'tests/test_multitenant.py',
    'tests/test_deployment.py', 'tests/verify_stack.py'
)
$files += Get-ChildItem -LiteralPath (Join-Path $source 'src') -Recurse -File -Filter '*.py' |
    ForEach-Object { $_.FullName.Substring($source.Length + 1).Replace('\', '/') }
foreach ($relative in $files) {
    $original = Join-Path $source $relative
    if (-not (Test-Path -LiteralPath $original -PathType Leaf)) { throw "Falta: $relative" }
    if (-not $relative.EndsWith('.pkl')) {
        $text = [Text.UTF8Encoding]::new($false, $true).GetString([IO.File]::ReadAllBytes($original))
        if ($text.IndexOf([char]0) -ge 0) { throw "Texto con NUL: $relative" }
    }
    $target = Join-Path $bundle $relative
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
    Copy-Item -LiteralPath $original -Destination $target
}
$inventory = @(Get-ChildItem -LiteralPath $bundle -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        path = $_.FullName.Substring($bundle.Length + 1).Replace('\', '/')
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = $_.Length
    }
})
$manifest = [ordered]@{ algorithm = 'SHA256'; files = $inventory }
$manifestPath = Join-Path $bundle 'MANIFEST.sha256.json'
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
$archive = [IO.Compression.ZipFile]::Open($zipPath, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in (Get-ChildItem -LiteralPath $bundle -Recurse -File -Force)) {
        $relative = $file.FullName.Substring($bundle.Length + 1).Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $relative, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $archive.Dispose() }
$archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    if ($archive.Entries.Count -ne ($inventory.Count + 1)) { throw 'Inventario ZIP inesperado' }
    foreach ($item in $inventory) {
        $entry = $archive.GetEntry($item.path)
        if ($null -eq $entry -or $entry.Length -ne $item.bytes) { throw "Falta entrada o longitud incorrecta: $($item.path)" }
        $stream = $entry.Open()
        $hasher = [Security.Cryptography.SHA256]::Create()
        try { $actual = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally { $stream.Dispose(); $hasher.Dispose() }
        if ($actual -ne $item.sha256) { throw "Hash incorrecto: $($item.path)" }
    }
} finally { $archive.Dispose() }
$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $destination 'backend-railway.zip.sha256.txt'), "$zipHash  backend-railway.zip`n", [Text.Encoding]::ASCII)
Write-Output "Paquete verificado: $($inventory.Count) archivos + manifiesto."
Write-Output "ZIP: $zipPath"
Write-Output "SHA256: $zipHash"