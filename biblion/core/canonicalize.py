"""Query extraction and tag auto-generation per entry type."""
from __future__ import annotations
import re

# Vocabulary for tag auto-detection
LANGUAGES = [
    "typescript", "javascript", "python", "rust", "go", "java", "bash",
    "shell", "sql", "html", "css", "c++", "c#", "ruby", "php", "swift",
    "kotlin", "scala",
]
FRAMEWORKS = [
    "react", "vue", "angular", "svelte", "next.js", "nuxt", "remix",
    "express", "fastify", "nest", "django", "flask", "fastapi", "rails",
    "spring", "bun", "deno", "node", "tailwind", "prisma", "drizzle",
    "trpc", "graphql",
]
CONCEPTS = [
    "async", "await", "promise", "middleware", "authentication",
    "authorization", "caching", "database", "migration", "schema",
    "websocket", "streaming", "pagination", "validation", "error-handling",
    "routing", "proxy", "crud", "transaction", "hook", "context", "state",
]

_NOISE = re.compile(
    r'\b(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'   # UUID
    r'|ses_[A-Za-z0-9]+'                                                        # session id
    r'|\d{10,}'                                                                 # timestamps
    r'|https?://\S+'                                                            # URLs
    r'|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'                        # emails
    r'|(?:/[\w.-]+){2,}'                                                        # file paths
    r'|\[REDACTED[^\]]*\]'                                                      # redacted markers
    r')\b',
    re.IGNORECASE,
)

_CAMEL = re.compile(r'[A-Z][a-z]+(?:[A-Z][a-z]+)+')
_KEBAB = re.compile(r'\b[a-z]+(?:-[a-z]+)+\b')
_SCREAMING = re.compile(r'\b[A-Z][A-Z0-9_]{3,}\b')


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', _NOISE.sub('', text)).strip()


def _first_sentence(text: str, max_len: int = 100) -> str:
    m = re.search(r'[.!?]', text)
    end = m.start() if m else len(text)
    return text[:min(end, max_len)].strip()


def _first_n_words(text: str, n: int = 6) -> str:
    return ' '.join(text.split()[:n])


def extract_query(content: str, entry_type: str) -> str:
    cleaned = _clean(content)
    if entry_type == "structure":
        tokens = _CAMEL.findall(cleaned)
        return ' '.join(tokens[:6])[:100] or cleaned[:100]
    if entry_type == "pattern":
        tokens = _KEBAB.findall(cleaned)
        return ' '.join(tokens[:6])[:100] or cleaned[:100]
    if entry_type in ("api",):
        tokens = _CAMEL.findall(cleaned) or _KEBAB.findall(cleaned)
        return (' '.join(tokens[:4]) + ' api')[:100]
    if entry_type == "config":
        tokens = _SCREAMING.findall(cleaned)
        return (' '.join(tokens[:4]) + ' config')[:100] or cleaned[:100]
    if entry_type == "dependency":
        # grab first word-like tokens (package names)
        tokens = re.findall(r'[\w@/-]+', cleaned)
        return ' '.join(tokens[:4])[:100]
    # workflow / default
    return _first_n_words(cleaned, 8)[:100] or cleaned[:100]


def extract_tags(content: str, entry_type: str, user_tags: list[str]) -> list[str]:
    lower = content.lower()
    tags: list[str] = [entry_type]
    for word in LANGUAGES + FRAMEWORKS + CONCEPTS:
        if re.search(r'\b' + re.escape(word) + r'\b', lower):
            tags.append(word)
    tags.extend(user_tags)
    # dedup preserving order, limit to 10
    seen: set[str] = set()
    result: list[str] = []
    for t in tags:
        t = t.strip().lower()
        if t and t not in seen:
            seen.add(t)
            result.append(t)
        if len(result) >= 10:
            break
    return result


def canonicalize(content: str, entry_type: str, user_tags: list[str]) -> tuple[str, list[str]]:
    """Return (canonical_query, tags)."""
    query = extract_query(content, entry_type)
    tags = extract_tags(content, entry_type, user_tags)
    return query, tags
