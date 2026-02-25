param(
    [string]$PiHost = "192.168.1.47",
    [int]$Port = 1234,
    [string]$CameraName = "",
    [int]$InputFps = 30,
    [int]$OutputFps = 15,
    [int]$Width = 1280,
    [int]$Height = 720,
    [ValidateSet("low-latency", "balanced", "quality")]
    [string]$Profile = "balanced",
    [int]$BitrateKbps = 0,
    [int]$MaxrateKbps = 0,
    [int]$BufsizeKbps = 0,
    [switch]$ListDevices
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-FfmpegPath {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return $cmd.Source
    }

    $candidates = @(
        "$env:ProgramFiles\ffmpeg\bin\ffmpeg.exe",
        "$env:ProgramFiles\FFmpeg\bin\ffmpeg.exe",
        "$env:ProgramFiles(x86)\ffmpeg\bin\ffmpeg.exe",
        "$env:ChocolateyInstall\bin\ffmpeg.exe"
    )

    foreach ($path in $candidates) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            return $path
        }
    }

    throw "ffmpeg introuvable. Installe ffmpeg puis relance."
}

function Get-DshowVideoDevices {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FfmpegPath
    )

    # ffmpeg returns non-zero when listing dshow devices; stderr output is expected.
    $prevErrorActionPreference = $ErrorActionPreference
    $prevNativeCommandPreference = $null
    $hasNativePreference = $false
    try {
        $ErrorActionPreference = "Continue"
        if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
            $hasNativePreference = $true
            $prevNativeCommandPreference = $PSNativeCommandUseErrorActionPreference
            $global:PSNativeCommandUseErrorActionPreference = $false
        }
        $raw = & $FfmpegPath -hide_banner -list_devices true -f dshow -i dummy 2>&1
    } finally {
        $ErrorActionPreference = $prevErrorActionPreference
        if ($hasNativePreference) {
            $global:PSNativeCommandUseErrorActionPreference = $prevNativeCommandPreference
        }
    }
    $lines = @($raw | ForEach-Object { "$_" })
    $videoDevices = New-Object System.Collections.Generic.List[string]

    # Preferred parser: explicit "(video)" marker in ffmpeg dshow output.
    foreach ($line in $lines) {
        if ($line -match '"(.+)"\s+\(video\)') {
            $name = $Matches[1].Trim()
            if ($name.Length -gt 0 -and -not $videoDevices.Contains($name)) {
                [void]$videoDevices.Add($name)
            }
        }
    }

    # Fallback parser: legacy "DirectShow video devices" section.
    if ($videoDevices.Count -eq 0) {
        $inVideoBlock = $false
        foreach ($line in $lines) {
            if ($line -match "DirectShow video devices") {
                $inVideoBlock = $true
                continue
            }
            if ($line -match "DirectShow audio devices") {
                $inVideoBlock = $false
                continue
            }
            if (-not $inVideoBlock) {
                continue
            }
            if ($line -match '"(.+)"') {
                $name = $Matches[1].Trim()
                if ($name.Length -gt 0 -and -not $videoDevices.Contains($name)) {
                    [void]$videoDevices.Add($name)
                }
            }
        }
    }

    return ,@($videoDevices)
}

$ffmpeg = Resolve-FfmpegPath
$devices = @()

if ($ListDevices -or [string]::IsNullOrWhiteSpace($CameraName)) {
    $devices = Get-DshowVideoDevices -FfmpegPath $ffmpeg
}

if ($ListDevices) {
    if (-not $devices -or $devices.Count -eq 0) {
        Write-Host "Aucune camera DirectShow detectee."
        exit 1
    }
    Write-Host "Cameras detectees:"
    foreach ($name in $devices) {
        Write-Host " - $name"
    }
    exit 0
}

if ([string]::IsNullOrWhiteSpace($CameraName)) {
    if (-not $devices -or $devices.Count -eq 0) {
        throw "Aucune camera detectee. Lance d'abord: .\surface_stream.ps1 -ListDevices"
    }
    $CameraName = $devices[0]
}

$gop = [Math]::Max($OutputFps * 2, 8)
$udpUrl = "udp://{0}:{1}?pkt_size=1316" -f $PiHost, $Port
$videoFilter = "scale=$Width`:$Height`:flags=lanczos,fps=$OutputFps,format=yuv420p"
$preset = "veryfast"
$crf = 23
$profileBitrate = 3500
$profileMaxrate = 5000
$profileBufsize = 10000

switch ($Profile) {
    "low-latency" {
        $preset = "ultrafast"
        $crf = 26
        $profileBitrate = 2200
        $profileMaxrate = 3200
        $profileBufsize = 6400
    }
    "quality" {
        $preset = "faster"
        $crf = 21
        $profileBitrate = 5000
        $profileMaxrate = 7000
        $profileBufsize = 14000
    }
    default {
        # balanced
    }
}

if ($BitrateKbps -le 0) {
    $BitrateKbps = $profileBitrate
}
if ($MaxrateKbps -le 0) {
    $MaxrateKbps = $profileMaxrate
}
if ($BufsizeKbps -le 0) {
    $BufsizeKbps = $profileBufsize
}

Write-Host "Didier Surface stream"
Write-Host " ffmpeg : $ffmpeg"
Write-Host " camera : $CameraName"
Write-Host " target : $udpUrl"
Write-Host " format : ${Width}x${Height} @ ${OutputFps}fps"
Write-Host " profile: $Profile (preset=$preset, crf=$crf)"
Write-Host " bitrate: ${BitrateKbps}k max=${MaxrateKbps}k buf=${BufsizeKbps}k"
Write-Host ""
Write-Host "Arret: Ctrl+C"
Write-Host ""

$args = @(
    "-hide_banner",
    "-loglevel", "warning",
    "-fflags", "nobuffer",
    "-flags", "low_delay",
    "-f", "dshow",
    "-rtbufsize", "128M",
    "-framerate", "$InputFps",
    "-i", "video=$CameraName",
    "-an",
    "-vf", $videoFilter,
    "-c:v", "libx264",
    "-preset", $preset,
    "-tune", "zerolatency",
    "-crf", "$crf",
    "-b:v", "${BitrateKbps}k",
    "-maxrate", "${MaxrateKbps}k",
    "-bufsize", "${BufsizeKbps}k",
    "-g", "$gop",
    "-keyint_min", "$gop",
    "-bf", "0",
    "-pix_fmt", "yuv420p",
    "-flush_packets", "1",
    "-muxdelay", "0",
    "-muxpreload", "0",
    "-f", "mpegts",
    $udpUrl
)

& $ffmpeg @args
