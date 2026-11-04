param(
    [string]$VivadoBat='D:\FPGA\2026.1\Vivado\bin\vivado.bat',
    [string]$PythonExe='D:\FPGA\2026.1\Vivado\tps\win64\python-3.13.0\python.exe',
    [ValidatePattern('^[A-Z]$')][string]$DriveLetter='V'
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot)
$drive="${DriveLetter}:"
if(Test-Path -LiteralPath "$drive\"){throw "Drive already mapped or occupied: $drive"}
& subst.exe $drive $root
if($LASTEXITCODE -ne 0){throw 'Short path mapping failed'}
$previous=$env:XILINX_LOCAL_USER_DATA
$env:XILINX_LOCAL_USER_DATA='no'
try {
    Push-Location "$drive\"
    try {
        & $PythonExe "$drive\prepare_vivado.py" *> "$drive\evidence\prepare_vivado.log"
        if($LASTEXITCODE -ne 0){throw 'YUYV IP/register preparation failed'}
        & $VivadoBat -mode batch -source "$drive\tcl\build_file_process_yuyv422.tcl" -log "$drive\evidence\vivado_build.log" -nojournal *> "$drive\evidence\vivado_console.log"
        if($LASTEXITCODE -ne 0){throw 'YUYV FPGA implementation failed; see evidence/vivado_console.log'}
        & $PythonExe "$drive\finalize_vivado.py" *> "$drive\evidence\finalize_vivado.log"
        if($LASTEXITCODE -ne 0){throw 'YUYV BIT/HWH/register/timing binding failed'}
    } finally {Pop-Location}
} finally {
    $env:XILINX_LOCAL_USER_DATA=$previous
    & subst.exe $drive /D | Out-Null
}
