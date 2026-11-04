param([string]$VitisRun='D:\FPGA\2026.1\Vitis\bin\vitis-run.bat')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot)
if(Test-Path -LiteralPath 'X:\'){throw 'X: is already mapped; no existing mapping will be changed'}
& subst.exe X: $root
if($LASTEXITCODE -ne 0){throw 'Short path mapping failed'}
$oldStage=$env:YUV50_STAGE
try {
    $env:YUV50_STAGE='export'
    Push-Location 'X:\'
    try {
        & $VitisRun --mode hls --tcl 'X:\build_hls.tcl' *> 'X:\evidence\hls_build.log'
        if($LASTEXITCODE -ne 0){throw 'Split v4 HLS/C-RTL failed; inspect evidence/hls_build.log'}
    } finally {Pop-Location}
} finally {
    $env:YUV50_STAGE=$oldStage
    & subst.exe X: /D | Out-Null
}
