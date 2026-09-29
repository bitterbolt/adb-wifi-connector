$port = 3000
$root = Get-Location

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $port)
$listener.Start()

Write-Host ""
Write-Host "==========================================="
Write-Host "📁 PowerShell TCP FILE SERVER STARTED"
Write-Host "==========================================="
Write-Host "Root folder: $root"
Write-Host ""

$ips = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {$_.IPAddress -notlike "169.254*" -and $_.IPAddress -ne "127.0.0.1"}).IPAddress

Write-Host "📱 Access from phone:"
foreach ($ip in $ips) {
    Write-Host "   http://$ip`:$port/"
}

Write-Host ""
Write-Host "💻 Local:"
Write-Host "   http://localhost:$port/"
Write-Host "==========================================="
Write-Host ""

while ($true) {

    $client = $listener.AcceptTcpClient()
    $stream = $client.GetStream()

    $reader = New-Object System.IO.StreamReader($stream)
    $requestLine = $reader.ReadLine()

    if (-not $requestLine) {
        $client.Close()
        continue
    }

    $path = ($requestLine.Split(" "))[1]
    $path = [System.Uri]::UnescapeDataString($path.TrimStart('/'))

    if ($path -eq "") { $path = "." }

    $fullPath = Join-Path $root $path

    Write-Host "$(Get-Date -Format HH:mm:ss) $path"

    if (Test-Path $fullPath) {

        if ((Get-Item $fullPath) -is [System.IO.DirectoryInfo]) {

            $files = Get-ChildItem $fullPath

            $html = "<html><body><h2>Index of /$path</h2><ul>"

            if ($path -ne ".") {
                $parent = Split-Path $path -Parent
                $html += "<li><a href='/$parent'>..</a></li>"
            }

            foreach ($f in $files) {

                $name = $f.Name

                if ($path -eq ".") {
                    $href = $name
                } else {
                    $href = "$path/$name"
                }

                $href = $href -replace '\\','/'

                if ($f.PSIsContainer) {
                    $html += "<li>📁 <a href='/$href/'>$name/</a></li>"
                } else {
                    $html += "<li>📄 <a href='/$href'>$name</a></li>"
                }
            }

            $html += "</ul></body></html>"

            $bytes = [Text.Encoding]::UTF8.GetBytes($html)

            $header =
"HTTP/1.1 200 OK
Content-Type: text/html
Content-Length: $($bytes.Length)

"

            $headerBytes = [Text.Encoding]::ASCII.GetBytes($header)

            $stream.Write($headerBytes,0,$headerBytes.Length)
            $stream.Write($bytes,0,$bytes.Length)

        }
        else {

            $bytes = [IO.File]::ReadAllBytes($fullPath)

            $header =
"HTTP/1.1 200 OK
Content-Length: $($bytes.Length)
Content-Type: application/octet-stream

"

            $headerBytes = [Text.Encoding]::ASCII.GetBytes($header)

            $stream.Write($headerBytes,0,$headerBytes.Length)
            $stream.Write($bytes,0,$bytes.Length)

        }

    }
    else {

        $msg = "404 Not Found"
        $bytes = [Text.Encoding]::UTF8.GetBytes($msg)

        $header =
"HTTP/1.1 404 Not Found
Content-Length: $($bytes.Length)

"

        $headerBytes = [Text.Encoding]::ASCII.GetBytes($header)

        $stream.Write($headerBytes,0,$headerBytes.Length)
        $stream.Write($bytes,0,$bytes.Length)
    }

    $stream.Close()
    $client.Close()
}