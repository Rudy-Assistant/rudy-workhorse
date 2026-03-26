# ══════════════════════════════════════════════════════════
#  Rudy Empowerment Script
#  Installs everything a claude -p session needs to be
#  actually useful: document creation, web research,
#  image handling, data processing, browser automation.
# ══════════════════════════════════════════════════════════

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  RUDY EMPOWERMENT — Installing Capability Libraries ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Document Creation ──────────────────────────────────
Write-Host "[1/6] Document creation libraries..." -ForegroundColor Yellow
pip install --break-system-packages python-pptx   # PowerPoint
pip install --break-system-packages python-docx    # Word documents
pip install --break-system-packages openpyxl       # Excel spreadsheets
pip install --break-system-packages reportlab      # PDF creation
pip install --break-system-packages PyPDF2         # PDF manipulation
pip install --break-system-packages markdown       # Markdown processing

# ── Image & Media ──────────────────────────────────────
Write-Host "[2/6] Image and media libraries..." -ForegroundColor Yellow
pip install --break-system-packages Pillow         # Image processing
pip install --break-system-packages svgwrite       # SVG creation
pip install --break-system-packages qrcode         # QR codes
pip install --break-system-packages cairosvg       # SVG to PNG/PDF

# ── Web & Research ─────────────────────────────────────
Write-Host "[3/6] Web research libraries..." -ForegroundColor Yellow
pip install --break-system-packages requests       # HTTP requests
pip install --break-system-packages beautifulsoup4 # HTML parsing
pip install --break-system-packages lxml           # Fast XML/HTML parser
pip install --break-system-packages feedparser     # RSS feeds
pip install --break-system-packages httpx          # Async HTTP

# ── Data Processing ────────────────────────────────────
Write-Host "[4/6] Data processing libraries..." -ForegroundColor Yellow
pip install --break-system-packages pandas         # Data analysis
pip install --break-system-packages matplotlib     # Charts/graphs
pip install --break-system-packages tabulate       # Pretty tables
pip install --break-system-packages pyyaml         # YAML parsing
pip install --break-system-packages jinja2         # Templating

# ── Email (for Rudy listener) ─────────────────────────
Write-Host "[5/6] Email libraries..." -ForegroundColor Yellow
pip install --break-system-packages imapclient     # IMAP (already installed)

# ── Browser Automation ─────────────────────────────────
Write-Host "[6/6] Browser automation (Playwright)..." -ForegroundColor Yellow
pip install --break-system-packages playwright
python -m playwright install chromium

# ── Verify ─────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  VERIFICATION                                       ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Green

$libs = @(
    "pptx", "docx", "openpyxl", "reportlab", "PyPDF2",
    "PIL", "requests", "bs4", "pandas", "matplotlib",
    "playwright", "jinja2", "yaml", "markdown"
)

$passed = 0
$failed = 0

foreach ($lib in $libs) {
    $result = python -c "import $lib" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $lib" -ForegroundColor Green
        $passed++
    } else {
        Write-Host "  [FAIL] $lib" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Host "  Passed: $passed / $($passed + $failed)" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Yellow" })

if ($failed -eq 0) {
    Write-Host ""
    Write-Host "  ALL LIBRARIES INSTALLED — Rudy is armed." -ForegroundColor Green
    Write-Host "  claude -p sessions can now create:" -ForegroundColor Green
    Write-Host "    - PowerPoint presentations (.pptx)" -ForegroundColor White
    Write-Host "    - Word documents (.docx)" -ForegroundColor White
    Write-Host "    - Excel spreadsheets (.xlsx)" -ForegroundColor White
    Write-Host "    - PDFs (.pdf)" -ForegroundColor White
    Write-Host "    - Charts and images (.png, .svg)" -ForegroundColor White
    Write-Host "    - Web research via Playwright" -ForegroundColor White
    Write-Host "    - Data analysis with pandas" -ForegroundColor White
}

Write-Host ""
Write-Host "Done. Press any key to close." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
