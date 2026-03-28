# Claude Command Bridge Runner v2
# Watches ~/claude-commands/ for scripts, executes them, writes results to ~/claude-results/
# v2 adds: per-command timeout (5 minutes), hung process detection, graceful cleanup

$CommandDir = Join-Path $env:USERPROFILE "claude-commands"
$ResultDir  = Join-Path $env:USERPROFILE "claude-results"
$MaxRuntime = 300  # 5 minutes max per command (seconds)
$PollInterval = 2  # Check every 2 seconds

# Create directories
New-Item -ItemType Directory -Force -Path $CommandDir | Out-Null
New-Item -ItemType Directory -Force -Path $ResultDir  | Out-Null

# Log startup
$startupLog = Join-Path $ResultDir "_runner.log"
"Runner v2 started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File $startupLog -Encoding UTF8

# Lock file
$lockFile = Join-Path $CommandDir "_runner.lock"
"PID: $PID" | Out-File $lockFile -Encoding UTF8

while ($true) {
    # Find executable files (not starting with _)
    $files = Get-ChildItem -Path $CommandDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike "_*" -and $_.Extension -in @('.ps1','.cmd','.bat','.py') }

    foreach ($file in $files) {
        $name = $file.Name
        $runningName = "_running_$name"
        $runningPath = Join-Path $CommandDir $runningName
        $resultPath  = Join-Path $ResultDir  "$($file.BaseName).log"

        # Rename to mark as running
        try {
            Rename-Item -Path $file.FullName -NewName $runningName -Force
        } catch {
            continue  # Another instance may have grabbed it
        }

        $startTime = Get-Date
        $result = [PSCustomObject]@{
            File      = $name
            Started   = $startTime.ToString("yyyy-MM-dd HH:mm:ss")
            Elapsed   = ""
            ExitCode  = -1
            Output    = ""
            TimedOut  = $false
        }

        try {
            # Build the command based on extension
            switch ($file.Extension) {
                '.ps1' {
                    $proc = Start-Process -FilePath "powershell.exe" `
                        -ArgumentList "-ExecutionPolicy Bypass -NoProfile -File `"$runningPath`"" `
                        -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\cmd-stdout.tmp" `
                        -RedirectStandardError "$env:TEMP\cmd-stderr.tmp"
                }
                '.cmd' {
                    $proc = Start-Process -FilePath "cmd.exe" `
                        -ArgumentList "/c `"$runningPath`"" `
                        -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\cmd-stdout.tmp" `
                        -RedirectStandardError "$env:TEMP\cmd-stderr.tmp"
                }
                '.bat' {
                    $proc = Start-Process -FilePath "cmd.exe" `
                        -ArgumentList "/c `"$runningPath`"" `
                        -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\cmd-stdout.tmp" `
                        -RedirectStandardError "$env:TEMP\cmd-stderr.tmp"
                }
                '.py' {
                    $proc = Start-Process -FilePath "python.exe" `
                        -ArgumentList "`"$runningPath`"" `
                        -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\cmd-stdout.tmp" `
                        -RedirectStandardError "$env:TEMP\cmd-stderr.tmp"
                }
            }

            # Wait with timeout
            $exited = $proc.WaitForExit($MaxRuntime * 1000)

            if (-not $exited) {
                # TIMEOUT - kill the process tree
                $result.TimedOut = $true
                try {
                    # Kill child processes first
                    Get-CimInstance Win32_Process |
                        Where-Object { $_.ParentProcessId -eq $proc.Id } |
                        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
                    # Kill the main process
                    $proc | Stop-Process -Force -ErrorAction SilentlyContinue
                } catch {}
                $result.ExitCode = -999
                $stdout = if (Test-Path "$env:TEMP\cmd-stdout.tmp") { Get-Content "$env:TEMP\cmd-stdout.tmp" -Raw -ErrorAction SilentlyContinue } else { "" }
                $stderr = "TIMED OUT after $MaxRuntime seconds. Process killed."
                if ($stdout) { $stderr = "$stdout`n`n$stderr" }
                $result.Output = $stderr
            } else {
                $result.ExitCode = $proc.ExitCode
                $stdout = if (Test-Path "$env:TEMP\cmd-stdout.tmp") { Get-Content "$env:TEMP\cmd-stdout.tmp" -Raw -ErrorAction SilentlyContinue } else { "" }
                $stderr = if (Test-Path "$env:TEMP\cmd-stderr.tmp") { Get-Content "$env:TEMP\cmd-stderr.tmp" -Raw -ErrorAction SilentlyContinue } else { "" }
                $result.Output = if ($stderr) { "$stdout`n$stderr" } else { $stdout }
            }

        } catch {
            $result.ExitCode = -1
            $result.Output = "RUNNER ERROR: $_"
        }

        $endTime = Get-Date
        $result.Elapsed = "{0:F2}s" -f ($endTime - $startTime).TotalSeconds

        # Write result log
        $logContent = @"
=== COMMAND RESULT ===
File: $($result.File)
Started: $($result.Started)
Elapsed: $($result.Elapsed)
ExitCode: $($result.ExitCode)
TimedOut: $($result.TimedOut)
=== OUTPUT ===
$($result.Output)
=== END ===
"@
        Set-Content -Path $resultPath -Value $logContent -Encoding UTF8

        # Clean up
        Remove-Item $runningPath -Force -ErrorAction SilentlyContinue
        Remove-Item "$env:TEMP\cmd-stdout.tmp" -Force -ErrorAction SilentlyContinue
        Remove-Item "$env:TEMP\cmd-stderr.tmp" -Force -ErrorAction SilentlyContinue
    }

    # Also check for stale _running_ files (from crashed runs)
    $staleFiles = Get-ChildItem -Path $CommandDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "_running_*" -and $_.LastWriteTime -lt (Get-Date).AddMinutes(-10) }
    foreach ($stale in $staleFiles) {
        $originalName = $stale.Name -replace "^_running_", ""
        $resultPath = Join-Path $ResultDir "$([System.IO.Path]::GetFileNameWithoutExtension($originalName)).log"
        $logContent = @"
=== COMMAND RESULT ===
File: $originalName
Started: unknown
Elapsed: unknown
ExitCode: -998
TimedOut: True
=== OUTPUT ===
STALE: This command was found in _running_ state for over 10 minutes.
It was likely killed by a system restart or the runner crashed during execution.
The _running_ file has been cleaned up.
=== END ===
"@
        Set-Content -Path $resultPath -Value $logContent -Encoding UTF8
        Remove-Item $stale.FullName -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds $PollInterval
}
