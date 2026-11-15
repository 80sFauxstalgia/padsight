# Checks the control panel window's navigation guard (PanelForm.IsOwnUrl) against tricky URLs.
# Usage: powershell -NoProfile -File tools\tests\Test-PanelOrigin.ps1 [-Configuration Debug|Release]
param([string]$Configuration = 'Debug')
$ErrorActionPreference = 'Stop'
$exe = Join-Path $PSScriptRoot "..\..\VSCView\bin\$Configuration\net462\VSCView.exe"
$asm = [Reflection.Assembly]::LoadFrom((Resolve-Path $exe))
$m = $asm.GetType('VSCView.UiForms.PanelForm').GetMethod('IsOwnUrl')
$origin = 'http://127.0.0.1:47817/'

$cases = @(
    @{ url = 'http://127.0.0.1:47817/panel/#k=abc';          expect = $true  },
    @{ url = 'http://127.0.0.1:47817/';                      expect = $true  },
    @{ url = 'http://127.0.0.1:47817@evil.example/';         expect = $false },  # origin as user info
    @{ url = 'http://127.0.0.1:47817@evil.example:47817/';   expect = $false },
    @{ url = 'http://user:pw@127.0.0.1:47817/panel/';        expect = $false },  # any user info is refused
    @{ url = 'http://127.0.0.1:47817.evil.example/';         expect = $false },
    @{ url = 'http://127.0.0.1:47818/panel/';                expect = $false },  # other port
    @{ url = 'https://127.0.0.1:47817/panel/';               expect = $false },  # other scheme
    @{ url = 'http://localhost:47817/panel/';                expect = $false },  # other host name
    @{ url = 'file:///C:/Windows/win.ini';                   expect = $false },
    @{ url = 'javascript:alert(1)';                          expect = $false },
    @{ url = 'not a url';                                    expect = $false }
)

$failed = 0
foreach ($c in $cases) {
    $got = $m.Invoke($null, @($c.url, $origin))
    $ok = $got -eq $c.expect
    if (-not $ok) { $failed++ }
    '{0}  {1,-48} -> {2}' -f ($(if ($ok) { 'PASS' } else { 'FAIL' })), $c.url, $got
}
if ($failed) { throw "$failed case(s) failed" }
'All {0} cases passed.' -f $cases.Count
