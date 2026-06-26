<#
  build.ps1 - Build the Meowtion technical documentation with XeLaTeX + Biber.

  No Perl and no latexmk required (this machine has neither): the passes are run
  by hand. Everything LaTeX generates goes in .\build so the source folder stays
  clean, and that one folder is the only thing .gitignore needs to exclude.

  Run from anywhere (the script cd's to its own folder):
    .\build.ps1                  full build  (xelatex, biber, xelatex, xelatex)
    .\build.ps1 -Quick           single xelatex pass (fast; skips bibliography)
    .\build.ps1 -Clean           delete the build folder and stop
    .\build.ps1 -Clean -Full     clean, then full rebuild
    .\build.ps1 -View            (full) build, then open the PDF
#>
[CmdletBinding()]
param(
    [switch]$Quick,
    [switch]$Clean,
    [switch]$Full,
    [switch]$View
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$buildDir = Join-Path $PSScriptRoot 'build'
$job = 'main'

if ($Clean) {
    if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
    Write-Host 'Cleaned build/' -ForegroundColor Yellow
    if (-not ($Quick -or $Full -or $View)) { return }
}

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

function Invoke-Xelatex {
    xelatex -interaction=nonstopmode -halt-on-error -output-directory=build "$job.tex"
    if ($LASTEXITCODE -ne 0) { throw "xelatex failed (exit $LASTEXITCODE) - see build/$job.log" }
}

Write-Host 'XeLaTeX pass 1...' -ForegroundColor Cyan
Invoke-Xelatex

if (-not $Quick) {
    Write-Host 'Biber...' -ForegroundColor Cyan
    # Run biber from the source folder (so it finds references.bib) while reading the
    # .bcf and writing the .bbl in build/ via --output-directory.
    biber --output-directory build $job
    if ($LASTEXITCODE -ne 0) { throw "biber failed (exit $LASTEXITCODE) - see build/$job.blg" }

    Write-Host 'XeLaTeX pass 2...' -ForegroundColor Cyan
    Invoke-Xelatex
    Write-Host 'XeLaTeX pass 3...' -ForegroundColor Cyan
    Invoke-Xelatex
}

$pdf = Join-Path $buildDir "$job.pdf"
Write-Host "Done: $pdf" -ForegroundColor Green
if ($View -and (Test-Path $pdf)) { Start-Process $pdf }
