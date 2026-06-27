param([int]$Seconds = 30)
$end = (Get-Date).AddSeconds($Seconds); $max = 0.0
while ((Get-Date) -lt $end) {
  $v = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -EA SilentlyContinue).CounterSamples | Measure-Object CookedValue -Max).Maximum/1MB
  if ($v -gt $max) { $max = $v }
  Start-Sleep -Milliseconds 250
}
"VRAM_peak_MB={0:N0}" -f $max
