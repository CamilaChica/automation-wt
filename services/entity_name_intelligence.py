"""
entity_name_intelligence.py
===========================
Shared intelligence utility for high-accuracy client (customer) and supplier
name identification, cleaning, domain resolution, and quality scoring.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Common generic email local-parts that represent roles or mailboxes, NOT customer or company names
GENERIC_MAILBOX_LOCALPARTS = {
    "procurement", "purchasing", "buyer", "buyers", "sales", "inside.sales", "insidesales",
    "quotes", "quote", "rfq", "rfqs", "orders", "order", "info", "information",
    "support", "admin", "administrator", "help", "helpdesk", "contact", "parts",
    "inventory", "billing", "accounting", "operations", "ops", "logistics",
    "shipping", "team", "customer.service", "customerservice", "cs", "inquiry",
    "inquiries", "general", "mail", "postmaster", "webmaster", "office", "desk",
    "distrib", "distribution", "spares", "store", "dept", "department",
}

# Artifacts, chatter phrases, or noise that must never be treated as company or client names
NOISE_PHRASES = {
    "good afternoon", "good morning", "good day", "good evening", "hello",
    "dear sales", "dear customer", "dear all", "dear team", "dear sir", "dear madam",
    "please find", "please review", "please see", "please quote", "see attached",
    "attached quote", "quote attached", "attached is", "attached file", "thank you",
    "thanks & regards", "thanks and regards", "best regards", "kind regards",
    "warm regards", "sincerely", "regards", "follow up", "followup",
    "status update", "order update", "quote request", "request for quotation",
    "part number", "part no", "unit price", "lead time", "be careful",
    "manage digest", "all info is inside", "urgent requirement", "aog requirement",
    "customer portal", "winged tycoons", "winged tycoons sales team", "internal inventory",
    "unknown", "unknown supplier", "unknown customer", "not available", "none", "n/a",
}

# Corporate legal designators and aviation industry indicators
CORPORATE_INDICATORS = {
    "llc", "l.l.c.", "inc", "inc.", "corp", "corp.", "corporation", "ltd", "ltd.",
    "limited", "gmbh", "s.a.", "co.", "co", "company", "plc", "sa", "ag", "bv",
}

AVIATION_INDUSTRY_WORDS = {
    "aerospace", "aviation", "aero", "airways", "airlines", "airline", "spares",
    "components", "parts", "supply", "supplies", "technik", "mro", "systems",
    "technologies", "tech", "trading", "distribution", "international", "global",
    "logistics", "defense", "defence", "services", "dynamics", "air", "materials",
    "flight", "avionics", "rotables", "overhaul", "turbines", "propulsion",
}

# Known acronyms that should be kept in uppercase
ACRONYMS = {"LLC", "CORP", "LTD", "GMBH", "MRO", "FAA", "EASA", "AOG", "OEM", "USA", "UK"}

# Domain word tokens for compound domain splitting
DOMAIN_WORD_TOKENS = sorted(
    [
        "aerospace", "aviation", "aero", "spares", "components", "parts", "supply",
        "technik", "systems", "tech", "trading", "direct", "defense", "logistics",
        "airways", "airlines", "airline", "global", "materials", "services", "rotables",
        "mro", "air", "star", "delta", "apex", "vanguard", "wyatt", "precision",
        "premier", "united", "american", "pacific", "atlantic", "international",
        "national", "spartanaero", "summit", "velocity", "allied", "horizon",
        "innovation", "eagle", "falcon", "phoenix", "dynamic", "universal",
    ],
    key=len,
    reverse=True,
)


def is_generic_mailbox(local_part: str) -> bool:
    """Return True if local part is a generic role rather than a personal or brand name."""
    if "@" in (local_part or ""):
        local_part = (local_part or "").split("@", 1)[0]
    raw = (local_part or "").lower().strip()
    tokens = [t for t in re.split(r"[\s._\-]+", raw) if t]
    if tokens and all(t in GENERIC_MAILBOX_LOCALPARTS for t in tokens):
        return True
    cleaned = re.sub(r"[^a-z0-9.]", "", raw)
    cleaned_no_dot = cleaned.replace(".", "")
    return cleaned in GENERIC_MAILBOX_LOCALPARTS or cleaned_no_dot in GENERIC_MAILBOX_LOCALPARTS


def is_garbage_name(name: str) -> bool:
    """Return True if the candidate name is empty, an email, a domain, or noise."""
    if not name or not isinstance(name, str):
        return True
    cleaned = name.strip()
    lowered = cleaned.lower()
    if len(cleaned) < 2 or len(cleaned) > 80:
        return True
    if "@" in cleaned:
        return True
    # Domain suffixes like foo.com, foo.aero, foo.net
    if re.search(r"\.[a-z]{2,6}$", lowered):
        return True
    # Noise phrases check
    if lowered in NOISE_PHRASES:
        return True
    if any(lowered.startswith(phrase) for phrase in ("good afternoon", "good morning", "dear ", "please ", "attached ", "see attached", "hello ", "hi ")):
        return True
    if "winged tycoons" in lowered or "internal inventory" in lowered:
        return True
    # Numbers only or mostly symbols
    alphanumeric = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
    if not alphanumeric or alphanumeric.isdigit():
        return True
    letters_count = len(re.findall(r"[a-zA-Z]", cleaned))
    if letters_count < 2:
        return True
    return False


def clean_company_name(name: str) -> str:
    """Standardize whitespace, punctuation, quotes, and acronym casing for company names."""
    if not name or is_garbage_name(name):
        return ""
    cleaned = re.sub(r"\s+", " ", name).strip(" \t-:;|\"'#<>")
    # Remove leading greetings or prefixes
    cleaned = re.sub(r"^(?:company|company\s*name|supplier|vendor|client|customer)\s*[:\-]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.split(r"\s+(?:for|re:?|regarding)\s+(?:rfq|quote|p/?n|po)\b", cleaned, flags=re.IGNORECASE)[0].strip(" \t-:;|\"'#")
    if is_garbage_name(cleaned):
        return ""

    is_all_caps = cleaned.isupper()
    words = cleaned.split()
    formatted = []
    for word in words:
        # Match leading punctuation, core word, trailing punctuation
        m = re.match(r"^([^a-zA-Z0-9]*)(.*?)([^a-zA-Z0-9]*)$", word)
        prefix, core, suffix = m.groups() if m else ("", word, "")
        upper_core = core.upper()

        if upper_core in ACRONYMS:
            formatted.append(f"{prefix}{upper_core}{suffix}")
        elif upper_core == "INC":
            formatted.append(f"{prefix}Inc{suffix}")
        elif is_all_caps:
            # For ALL CAPS names (e.g. "DELTA MRO INC.")
            if upper_core in ACRONYMS:
                formatted.append(f"{prefix}{upper_core}{suffix}")
            else:
                formatted.append(f"{prefix}{core.capitalize()}{suffix}")
        elif cleaned.islower():
            formatted.append(f"{prefix}{core.capitalize()}{suffix}")
        else:
            formatted.append(word)

    result = " ".join(formatted).strip(" \t-:;|\"'")
    return result if not is_garbage_name(result) else ""


def clean_person_name(name: str) -> str:
    """Clean and extract a personal contact name (e.g. 'Sandy Delgado')."""
    if not name or is_garbage_name(name):
        return ""
    cleaned = re.sub(r"\s+", " ", name).strip(" \t-:;,.|\"'#<>")
    cleaned = re.sub(r"^(?:contact|contact\s*name|customer\s*name|name)\s*[:\-]\s*", "", cleaned, flags=re.IGNORECASE)
    # Strip parentheticals like "(Purchasing)" or "(Sales)"
    cleaned = re.sub(r"\s*\([^)]*\)", "", cleaned).strip()
    # Strip quoted nicknames like 'Bob' or "Bob"
    cleaned = re.sub(r"\s*['\"].*?['\"]\s*", " ", cleaned).strip()
    # Strip title / role if appended with pipe, hyphen, comma, e.g. "Sandy Delgado - Purchasing"
    cleaned = re.split(r"\s*[-–—|,]\s*(?:purchasing|buyer|sales|procurement|manager|lead|director|vp|inside|president)\b", cleaned, flags=re.IGNORECASE)[0].strip()
    if is_garbage_name(cleaned):
        return ""
    # Person names should typically not have corporate suffixes
    words = cleaned.split()
    if len(words) > 4:
        return ""
    if any(w.lower().strip(".,") in CORPORATE_INDICATORS for w in words):
        return ""
    return cleaned.title() if cleaned.isupper() or cleaned.islower() else cleaned


def split_compound_domain(domain_token: str) -> str:
    """
    Intelligently split a domain token into words.
    e.g. 'wyattaerospace' -> 'Wyatt Aerospace'
         'apexaero' -> 'Apex Aero'
         'deltamro' -> 'Delta MRO'
         'vanguardspares' -> 'Vanguard Spares'
    """
    raw = domain_token.lower().replace("-", " ").replace("_", " ").strip()
    # Check if hyphens or spaces were already present
    if " " in raw:
        words = raw.split()
        return " ".join("MRO" if w == "mro" else w.capitalize() for w in words)

    # Attempt prefix/suffix splitting with known aviation vocabulary
    for token in DOMAIN_WORD_TOKENS:
        if raw.endswith(token) and len(raw) > len(token):
            prefix = raw[:-len(token)].strip()
            if len(prefix) >= 2:
                prefix_clean = "MRO" if prefix == "mro" else prefix.capitalize()
                token_clean = "MRO" if token == "mro" else token.capitalize()
                return f"{prefix_clean} {token_clean}"
        if raw.startswith(token) and len(raw) > len(token):
            suffix = raw[len(token):].strip()
            if len(suffix) >= 2:
                token_clean = "MRO" if token == "mro" else token.capitalize()
                suffix_clean = "MRO" if suffix == "mro" else suffix.capitalize()
                return f"{token_clean} {suffix_clean}"

    # Default fallback: title case
    return raw.capitalize()


def derive_company_from_domain(email_or_domain: str) -> str:
    """Extract and intelligently format a company name from an email domain."""
    if not email_or_domain:
        return ""
    domain = email_or_domain.split("@", 1)[-1] if "@" in email_or_domain else email_or_domain
    domain = domain.split(".", 1)[0].lower().strip("<> ")
    generic_domains = {
        "gmail", "yahoo", "hotmail", "outlook", "aol", "icloud", "mail",
        "live", "msn", "comcast", "verizon", "sbcglobal", "partsbase",
        "ilsmart", "wingedtycoons",
    }
    if not domain or domain in generic_domains:
        return ""
    return split_compound_domain(domain)


def name_quality_score(name: str, email: Optional[str] = None) -> int:
    """
    Return a quality score (0 to 100) for a candidate company name:
    0   = Garbage, empty, email address, noise greeting, or wingedtycoons
    10  = Generic role words (e.g. 'Sales Team', 'Procurement')
    20  = Single token or domain fallback (e.g. 'Apexaero')
    50  = Clean multi-word name (e.g. 'Apex Aero')
    80  = Multi-word with aviation or corporate keywords (e.g. 'Wyatt Aerospace')
    100 = Full legal corporate name with entity suffix (e.g. 'Apex Aero Components LLC')
    """
    if not name or is_garbage_name(name):
        return 0
    cleaned = clean_company_name(name)
    if not cleaned:
        return 0
    if is_generic_mailbox(cleaned):
        return 10
    words = [w.lower().strip(".,") for w in cleaned.split()]
    has_corporate = any(w in CORPORATE_INDICATORS for w in words)
    has_aviation = any(w in AVIATION_INDUSTRY_WORDS for w in words)

    score = 20
    if has_corporate and (has_aviation or len(words) >= 3):
        score = 100
    elif has_corporate:
        score = 90
    elif has_aviation and len(words) >= 2:
        score = 80
    elif len(words) >= 2:
        score = 50

    if email:
        domain = email.split("@", 1)[-1].split(".", 1)[0].lower() if "@" in email else ""
        if domain and len(domain) >= 3 and domain in cleaned.lower().replace(" ", ""):
            score = min(100, score + 10)

    return score


def extract_company_from_signature(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Intelligently inspect sign-offs (Regards, Sincerely, Thanks) and following lines
    to extract (contact_person, company_name).
    """
    signoff_pattern = re.compile(
        r"(?:thanks\s*(?:&|and)?\s*regards|best\s*regards|kind\s*regards|warm\s*regards|regards|sincerely|thank\s*you)[,!\s]*\n+([^\n]+(?:\n+[^\n]+){1,5})",
        re.IGNORECASE,
    )
    match = signoff_pattern.search(text)
    if not match:
        return None, None

    lines = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    if not lines:
        return None, None

    contact_person: Optional[str] = None
    company_name: Optional[str] = None

    for idx, line in enumerate(lines[:4]):
        if is_garbage_name(line) or any(char in line for char in ("@", "http", "www.", "+", "tel:", "phone:")):
            continue
        cleaned_company = clean_company_name(line)
        cleaned_person = clean_person_name(line)
        # Check if line looks like a company
        words = [w.lower().strip(".,") for w in line.split()]
        has_corp = any(w in CORPORATE_INDICATORS for w in words)
        has_avi = any(w in AVIATION_INDUSTRY_WORDS for w in words)

        if (has_corp or has_avi) and not company_name and len(words) >= 2:
            company_name = cleaned_company
        elif not contact_person and cleaned_person and len(words) <= 3 and not (has_corp or has_avi):
            contact_person = cleaned_person

    return contact_person, company_name
