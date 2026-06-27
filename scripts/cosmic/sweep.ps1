# Max-out sweep for cosmic Vulkan qwen2.5-VL native 300-DPI transcribe.
# For each (NP, UB): start llama-server, wait for listen, warm (discard), measure, sample VRAM peak, kill.
$ErrorActionPreference = "Continue"
$LIB  = "C:\Users\john\AppData\Local\Programs\Ollama\lib\ollama"
$BLOB = "C:\Users\john\.ollama\models\blobs\sha256-a99b7f834d754b88f122d865f32758ba9f0994a83f8363df2c1e71c17605a025"
$env:GGML_BACKEND_PATH   = "$LIB\vulkan\ggml-vulkan.dll"
$env:GGML_VK_VISIBLE_DEVICES = "0"
$PORT = 18082
$PAGES = "C:\ai\bench_pages"
$RESULTS = "C:\ai\sweep_results.txt"
"config`tpages/min`tgen_t/s`tpeak_VRAM_MB`tfails`tfid`tstatus" | Out-File $RESULTS -Encoding utf8

# (NP, UB) configs to probe. Baseline np3/ub1024 already known ~22.6.
$configs = @(
  @{np=3; ub=2048}, @{np=3; ub=4096},
  @{np=2; ub=4096},
  @{np=4; ub=2048}, @{np=4; ub=4096},
  @{np=6; ub=1024}, @{np=6; ub=2048}
)

function Vram { (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples | Sort-Object CookedValue -Descending | Select-Object -First 1 | ForEach-Object { [math]::Round($_.CookedValue/1MB) } }

foreach ($c in $configs) {
  $np = $c.np; $ub = $c.ub; $ctx = $np * 8192; $tag = "np$np`_ub$ub"
  Write-Host "==== $tag (ctx=$ctx) ===="
  Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 3
  $log = "C:\ai\sweep_$tag.log"
  $args = @("-m",$BLOB,"--mmproj",$BLOB,"-ngl","99","--flash-attn","on","-b",$ub,"-ub",$ub,"-c",$ctx,"--parallel",$np,"--port",$PORT,"--host","127.0.0.1")
  $p = Start-Process -FilePath "$LIB\llama-server.exe" -ArgumentList $args -WindowStyle Hidden -RedirectStandardError $log -RedirectStandardOutput "$log.out" -PassThru
  # wait for listen (or OOM)
  $ready = $false; $oom = $false
  for ($i=0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 3
    if (Test-Path $log) {
      $t = Get-Content $log -Raw -ErrorAction SilentlyContinue
      if ($t -match "server is listening") { $ready = $true; break }
      if ($t -match "OutOfDeviceMemory|failed to|error loading") { $oom = $true; break }
    }
    if ($p.HasExited) { $oom = $true; break }
  }
  if (-not $ready) {
    "$tag`t-`t-`t-`t-`t-`t$(if($oom){'OOM/crash on load'}else{'no-listen timeout'})" | Out-File $RESULTS -Append -Encoding utf8
    Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force; continue
  }
  $workers = [math]::Max(2*$np, 6)
  # warm-up (discarded)
  & python C:\ai\bench.py llamacpp "http://127.0.0.1:$PORT" 0 $PAGES $workers | Out-Null
  # measured run with concurrent VRAM sampling
  $job = Start-Job -ScriptBlock { param($w,$port,$pages) & python C:\ai\bench.py llamacpp "http://127.0.0.1:$port" 0 $pages $w 2>&1 } -ArgumentList $workers,$PORT,$PAGES
  $peak = 0
  while ($job.State -eq "Running") { $v = Vram; if ($v -gt $peak) { $peak = $v }; Start-Sleep -Milliseconds 700 }
  $out = Receive-Job $job; Remove-Job $job
  $summary = ($out | Select-String '^---') -join " "
  # parse "--- N pages in Ts wall | X PAGES/MIN | avg gen Yt/s | fails=Z | avg fid F"
  $pm = if ($summary -match '([\d.]+) PAGES/MIN') { $matches[1] } else { '?' }
  $gn = if ($summary -match 'avg gen ([\d.]+)') { $matches[1] } else { '?' }
  $fl = if ($summary -match 'fails=(\d+)') { $matches[1] } else { '?' }
  $fd = if ($summary -match 'avg fid ([\d.]+)') { $matches[1] } else { '?' }
  $status = if ($peak -gt 15000) { 'OVER 15GB GUARDRAIL' } else { 'ok' }
  "$tag`t$pm`t$gn`t$peak`t$fl`t$fd`t$status" | Out-File $RESULTS -Append -Encoding utf8
  Write-Host "$tag -> $pm pg/min, peak $peak MB, fails=$fl, fid=$fd"
}
Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "SWEEP DONE"
Get-Content $RESULTS
