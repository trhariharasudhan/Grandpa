"""Source verification engine for domain trust, official recognition, and ranking."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from grandpa.browser_intelligence.models import (
    ConfidenceLevel,
    SearchEngineResult,
    SourceVerificationResult,
)

# Strict official domain registry (exact domain or validated parent domain)
_KNOWN_OFFICIAL_DOMAINS: dict[str, tuple[str, ...]] = {
    "fastapi": ("fastapi.tiangolo.com", "tiangolo.com"),
    "python": ("docs.python.org", "python.org", "pypi.org"),
    "raspberry pi": (
        "raspberrypi.com",
        "raspberrypi.org",
        "documentation.raspberrypi.com",
    ),
    "jetson": ("nvidia.com", "developer.nvidia.com", "docs.nvidia.com"),
    "nvidia": ("nvidia.com", "developer.nvidia.com", "docs.nvidia.com"),
    "windows": ("microsoft.com", "learn.microsoft.com", "support.microsoft.com"),
    "microsoft": ("microsoft.com", "learn.microsoft.com", "support.microsoft.com"),
    "mdn": ("developer.mozilla.org",),
    "javascript": ("developer.mozilla.org", "tc39.es"),
    "typescript": ("typescriptlang.org",),
    "node": ("nodejs.org", "docs.nodejs.org"),
    "react": ("react.dev", "legacy.reactjs.org"),
    "rust": ("rust-lang.org", "doc.rust-lang.org", "crates.io"),
    "docker": ("docker.com", "docs.docker.com"),
    "git": ("git-scm.com", "github.com"),
}

_HIGH_TRUST_TLDS = (".gov", ".edu", ".org")
_LOW_TRUST_PATTERNS = (
    r"\bseo\b",
    r"\baffiliate\b",
    r"\bspam\b",
    r"\bad\b",
    r"\bsponsored\b",
    r"clickbait",
    r"blogspot\.com",
    r"wordpress\.com",
    r"fake",
    r"example\.com",
)


def extract_domain(url_or_domain: str) -> str:
    """Extract clean domain name from URL or string."""
    if not url_or_domain:
        return ""
    val = url_or_domain.strip().lower()
    if "://" in val:
        try:
            parsed = urlparse(val)
            val = parsed.netloc or parsed.path
        except Exception:
            pass
    # Strip port if any
    val = val.split(":")[0].split("/")[0]
    if val.startswith("www."):
        val = val[4:]
    return val


def compute_domain_trust_score(domain: str) -> float:
    """Compute base trust score for a domain (0.0 to 1.0)."""
    clean = extract_domain(domain)
    if not clean:
        return 0.1

    score = 0.6  # Default baseline for standard web domains

    # Check high-trust TLDs
    if any(clean.endswith(tld) for tld in _HIGH_TRUST_TLDS):
        score += 0.25

    # Check if domain matches known official registry
    if any(
        _domain_matches_official(clean, off_dom)
        for sublist in _KNOWN_OFFICIAL_DOMAINS.values()
        for off_dom in sublist
    ):
        score += 0.25

    # Check low trust patterns
    for pat in _LOW_TRUST_PATTERNS:
        if re.search(pat, clean):
            score -= 0.4

    return max(0.0, min(1.0, score))


def _domain_matches_official(candidate_domain: str, official_domain: str) -> bool:
    """Check if candidate domain is exact or a strict validated subdomain of official domain."""
    cand = extract_domain(candidate_domain)
    off = extract_domain(official_domain)

    if not cand or not off:
        return False

    # Reject lookalikes (e.g. fastapi-tiangolo.example.com vs tiangolo.com)
    if cand == off or cand.endswith("." + off):
        return True

    return False


def is_official_domain(url_or_domain: str, subject: str = "") -> bool:
    """Determine if a domain/URL is official for a given target subject."""
    clean_domain = extract_domain(url_or_domain)
    if not clean_domain:
        return False

    raw_subj = subject.strip().lower()

    # Remove noise words from subject
    subj_clean = re.sub(
        r"\b(official|docs|documentation|site|guide|page|tutorial|search|result|results)\b",
        "",
        raw_subj,
    ).strip()
    if not subj_clean:
        subj_clean = raw_subj

    # Direct check against known official map
    for key, official_domains in _KNOWN_OFFICIAL_DOMAINS.items():
        if key == subj_clean or key in subj_clean or subj_clean in key:
            for official_dom in official_domains:
                if _domain_matches_official(clean_domain, official_dom):
                    return True

    # General heuristic match for exact subject slug matching
    clean_subj_slug = re.sub(r"[^\w]", "", subj_clean)
    if clean_subj_slug and len(clean_subj_slug) >= 3:
        # Require exact domain prefix or subdomain match (e.g. fastapi.org, docs.fastapi.com)
        if (
            clean_domain == f"{clean_subj_slug}.org"
            or clean_domain == f"{clean_subj_slug}.dev"
            or clean_domain == f"{clean_subj_slug}.io"
        ):
            return True
        if clean_domain.startswith(f"{clean_subj_slug}.") or clean_domain.startswith(
            f"docs.{clean_subj_slug}."
        ):
            return True

    return False


def verify_source(url: str, subject: str = "") -> SourceVerificationResult:
    """Verify a source URL against target subject and return structured verification result."""
    domain = extract_domain(url)

    if not url or not domain:
        return SourceVerificationResult(
            url="",
            domain="",
            is_official=False,
            trust_score=0.0,
            official_score=0.0,
            confidence="Low",
            reasoning="Cannot verify the current source because no verified browser URL is available.",
            target_subject=subject,
        )

    official = is_official_domain(url, subject)
    trust = compute_domain_trust_score(domain)
    official_score = 0.95 if official else (0.65 if trust >= 0.8 else 0.3)

    if official:
        confidence: ConfidenceLevel = "High"
        reasoning = f"Verified as official primary domain ({domain})."
    elif trust >= 0.7:
        confidence = "Medium"
        reasoning = f"Reputable community or third-party source ({domain})."
    else:
        confidence = "Low"
        reasoning = f"Unverified third-party source ({domain}). Exercise caution."

    return SourceVerificationResult(
        url=url,
        domain=domain,
        is_official=official,
        trust_score=trust,
        official_score=official_score,
        confidence=confidence,
        reasoning=reasoning,
        target_subject=subject,
    )


def rank_search_results(
    results: list[SearchEngineResult],
    subject: str = "",
) -> list[SearchEngineResult]:
    """Rank search results based on domain trust, official score, and search position."""
    scored_results: list[tuple[float, SearchEngineResult]] = []

    for item in results:
        verification = verify_source(item.url or item.domain, subject=subject)
        position_penalty = (item.ranking - 1) * 0.05
        composite_score = (
            (0.55 * verification.official_score)
            + (0.35 * verification.trust_score)
            - position_penalty
        )

        ranked_item = SearchEngineResult(
            title=item.title,
            url=item.url,
            snippet=item.snippet,
            domain=verification.domain,
            ranking=item.ranking,
            engine=item.engine,
            trust_score=verification.trust_score,
            official_score=verification.official_score,
            confidence=verification.confidence,
            is_official=verification.is_official,
        )
        scored_results.append((composite_score, ranked_item))

    scored_results.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored_results]
