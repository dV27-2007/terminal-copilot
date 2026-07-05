# terminal-copilot PowerShell integration
# MVP: Ctrl+F requests one local suggestion and inserts it into PSReadLine.

if ($script:TermCopilotPowerShellLoaded) {
    return
}
$script:TermCopilotPowerShellLoaded = $true

function Get-TermCopilotHttpUrl {
    param(
        [switch]$RequireExplicit
    )

    if (-not [string]::IsNullOrWhiteSpace($env:TERM_COPILOT_HTTP_URL)) {
        return $env:TERM_COPILOT_HTTP_URL.TrimEnd("/")
    }
    if (-not [string]::IsNullOrWhiteSpace($env:TERM_COPILOT_URL)) {
        return $env:TERM_COPILOT_URL.TrimEnd("/")
    }
    if ($RequireExplicit) {
        return $null
    }
    return "http://127.0.0.1:8765"
}

function Get-TermCopilotTimeoutSeconds {
    $value = $env:TERM_COPILOT_TIMEOUT
    if ([string]::IsNullOrWhiteSpace($value)) {
        return 1
    }

    try {
        $seconds = [double]::Parse($value, [Globalization.CultureInfo]::InvariantCulture)
        if ($seconds -le 0) {
            return 1
        }
        return [Math]::Max(1, [int][Math]::Ceiling($seconds))
    } catch {
        return 1
    }
}

function Test-TermCopilotAdmin {
    if ($env:TERM_COPILOT_ROOT_MODE -eq "1") {
        return $true
    }

    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Get-TermCopilotUserName {
    if (-not [string]::IsNullOrWhiteSpace($env:USERNAME)) {
        return $env:USERNAME
    }
    if (-not [string]::IsNullOrWhiteSpace($env:USER)) {
        return $env:USER
    }
    return $null
}

function Get-TermCopilotCurrentDirectory {
    try {
        $location = Get-Location
        if ($location.ProviderPath) {
            return $location.ProviderPath
        }
        return $location.Path
    } catch {
        return $null
    }
}

function New-TermCopilotPredictionPayload {
    param(
        [Parameter(Mandatory = $true)][string]$Buffer,
        [Parameter(Mandatory = $true)][int]$Cursor
    )

    $rootMode = [bool](Test-TermCopilotAdmin)
    $version = $null
    $edition = $null
    try {
        $version = $PSVersionTable.PSVersion.ToString()
        $edition = $PSVersionTable.PSEdition
    } catch {
        $version = $null
        $edition = $null
    }

    [ordered]@{
        protocol_version = 1
        buffer = $Buffer
        cursor = $Cursor
        cwd = (Get-TermCopilotCurrentDirectory)
        shell = "powershell"
        user = (Get-TermCopilotUserName)
        effective_uid = $null
        original_user = $(if ($env:TERM_COPILOT_USER) { $env:TERM_COPILOT_USER } else { Get-TermCopilotUserName })
        term_copilot_home = $env:TERM_COPILOT_HOME
        root_mode = $rootMode
        admin = $rootMode
        shell_version = $version
        shell_edition = $edition
    }
}

function Invoke-TermCopilotJsonPost {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)]$Payload
    )

    try {
        $requireExplicit = $false
        if ($null -ne $Payload -and $null -ne $Payload.root_mode) {
            $requireExplicit = [bool]$Payload.root_mode
        }
        $baseUrl = Get-TermCopilotHttpUrl -RequireExplicit:$requireExplicit
        if ([string]::IsNullOrWhiteSpace($baseUrl)) {
            return $null
        }

        $body = $Payload | ConvertTo-Json -Depth 8 -Compress
        $uri = "$baseUrl$Endpoint"
        Invoke-RestMethod `
            -Uri $uri `
            -Method Post `
            -ContentType "application/json" `
            -Body $body `
            -TimeoutSec (Get-TermCopilotTimeoutSeconds) `
            -ErrorAction Stop
    } catch {
        return $null
    }
}

function Invoke-TermCopilotPrediction {
    param(
        [Parameter(Mandatory = $true)][string]$Buffer,
        [Parameter(Mandatory = $true)][int]$Cursor
    )

    $payload = New-TermCopilotPredictionPayload -Buffer $Buffer -Cursor $Cursor
    Invoke-TermCopilotJsonPost -Endpoint "/predict" -Payload $payload
}

