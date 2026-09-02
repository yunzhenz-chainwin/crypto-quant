# update_docx_fields.ps1 - Use Microsoft Word (COM) to update every field in a .docx
# (table of contents page numbers, PAGE / NUMPAGES) and save it in place.
# Called by scripts/build_docs.py; can also be run by hand:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update_docx_fields.ps1 -Path docs\crypto-quant_交接手冊.docx
# ASCII only (see docs handbook ch.10 "雷區" about .cmd/.ps1 encodings).
param(
    [Parameter(Mandatory = $true)][string]$Path
)
$ErrorActionPreference = 'Stop'
$full = (Resolve-Path -LiteralPath $Path).Path
$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles)
    $doc = $word.Documents.Open($full, $false, $false, $false)
    # Update fields twice: first pass builds the TOC, second pass settles
    # page numbers that shift once the TOC itself takes up pages.
    for ($pass = 0; $pass -lt 2; $pass++) {
        [void]$doc.Fields.Update()
        foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
        # Force pagination so NUMPAGES/PAGE in footers are current.
        [void]$doc.Repaginate()
    }
    $doc.Save()
    $pages = $doc.ComputeStatistics(2)   # wdStatisticPages = 2
    Write-Output ("updated fields: {0} ({1} pages)" -f (Split-Path $full -Leaf), $pages)
}
finally {
    if ($doc -ne $null) { $doc.Close($true) }
    if ($word -ne $null) { $word.Quit() }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
