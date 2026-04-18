"""Credential sanitization — strip secrets before storage."""
import re

# ENV_VAR=secret style
_ENV_SECRET = re.compile(
    r'(?:API_KEY|SECRET(?:_KEY)?|ACCESS_KEY|AUTH_TOKEN|PRIVATE_KEY|'
    r'[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|PASSWD|PWD|CREDENTIAL|CERT|PRIVATE))'
    r'\s*=\s*\S+',
    re.IGNORECASE,
)
# Bearer / Basic tokens
_BEARER = re.compile(r'\bBearer\s+\S{20,}', re.IGNORECASE)
_BASIC = re.compile(r'\bBasic\s+\S{20,}', re.IGNORECASE)
# Long hex strings (32+ chars)
_HEX = re.compile(r'\b[0-9a-fA-F]{32,}\b')
# Long base64 strings (40+ chars, not UUID-like)
_B64 = re.compile(r'[A-Za-z0-9+/]{40,}={0,2}')
# PEM private keys
_PEM = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.DOTALL)


def sanitize(text: str) -> str:
    """Return text with credentials replaced by [REDACTED]."""
    text = _PEM.sub('[REDACTED_PRIVATE_KEY]', text)
    text = _ENV_SECRET.sub(lambda m: m.group(0).split('=')[0] + '=[REDACTED]', text)
    text = _BEARER.sub('Bearer [REDACTED]', text)
    text = _BASIC.sub('Basic [REDACTED]', text)
    text = _HEX.sub('[REDACTED]', text)
    text = _B64.sub('[REDACTED]', text)
    return text
