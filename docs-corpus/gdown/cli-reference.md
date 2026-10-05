usage: gdown [-h] [-V] [-O OUTPUT] [-q] [--proxy PROXY] [--speed SPEED]
             [--cookies FILE] [--cookies-from-browser BROWSER] [--no-cookies]
             [--no-check-certificate] [--continue] [--retries N] [--folder]
             [--json] [--format FORMAT] [--user-agent USER_AGENT]
             [--timeout SECONDS]
             url_or_id

positional arguments:
  url_or_id             url or file/folder id to download from

options:
  -h, --help            show this help message and exit
  -V, --version         display version (default: None)
  -O, --output OUTPUT   output file name/path; end with "/" to create a new
                        directory (default: None)
  -q, --quiet           suppress logging except errors (default: False)
  --proxy PROXY         <protocol://host:port> download using the specified
                        proxy (default: None)
  --speed SPEED         download speed limit in second (e.g., '10MB' ->
                        10MB/s) (default: None)
  --cookies FILE        Netscape cookies file to read cookies from and save
                        them to (default: ~/.cache/gdown/cookies.txt)
  --cookies-from-browser BROWSER
                        copy your Google cookies from this browser into the
                        cookies file, so this and later runs download as your
                        signed-in account. One of: brave, chrome, chromium,
                        edge, firefox, opera, safari, vivaldi, whale (default:
                        None)
  --no-cookies          don't read or save cookies (default: False)
  --no-check-certificate
                        don't check the server's TLS certificate (default:
                        False)
  --continue, -c        resume getting partially-downloaded files while
                        skipping fully downloaded ones (default: False)
  --retries N           retry transient failures up to N times per file,
                        resuming the current transfer; use --continue to
                        resume earlier downloads and skip completed files
                        (filesystem destinations only; excludes --json and
                        folder discovery) (default: 0)
  --folder              download a folder by ID (folder URLs are detected
