@echo off
REM Cosmic (AMD/Vulkan) qwen2.5-VL vision server via Ollama's bundled llama-server.
REM Usage: serve_vision.cmd [NP] [UBATCH]   e.g. serve_vision.cmd 4 2048
REM Defaults are the benchmarked production point: -np 4 -ub 2048 -> ~24.2 pg/min @ ~11GB.
set NP=%1
if "%NP%"=="" set NP=4
set UB=%2
if "%UB%"=="" set UB=2048
REM total context = 8192 per slot so a native 300-DPI page (~5k img tokens) fits
set /a CTX=%NP%*8192
set OLLAMA_LIB=C:\Users\john\AppData\Local\Programs\Ollama\lib\ollama
set BLOB=C:\Users\john\.ollama\models\blobs\sha256-a99b7f834d754b88f122d865f32758ba9f0994a83f8363df2c1e71c17605a025
set GGML_BACKEND_PATH=%OLLAMA_LIB%\vulkan\ggml-vulkan.dll
set GGML_VK_VISIBLE_DEVICES=0
echo Starting vision server: NP=%NP% UBATCH=%UB% on http://127.0.0.1:18082
"%OLLAMA_LIB%\llama-server.exe" -m "%BLOB%" --mmproj "%BLOB%" ^
  -ngl 99 --flash-attn on -b %UB% -ub %UB% -c %CTX% --parallel %NP% ^
  --port 18082 --host 127.0.0.1
