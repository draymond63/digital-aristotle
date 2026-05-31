import re


def normalize_identifier(value: str) -> str:
    """Normalize free text into lowercase snake case."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")


def normalize_list(items: list[str]) -> list[str]:
    """Normalize and dedupe a list of identifiers."""
    normalized = []
    for item in items:
        item = normalize_identifier(item)
        if item and item not in normalized:
            normalized.append(item)
    return normalized
