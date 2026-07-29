@echo off
REM ==========================================================================
REM 谱渡 Pudu - oemer 补丁 QA 冒烟一键脚本 (Windows)
REM
REM 用法: 双击运行 或 在命令行执行 qa_oemer_patch_smoke.bat
REM
REM 流程:
REM   1. 干净重装 oemer==0.1.8
REM   2. 应用补丁 (install_oemer.py)
REM   3. 逆 apply 确认能还原
REM   4. 再 apply 确认幂等
REM   5. OMR 冒烟 (omr_oemer.py data/river_1.jpg)
REM
REM 详见 docs/oemer-patch-verification.md
REM ==========================================================================

setlocal enabledelayedexpansion

REM --- 定位 Pudu 仓库根目录 ---
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."
pushd "%REPO_ROOT%"
set "REPO_ROOT=%CD%"
popd

REM --- 定位 venv Python ---
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] venv Python 不存在: %PY%
    echo         请按 docs/m2-real-run-guide.md §1.1 创建 venv。
    exit /b 1
)

echo ============================================================
echo  谱渡 Pudu - oemer 补丁 QA 冒烟验证
echo  Python: %PY%
echo  Repo:   %REPO_ROOT%
echo  Time:   %DATE% %TIME%
echo ============================================================
echo.

REM --- 运行验证脚本 ---
"%PY%" "%REPO_ROOT%\tools\verify_oemer_patch.py" --py "%PY%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo ============================================================
if %EXIT_CODE% equ 0 (
    echo  [RESULT] ALL PASS - oemer 补丁验证通过
) else (
    echo  [RESULT] HAS FAILURE - 请检查上方输出
)
echo  Exit code: %EXIT_CODE%
echo ============================================================

exit /b %EXIT_CODE%
