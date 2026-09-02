# word_release_docx.ps1 - Close a .docx that is open (and unmodified) in the user's
# running Word instance so build_docs.py can overwrite it, or reopen it afterwards.
# Only documents with Saved=True are closed; anything with unsaved edits is left alone
# and reported so no one loses work. Never starts or quits Word itself.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\word_release_docx.ps1 -Path docs\x.docx -Action close
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\word_release_docx.ps1 -Path docs\x.docx -Action reopen
# Exit codes: 0 done / nothing to do, 2 = document has unsaved changes (not closed).
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][ValidateSet('close', 'reopen', 'status')][string]$Action
)
$ErrorActionPreference = 'Stop'
$full = [System.IO.Path]::GetFullPath($Path)
try {
    $word = [Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application')
}
catch {
    Write-Output "no running Word instance"
    exit 0
}
$target = $null
foreach ($d in $word.Documents) {
    if ($d.FullName -ieq $full) { $target = $d }
}
switch ($Action) {
    'status' {
        if ($target -eq $null) { Write-Output "not open" } else { Write-Output ("open, Saved={0}" -f $target.Saved) }
        exit 0
    }
    'close' {
        if ($target -eq $null) { Write-Output "not open in Word"; exit 0 }
        if (-not $target.Saved) { Write-Output "has unsaved changes - not closed"; exit 2 }
        $target.Close(0)   # wdDoNotSaveChanges (document is already saved)
        Write-Output "closed in Word"
        exit 0
    }
    'reopen' {
        if ($target -ne $null) { Write-Output "already open"; exit 0 }
        $doc = $word.Documents.Open($full, $false, $false, $false)
        $doc.Saved = $true   # field refresh on open marks it dirty; nothing was edited
        $word.Visible = $true
        Write-Output "reopened in Word"
        exit 0
    }
}
