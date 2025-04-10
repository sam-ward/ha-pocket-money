# <config>/custom_components/pocket_money/helpers.py
import re

def sanitize_name(name: str) -> str:
    """Generate a safe string for IDs from a name."""
    # Convert to lowercase
    s = name.lower()
    # Remove invalid characters and replace spaces/multiple invalid chars with a single underscore
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    # Remove leading/trailing underscores
    s = s.strip("_")
    # If the name was entirely invalid characters, provide a fallback
    if not s:
        return "pocket_money_item" # Generic fallback
    return s