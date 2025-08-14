import asyncio
import logging
import re
import socks
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError, RPCError, ConnectionError,
    PhoneNumberInvalidError, ApiIdInvalidError, AuthKeyError
)
from telethon.sessions import StringSession

class TelegramCollector:
    # Pre-compile the regex for performance
    PROXY_LINK_PATTERN = re.compile(r'\b(?:vless|vmess|ss|ssr|trojan)://[^\s<>"\'`]+')

    def __init__(self, config: dict, stats):
        self.config = config
        self.stats = stats
        self.client: TelegramClient | None = None

    def _ensure_client(self, runtime_proxy: dict | None = None):
        """Initializes the Telegram client with the appropriate proxy setting."""
        proxy_cfg = None
        # Prefer a runtime-provided proxy if given, else use the one from config
        if runtime_proxy and runtime_proxy.get('enabled'):
            proxy_cfg = self._to_pysocks_tuple(runtime_proxy)
        elif self.config.get('proxy', {}).get('enabled'):
            proxy_cfg = self._to_pysocks_tuple(self.config.get('proxy'))

        self.client = TelegramClient(
            StringSession(self.config.get('session_string')), # Use StringSession for easier persistence
            self.config['api_id'],
            self.config['api_hash'],
            proxy=proxy_cfg
        )

    async def collect_links(self, runtime_proxy: dict | None = None, last_progress: dict | None = None) -> tuple[set, dict]:
        """Connects to Telegram and gathers new links from all configured groups."""
        all_new_links = set()
        new_progress: dict = {}
        if self.client is None:
            self._ensure_client(runtime_proxy)

        try:
            async with self.client:
                group_ids = list(self.config['target_groups'])
                prev_progress = last_progress or {}
                tasks = [self._collect_from_one_group(gid, prev_progress.get(gid)) for gid in group_ids]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for i, res in enumerate(results):
                    gid = group_ids[i]
                    if isinstance(res, Exception):
                        logging.error(f"An exception occurred while processing group {gid}: {res}")
                        continue

                    links, latest_id = res
                    all_new_links.update(links)
                    if latest_id is not None:
                        new_progress[gid] = latest_id
        except (PhoneNumberInvalidError, ApiIdInvalidError, AuthKeyError) as e:
            logging.critical(f"Telegram authentication failed: {e}. Please check your api_id, api_hash, and session string.")
        except ConnectionError as e:
            logging.error(f"Failed to connect to Telegram: {e}")

        return all_new_links, new_progress

    async def _collect_from_one_group(self, group_id, since_message_id: int | None = None) -> tuple[set, int | None]:
        """Collects messages from a single group and extracts proxy links."""
        links = set()
        self.stats.increment('groups_processed')
        try:
            entity = await self.client.get_entity(group_id)
            
            fetch_kwargs = {"limit": self.config.get('fetch_chunk_size', 200)}
            if since_message_id:
                fetch_kwargs["min_id"] = since_message_id

            messages = await self.client.get_messages(entity, **fetch_kwargs)
            latest_id = None
            if messages:
                # Filter out None IDs before finding max
                valid_ids = [m.id for m in messages if hasattr(m, 'id') and m.id is not None]
                if valid_ids:
                    latest_id = max(valid_ids)
                links.update(self._extract_proxy_links(messages))

            if links:
                self.stats.increment('links_found_raw', len(links))

        except FloodWaitError as e:
            logging.warning(f"Flood wait error for group {group_id}. Waiting for {e.seconds} seconds.")
            await asyncio.sleep(e.seconds)
            # The operation is not retried automatically here, but the framework could be extended to do so.
        except RPCError as e:
            logging.error(f"A Telegram RPC error occurred for group {group_id}: {e.code} {e.message}")
        except ValueError as e:
            # Catches errors from get_entity if the group_id is invalid
            logging.error(f"Could not find the entity for group {group_id}. Is the ID correct? Error: {e}")

        return links, latest_id
        
    def _extract_proxy_links(self, messages):
        """Extracts proxy links from a list of messages using the pre-compiled regex."""
        links = set()
        for msg in messages:
            if msg and msg.text:
                found = self.PROXY_LINK_PATTERN.findall(msg.text)
                links.update(link.strip('.,') for link in found)
        return links

    def _to_pysocks_tuple(self, proxy_dict: dict):
        """Converts a proxy dictionary to a PySocks-compatible tuple."""
        scheme_map = {
            'socks5': socks.SOCKS5,
            'socks4': socks.SOCKS4,
            'http': socks.HTTP,
        }

        scheme_str = proxy_dict.get('scheme', 'socks5').lower()
        proxy_type = scheme_map.get(scheme_str, socks.SOCKS5)

        host = proxy_dict.get('hostname') or proxy_dict.get('host')
        port = int(proxy_dict.get('port', 1080))
        username = proxy_dict.get('username')
        password = proxy_dict.get('password')

        # PySocks expects rdns to be True for SOCKS proxies if you want remote DNS resolution
        rdns = True if proxy_type in (socks.SOCKS4, socks.SOCKS5) else False

        return (proxy_type, host, port, rdns, username, password)