function Test-TermCopilotCandidateText {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate
    )

    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        return $false
    }
    if ($Candidate -match "(```|\r|\n)") {
        return $false
    }
    if ($Candidate -match "^\s*(Here is|Here are|Explanation:|```)" ) {
        return $false
    }
    return $true
}

function Get-TermCopilotSuggestionSuffix {
    param(
        [Parameter(Mandatory = $true)][string]$Buffer,
        $Response
    )

    if ($null -eq $Response) {
        return $null
    }

    $risk = [string]$Response.risk
    if ($risk -eq "dangerous") {
        return $null
    }

    $ghostText = [string]$Response.ghost_text
    $fullCommand = [string]$Response.full_command
    $source = [string]$Response.source

    if (-not [string]::IsNullOrEmpty($ghostText)) {
        $candidate = "$Buffer$ghostText"
        if (([string]::IsNullOrEmpty($fullCommand) -or $fullCommand -eq $candidate) -and
            (Test-TermCopilotCandidateText -Candidate $candidate)) {
            return [pscustomobject]@{
                Suffix = $ghostText
                FullCommand = $candidate
                Source = $source
            }
        }
    }

    if (-not [string]::IsNullOrEmpty($fullCommand) -and $fullCommand.StartsWith($Buffer)) {
        $suffix = $fullCommand.Substring($Buffer.Length)
        if (-not [string]::IsNullOrEmpty($suffix) -and (Test-TermCopilotCandidateText -Candidate $fullCommand)) {
            return [pscustomobject]@{
                Suffix = $suffix
                FullCommand = $fullCommand
                Source = $source
            }
        }
    }

    return $null
}

function Send-TermCopilotAcceptedEvent {
    param(
        [Parameter(Mandatory = $true)][string]$Suggestion,
        [string]$Source,
        [string]$Buffer
    )

    try {
        $rootMode = [bool](Test-TermCopilotAdmin)
        $payload = [ordered]@{
            event = "suggestion_accepted"
            suggestion = $Suggestion
            source = $Source
            buffer = $Buffer
            cwd = (Get-TermCopilotCurrentDirectory)
            shell = "powershell"
            root_mode = $rootMode
            admin = $rootMode
            user = (Get-TermCopilotUserName)
            original_user = $(if ($env:TERM_COPILOT_USER) { $env:TERM_COPILOT_USER } else { Get-TermCopilotUserName })
            term_copilot_home = $env:TERM_COPILOT_HOME
        }
        $null = Invoke-TermCopilotJsonPost -Endpoint "/events" -Payload $payload
    } catch {
        return
    }
}

function Get-TermCopilotReadLineState {
    try {
        $line = $null
        $cursor = 0
        [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
        if ($null -eq $line) {
            return $null
        }
        [pscustomobject]@{
            Line = [string]$line
            Cursor = [int]$cursor
        }
    } catch {
        return $null
    }
}

function Invoke-TermCopilotSuggestion {
    try {
        $state = Get-TermCopilotReadLineState
        if ($null -eq $state) {
            return
        }

        $line = [string]$state.Line
        $cursor = [int]$state.Cursor
        if ($cursor -ne $line.Length) {
            return
        }
        if ($line.Length -lt 2) {
            return
        }

        $response = Invoke-TermCopilotPrediction -Buffer $line -Cursor $cursor
        $suggestion = Get-TermCopilotSuggestionSuffix -Buffer $line -Response $response
        if ($null -eq $suggestion -or [string]::IsNullOrEmpty($suggestion.Suffix)) {
            return
        }

        [Microsoft.PowerShell.PSConsoleReadLine]::Insert($suggestion.Suffix)
        Send-TermCopilotAcceptedEvent -Suggestion $suggestion.FullCommand -Source $suggestion.Source -Buffer $line
    } catch {
        return
    }
}

function Register-TermCopilotKeyBinding {
    try {
        if (Get-Command Set-PSReadLineKeyHandler -ErrorAction SilentlyContinue) {
            Set-PSReadLineKeyHandler `
                -Chord "Ctrl+f" `
                -ScriptBlock { Invoke-TermCopilotSuggestion } `
                -BriefDescription "TerminalCopilotSuggestion" `
                -Description "Insert a terminal-copilot suggestion without executing it"
        }
    } catch {
        return
    }
}

Register-TermCopilotKeyBinding
