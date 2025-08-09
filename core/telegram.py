# vless_scanner/core/telegram.py
import asyncio
import logging
import re
from telethon import TelegramClient
from telethon.errors import FloodWaitError

class TelegramCollector:
    def __init__(self, config: dict, stats):
        self.config = config
        self.stats = stats
        self.client = TelegramClient(
            config['session_name'],
            config['api_id'],
            config['api_hash'],
            proxy=config.get('proxy') if config.get('proxy', {}).get('enabled') else None
        )

    async def collect_links(self) -> set:
        """Connects to Telegram and gathers new links from all configured groups."""
        all_new_links = set()
        async with self.client:
            tasks = [self._collect_from_one_group(group_id) for group_id in self.config['target_groups']]
            for link_set in await asyncio.gather(*tasks):
                all_new_links.update(link_set)
        return all_new_links

    async def _collect_from_one_group(self, group_id) -> set:
        links = set()
        self.stats.increment('groups_processed')
        try:
            entity = await self.client.get_entity(group_id)
            # This part is now handled by the database manager, not here
            # We assume we always fetch from the beginning for simplicity in this component
            # The main pipeline will filter based on the database state
            
            # A placeholder for fetching logic, which would be more complex in a real app
            # For now, we'll just fetch the latest messages to avoid full history scans
            messages = await self.client.get_messages(entity, limit=self.config['fetch_chunk_size'])
            if messages:
                links.update(self._extract_proxy_links(messages))

            if links:
                self.stats.increment('links_found_raw', len(links))

        except FloodWaitError as e:
            logging.warning(f"Flood wait error for group {group_id}. Waiting for {e.seconds} seconds.")
            await asyncio.sleep(e.seconds)
            # Optionally, you could retry the operation here
        except Exception as e:
            logging.error(f"Failed to collect from group {group_id}: {e}", exc_info=True)
        return links
        
    def _extract_proxy_links(self, messages):
        links = set()
        pattern = re.compile(r'\b(?:vless|vmess|ss|ssr|trojan)://[^\s<>"\'`]+')
        for msg in messages:
            if msg and msg.text:
                links.update(link.strip('.,') for link in pattern.findall(msg.text))
        return links
