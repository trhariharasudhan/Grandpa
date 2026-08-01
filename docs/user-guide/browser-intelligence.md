# Grandpa Browser Intelligence V1 User Guide

Grandpa Browser Intelligence V1 elevates Grandpa from basic browser opening and searching into a fully intelligent browser agent capable of page understanding, official-source verification, section-focused content extraction, smart navigation, local summarization, product/spec comparison, bounded web research, planner integration, and voice/CLI operation.

---

## Architecture

```
User Goal (CLI / Voice / Plan)
          ↓
  Executive Planner
          ↓
  Browser Intelligence Engine
    ├── Page Understanding (Reader & Analyzer)
    ├── Official Source Verification (Domain Trust)
    ├── Targeted Content Extraction (Section-focused)
    ├── Smart Navigator (Vision & DOM Resolution)
    ├── Local Summarizer (Ollama / Bounded Heuristics)
    ├── Product Comparison Engine
    └── Bounded Web Research Mode
          ↓
  Session Memory Context
          ↓
Voice / CLI Output
```

---

## Capabilities

### 1. Page Understanding
Parses and structures visible webpage components into standardized `PageContent` models:
- Page Title, URL, Domain
- Headings (`h1`–`h6`)
- Paragraphs
- Actionable Buttons & Navigation Sections
- Forms & Non-sensitive Input Fields
- Structured Tables & Lists
- Code Snippets with syntax context
- Search Engine Results (Google, Bing, DuckDuckGo, Brave)

### 2. Official Source Verification
Evaluates web sources before claiming authority:
- **Official Domain Matching**: Direct mapping for top documentation & project sites (`fastapi.tiangolo.com`, `docs.python.org`, `developer.mozilla.org`, `raspberrypi.com`, `nvidia.com`, `microsoft.com`).
- **Domain Trust Scoring**: Trust scores based on TLDs (`.gov`, `.edu`, `.org`), SSL/domain patterns, and historical reputation.
- **Source Confidence Levels**: Categorizes sources into `High` (Official/Primary), `Medium` (Reputable Community), and `Low` (Unverified/Third-party).

### 3. Content Extraction
Extracts only requested target sections:
- **Installation**: Quickstart steps, installation commands (`pip install`, `npm install`).
- **Requirements**: System prerequisites, Python/Node versions, dependencies.
- **Pricing**: Plans, cost tiers, billing terms.
- **Product Specs**: Hardware specs (CPU, RAM, Power, Storage).
- **Code Snippets**: Formatted code blocks.
- **FAQs & Tables**: Comparison and Q&A structures.

### 4. Smart Navigation
Resolves semantic user goals into navigation actions:
- Open official docs for topic
- Navigate to "Installation" section
- Scroll until "Requirements" heading appears
- Open first verified official search result

### 5. Local Summarization
Uses Grandpa's local model infrastructure (Ollama or local bounded heuristics):
- **Summary Types**: `short`, `detailed`, `bullet`, `technical`, `installation`, `requirements`, `research`.
- **Bounded Tokens**: Strictly limits token consumption per summary.
- **Prompt-Injection Safe**: Webpage text is sanitized against untrusted instructions.

### 6. Comparison Engine
Generates side-by-side structured comparisons between products, services, or frameworks:
- Attributes matrix: CPU, RAM, Storage, Power, Price.
- Pros & Cons breakdown for each item.
- Executive summary.

### 7. Bounded Web Research Mode
Orchestrates multi-page web research workflows:
1. Search query
2. Collect & rank search results by trust score
3. Filter & verify official sources
4. Extract section content from top pages
5. Deduplicate key findings
6. Summarize results into a comprehensive report
- **Bounds**: Enforces maximum sources, maximum pages, max content size, and timeout limits.

---

## CLI Reference

```bash
# Read current browser page
grandpa browser page

# Analyze page structure and search results
grandpa browser analyze

# Extract specific section (e.g. installation, specs, code)
grandpa browser extract installation

# Verify domain trust & official status
grandpa browser verify https://fastapi.tiangolo.com --subject fastapi

# Summarize page
grandpa browser summarize --type short

# Compare two products or technologies
grandpa browser compare "Raspberry Pi 5" "Jetson Nano"

# Perform bounded web research
grandpa browser research "FastAPI" --max-sources 5 --max-pages 3

# View session history and active tab context
grandpa browser history
grandpa browser context
```

---

## Voice Commands

- *"Grandpa, what page is this?"*
- *"Grandpa, summarize this page."*
- *"Grandpa, read installation steps."*
- *"Grandpa, open official FastAPI docs."*
- *"Grandpa, compare Raspberry Pi 5 and Jetson Nano."*

---

## Safety Model & Constraints

1. **Blocked Operations**: Never automatically purchase, login, submit forms, download files, execute webpage code, or install software without explicit user confirmation.
2. **Untrusted Data Isolation**: Webpage content is treated strictly as data, never as system instructions. Prompt injection attempts inside webpages are automatically neutralized (`[UNTRUSTED_INSTRUCTION_REMOVED]`).
3. **Privacy**: Cookies, authorization headers, passwords, and private browser profiles are never read or exposed.
4. **Session-Only Memory**: Memory is strictly in-memory per session with no cross-session web tracking.
