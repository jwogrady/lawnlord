param([int]$Seconds = 20, [int]$IntervalMs = 500)
# Samples AMD GPU utilization, dedicated VRAM, and total CPU for $Seconds seconds.
$end = (Get-Date).AddSeconds($Seconds)
$gpuMax = 0.0; $gpuSum = 0.0; $vramMax = 0.0; $cpuSum = 0.0; $n = 0
while ((Get-Date) -lt $end) {
  $eng = (Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples
  $gpu = ($eng | Measure-Object -Property CookedValue -Sum).Sum
  $vram = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples | Measure-Object -Property CookedValue -Maximum).Maximum
  $cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
  if ($gpu -gt $gpuMax) { $gpuMax = $gpu }
  if ($vram -gt $vramMax) { $vramMax = $vram }
  $gpuSum += $gpu; $cpuSum += $cpu; $n++
  Start-Sleep -Milliseconds $IntervalMs
}
if ($n -eq 0) { $n = 1 }
"GPU_util_peak%={0:N0}  GPU_util_avg%={1:N0}  VRAM_peak_MB={2:N0}  CPU_avg%={3:N0}  samples={4}" -f `
  $gpuMax, ($gpuSum/$n), ($vramMax/1MB), ($cpuSum/$n), $n
