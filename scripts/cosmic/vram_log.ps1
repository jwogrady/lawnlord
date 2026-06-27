while ($true) {
  $v = ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -EA SilentlyContinue).CounterSamples | Measure-Object CookedValue -Max).Maximum/1MB
  "{0:N0}" -f $v | Out-File -Append -Encoding ascii C:\ai\vram.log
  Start-Sleep -Milliseconds 250
}
