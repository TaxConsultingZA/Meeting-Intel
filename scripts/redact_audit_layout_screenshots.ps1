Add-Type -AssemblyName System.Drawing
$evidenceRoot = Join-Path $PSScriptRoot '../artifacts/processing-audit-layout-live'
Get-ChildItem -LiteralPath $evidenceRoot -Filter '*-redactions.json' | ForEach-Object {
    $stem = $_.Name.Replace('-redactions.json','')
    $rawPath = Join-Path $env:TEMP "audit-layout-$stem.png"
    if (Test-Path -LiteralPath $rawPath) {
        $sourceImage = [System.Drawing.Image]::FromFile($rawPath)
        $bitmap = [System.Drawing.Bitmap]::new($sourceImage)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(219,227,236))
        $cssWidth = if ($stem.Contains('mobile')) { 390 } else { 1280 }
        $scale = 1 # Browser screenshots use CSS pixels and omit the browser scrollbar.
        $boxes = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
        foreach ($box in $boxes) {
            $graphics.FillRectangle($brush, [single]([Math]::Max(0,$box.x*$scale-2)), [single]([Math]::Max(0,$box.y*$scale-24)), [single]($box.width*$scale+42), [single]($box.height*$scale+30))
        }
        $bitmap.Save((Join-Path $evidenceRoot "$stem.png"), [System.Drawing.Imaging.ImageFormat]::Png)
        Write-Output "$stem : $($bitmap.Width)x$($bitmap.Height), $($boxes.Count) redactions"
        $brush.Dispose(); $graphics.Dispose(); $bitmap.Dispose(); $sourceImage.Dispose()
    }
}
