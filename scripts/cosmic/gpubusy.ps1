param([int]$Seconds = 12)
# Fast GPU-only sampler: one counter set, ~10 samples/sec
$end = (Get-Date).AddSeconds($Seconds)
$max = 0.0; $sum = 0.0; $n = 0
while ((Get-Date) -lt $end) {
  $s = (Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples
  $g = ($s | Measure-Object -Property CookedValue -Sum).Sum
  if ($g -gt $max) { $max = $g }
  $sum += $g; $n++
}
if ($n -eq 0) { $n = 1 }
"GPU_util: peak={0:N0}%  avg={1:N0}%  samples={2}" -f $max, ($sum/$n), $n
