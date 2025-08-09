# vless_scanner/core/telegram.py
import asyncio
import logging
import re
import socks
from telethon import TelegramClient
from telethon.errors import FloodWaitError

class TelegramCollector:
    def __init__(self, config: dict, stats):
        self.config = config
        self.stats = stats
        self.client: TelegramClient | None = None

    def _ensure_client(self, runtime_proxy: dict | None = None):
        # Prefer a runtime-provided proxy if given, else config's proxy
        proxy_cfg = None
        if runtime_proxy and runtime_proxy.get('enabled'):
            proxy_cfg = self._to_pysocks_tuple(runtime_proxy)
        elif self.config.get('proxy', {}).get('enabled'):
            proxy_cfg = self._to_pysocks_tuple(self.config.get('proxy'))

        self.client = TelegramClient(
            self.config['session_name'],
            self.config['api_id'],
            self.config['api_hash'],
            proxy=proxy_cfg
        )

    async def collect_links(self, runtime_proxy: dict | None = None, last_progress: dict | None = None) -> tuple[set, dict]:
        """Connects to Telegram and gathers new links from all configured groups.

        Returns (links, new_progress)
        """
        all_new_links = set()
        new_progress: dict = {}
        if self.client is None:
            self._ensure_client(runtime_proxy)
        async with self.client:
            group_ids = list(self.config['target_groups'])
            prev = last_progress or {}
            tasks = [self._collect_from_one_group(gid, prev.get(gid)) for gid in group_ids]
            results = await asyncio.gather(*tasks)
            for gid, (links, latest_id) in zip(group_ids, results):
                all_new_links.update(links)
                if latest_id is not None:
                    new_progress[gid] = latest_id
        return all_new_links, new_progress

    async def _collect_from_one_group(self, group_id, since_message_id: int | None = None) -> tuple[set, int | None]:
        links = set()
        self.stats.increment('groups_processed')
        try:
            entity = await self.client.get_entity(group_id)
            # This part is now handled by the database manager, not here
            # We assume we always fetch from the beginning for simplicity in this component
            # The main pipeline will filter based on the database state
            
            # A placeholder for fetching logic, which would be more complex in a real app
            # For now, we'll just fetch the latest messages to avoid full history scans
            # Support progress-aware scanning if the database tracked last_message_id
            # The pipeline will pass this via config override if added in future.
            fetch_kwargs = {"limit": self.config['fetch_chunk_size']}
            if since_message_id:
                fetch_kwargs["min_id"] = since_message_id
            messages = await self.client.get_messages(entity, **fetch_kwargs)
            latest_id = None
            if messages:
                latest_id = max(m.id for m in messages if getattr(m, 'id', None) is not None)
                links.update(self._extract_proxy_links(messages))

            if links:
                self.stats.increment('links_found_raw', len(links))

        except FloodWaitError as e:
            logging.warning(f"Flood wait error for group {group_id}. Waiting for {e.seconds} seconds.")
            await asyncio.sleep(e.seconds)
            # Optionally, you could retry the operation here
        except Exception as e:
            logging.error(f"Failed to collect from group {group_id}: {e}", exc_info=True)
            return links, None
        return links, latest_id
        
    def _extract_proxy_links(self, messages):
        links = set()
        pattern = re.compile(r'\b(?:vless|vmess|ss|ssr|trojan)://[^\s<>"\'`]+')
        for msg in messages:
            if msg and msg.text:
                links.update(link.strip('.,') for link in pattern.findall(msg.text))
        return links

    def _to_pysocks_tuple(self, proxy_dict: dict):
        scheme = proxy_dict.get('scheme', 'socks5').lower()
        host = proxy_dict.get('hostname') or proxy_dict.get('host')
        port = int(proxy_dict.get('port', 1080))
        username = proxy_dict.get('username')
        password = proxy_dict.get('password')
        if scheme == 'socks5':
            return (socks.SOCKS5, host, port, True, username, password)
        if scheme == 'socks4':
            return (socks.SOCKS4, host, port, True, username, password)
        if scheme in ('http', 'https'):
            return (socks.HTTP, host, port, True, username, password)
        return (socks.SOCKS5, host, port)
