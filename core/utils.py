import re
import base64
import json
import logging
from typing import Optional, Dict, Any

def get_flag_emoji(location_name: Optional[str]) -> str:
    """
    Converts a location name into a flag emoji.
    Tries to find a two-letter country code in the string.
    Defaults to the globe emoji if no valid code is found.
    """
    if not location_name:
        return '🌍'

    # Prefer explicit two-letter codes in the text (e.g., "US", "DE").
    match = re.search(r'\b([A-Za-z]{2})\b', location_name)
    code = ''
    if len(location_name) == 2 and location_name.isalpha():
        code = location_name.upper()
    elif match:
        code = match.group(1).upper()

    if code == 'UK':
        code = 'GB'

    if len(code) == 2:
        try:
            # Formula to convert a two-letter country code to regional indicator symbols
            base = 0x1F1E6
            return chr(base + (ord(code[0]) - 65)) + chr(base + (ord(code[1]) - 65))
        except (TypeError, ValueError):
            pass # Fallback if code is not valid

    return '🌍'

def decode_vmess_payload(payload_b64: str) -> Optional[Dict[str, Any]]:
    """
    Decodes a vmess base64 payload into a dictionary.
    It handles different base64 paddings and encodings.
    """
    # Normalize padding and remove whitespace
    normalized_b64 = payload_b64.strip().replace('\n', '').replace('\r', '')
    padding = (-len(normalized_b64)) % 4
    normalized_b64 += ('=' * padding)

    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            decoded_bytes = decoder(normalized_b64)
            data = json.loads(decoded_bytes.decode('utf-8', errors='ignore'))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError, TypeError):
            # Try the next decoder if one fails
            continue

    logging.warning(f"Failed to decode vmess payload: {payload_b64[:30]}...")
    return None
