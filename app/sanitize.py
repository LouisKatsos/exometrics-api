"""Guards for free-form objects that end up stored in MongoDB."""

MAX_DEPTH = 5


def check_safe_keys(value, depth: int = 0):
    """Raises ValueError if a dict (at any depth) has a key MongoDB could
    treat as an operator or a path: one starting with '$', containing '.',
    or containing a NUL byte. Typed fields never need this; it is for the
    few places that accept an arbitrary object (user preferences)."""
    if depth > MAX_DEPTH:
        raise ValueError(f'nested deeper than {MAX_DEPTH} levels')
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or key.startswith('$') or '.' in key or '\x00' in key:
                raise ValueError('keys must not start with "$" or contain "." or NUL')
            check_safe_keys(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            check_safe_keys(item, depth + 1)
    return value
