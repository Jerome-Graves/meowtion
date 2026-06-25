# Build + UF2-flash the Meowtion collar using the locally-installed nRF Connect SDK,
# WITHOUT needing the nRF Connect VS Code extension or `west` on PATH. It reconstructs the
# toolchain environment from the NCS install under C:\ncs (mirrors that toolchain's
# environment.json), builds with the cdc-acm-console snippet (USB serial logs), then copies
# the UF2 to the XIAO bootloader drive if it is mounted.
#
# Run it directly:  powershell -ExecutionPolicy Bypass -File firmware\collar\build.ps1
# Or via the VS Code task "Build+Flash Collar".
$ErrorActionPreference = 'Stop'

$ncs = 'C:\ncs'
$tc  = (Get-ChildItem "$ncs\toolchains" -Directory -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
$zb  = (Get-ChildItem $ncs -Directory -Filter 'v*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1).FullName + '\zephyr'
if (-not $tc) { throw "No nRF Connect SDK toolchain found under $ncs\toolchains" }
if (-not (Test-Path $zb)) { throw "ZEPHYR_BASE not found: $zb" }

$env:PATH = "$tc\opt\bin\Scripts;$tc\opt\bin;$tc\mingw64\bin;$tc\bin;$tc\nrfutil\bin;$tc\opt\nanopb\generator-bin;$tc\opt\zephyr-sdk\arm-zephyr-eabi\bin;$tc\opt\zephyr-sdk\riscv64-zephyr-elf\bin;$env:PATH"
$env:PYTHONPATH = "$tc\opt\bin;$tc\opt\bin\Lib;$tc\opt\bin\Lib\site-packages"
$env:NRFUTIL_HOME = "$tc\nrfutil\home"
$env:ZEPHYR_TOOLCHAIN_VARIANT = 'zephyr'
$env:ZEPHYR_SDK_INSTALL_DIR = "$tc\opt\zephyr-sdk"
$env:ZEPHYR_BASE = $zb
Write-Host "NCS toolchain: $tc"
Write-Host "ZEPHYR_BASE:   $zb"

Set-Location $PSScriptRoot
west build -b xiao_ble/nrf52840/sense        # Sense variant: onboard PDM mic + LSM6DS3 IMU
if ($LASTEXITCODE -ne 0) { throw "west build failed (exit $LASTEXITCODE)" }

# Sysbuild (the NCS default) nests the artifact under build\<image>\zephyr\, so find it.
$uf2 = Get-ChildItem (Join-Path $PSScriptRoot 'build') -Recurse -Filter zephyr.uf2 -ErrorAction SilentlyContinue | Select-Object -First 1
$v   = Get-Volume | Where-Object { $_.FileSystemLabel -like 'XIAO*' } | Select-Object -First 1
if ($uf2 -and $v) {
    Copy-Item $uf2.FullName ($v.DriveLetter + ':/') -Force
    Write-Host "Flashed $($uf2.FullName) to $($v.DriveLetter):"
    Write-Host "Watch telemetry: open the collar COM port (e.g. COM10) in VS Code Serial Monitor or PuTTY at any baud."
} else {
    Write-Host "Built OK. No XIAO UF2 drive mounted: double-tap RESET on the collar, then run this again."
}
