---
name: web-fetch
version: 1.0.0
description: Fetch and parse web content using Playwright or requests
task_type: browse
agent: robin
triggers:
  - fetch url
  - browse to
  - scrape page
  - web content
---

# Web Fetch

Retrieve and parse web content for information gathering.

## Capabilities
- HTTP GET/POST via Python requests
- JavaScript-rendered pages via Playwright CDP
- HTML parsing and text extraction
- JSON API calls
- Screenshot capture

## Execution Steps
1. Determine if page needs JS rendering
2. For static: `python -m requests` GET
3. For dynamic: Playwright CDP via `robin_human_adapter.py`
4. Extract content (text, tables, specific selectors)
5. Return structured result

## Tools Available
- Python requests (static pages, APIs)
- Playwright/CDP (dynamic pages via robin_human_adapter)
- EasyOCR (text from screenshots)
- BeautifulSoup (HTML parsing)

## Security Rules
- No credential submission — escalate to Batman
- No form filling with personal data
- Respect robots.txt
- Rate limit: max 1 request/second per domain
- HTTPS preferred, HTTP only with explicit authorization

## Output Format
```json
{
  "url": "",
  "method": "GET|POST",
  "status_code": 200,
  "content_type": "text/html|application/json",
  "title": "",
  "text_content": "",
  "extracted_data": {},
  "screenshot_path": null,
  "status": "success|error|blocked"
}
```
