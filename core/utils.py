import asyncio
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

class ServiceError(Exception):
    pass

async def run_subprocess_with_timeout(
    command: list[str],
    timeout_seconds: int,
    shutdown_event: asyncio.Event
) -> tuple[bytes, bytes]:
    """
    Runs a subprocess with a specified timeout and a graceful shutdown event.
    Raises ServiceError on failure/timeout, and CancelledError on shutdown.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    wait_task = asyncio.create_task(process.wait())
    shutdown_task = asyncio.create_task(shutdown_event.wait())

    done, pending = await asyncio.wait(
        {wait_task, shutdown_task},
        timeout=timeout_seconds,
        return_when=asyncio.FIRST_COMPLETED
    )

    for task in pending:
        task.cancel()

    if shutdown_task in done:
        logging.warning(f"Shutdown signal received, terminating process: {' '.join(command)}")
        process.terminate()
        await process.wait()
        raise asyncio.CancelledError()

    if not done:
        logging.error(f"Process timed out after {timeout_seconds}s: {' '.join(command)}")
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            process.kill()
        await process.wait()
        raise ServiceError(f"Process timed out: {' '.join(command)}")

    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        error_message = stderr.decode('utf-8', errors='ignore').strip()
        raise ServiceError(f"Process failed with code {process.returncode}: {' '.join(command)}\n{error_message}")

    return stdout, stderr
