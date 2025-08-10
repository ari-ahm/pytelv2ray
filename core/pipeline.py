# vless_scanner/core/pipeline.py
import logging
import base64
import shutil
import re
from pathlib import Path
from datetime import datetime
from .proxy import InternalProxyManager

class Pipeline:
    """Orchestrates the entire process from collection to uploading."""
    def __init__(self, config, db, collector, tester, uploader, stats, shutdown_event):
        self.config = config
        self.db = db
        self.collector = collector
        self.tester = tester
        self.uploader = uploader
        self.stats = stats
        self.shutdown_event = shutdown_event

    async def run(self):
        """Executes the main application pipeline."""
        try:
            await self.db.connect()

            runtime_proxy_cfg = None
            proxy_manager = None
            # Optionally start internal proxy
            internal_proxy_cfg = self.config.get('internal_proxy', {})
            if internal_proxy_cfg.get('enabled'):
                logging.info("--- Internal Proxy: Selecting candidates and starting local proxy ---")
                selector = internal_proxy_cfg.get('selector', 'speed_passed')
                max_links = max(1, int(internal_proxy_cfg.get('max_links', 1)))
                listen_host = internal_proxy_cfg.get('listen_host', '127.0.0.1')
                listen_port = int(internal_proxy_cfg.get('listen_port', 1080))
                extra_args = internal_proxy_cfg.get('xray_knife_args', [])

                links = await self.db.get_proxy_candidates(selector=selector, max_links=max_links)
                if links:
                    proxy_manager = InternalProxyManager(self.config['xray_knife'], listen_host, listen_port, extra_args)
                    try:
                        runtime_proxy_cfg = await proxy_manager.start(links)
                    except Exception as e:
                        logging.warning(f"Could not start internal proxy: {e}")
                else:
                    logging.warning("No suitable links found to start internal proxy; proceeding without it.")

            # Determine per-group last progress
            last_progress = {}
            for group_id in self.config['telegram']['target_groups']:
                try:
                    last_id = await self.db.get_group_progress(group_id)
                except Exception:
                    last_id = None
                last_progress[group_id] = last_id

            # Stage 1: Collect new links from Telegram (optionally via internal proxy)
            new_links, new_progress = await self.collector.collect_links(runtime_proxy=runtime_proxy_cfg, last_progress=last_progress)
            if self.shutdown_event.is_set(): return

            # Persist updated group progress
            try:
                for gid, last_msg_id in new_progress.items():
                    if last_msg_id is not None:
                        await self.db.update_group_progress(gid, last_msg_id)
            except Exception as e:
                logging.warning(f"Failed to persist group progress: {e}")

            # Stage 2: Perform latency tests on new and old servers
            await self._perform_latency_tests(new_links)
            if self.shutdown_event.is_set(): return

            # Stage 3: Perform selective speed tests on the best candidates
            final_servers = await self._perform_selective_speed_tests()
            if self.shutdown_event.is_set(): return

            # Stage 4: Upload the final subscription file to a GitHub Repo
            await self._upload_subscription(final_servers)

        finally:
            await self.db.close()
            self._cleanup_xray_knife_db()
            self.stats.print_summary()
            # Ensure proxy is stopped
            try:
                if 'proxy_manager' in locals() and proxy_manager:
                    await proxy_manager.stop()
            except Exception as e:
                logging.warning(f"Error while stopping internal proxy: {e}")

    async def _perform_latency_tests(self, new_links: set):
        logging.info("--- Stage 2: Performing Latency Tests ---")
        db_cfg = self.config['database']
        links_to_test = await self.db.get_links_to_test(new_links, db_cfg['retest_window_hours'], db_cfg['max_retries'])
        
        results = await self.tester.run_test(links_to_test)
        
        await self.db.save_latency_test_results(results, db_cfg['max_servers_per_location'])

    async def _perform_selective_speed_tests(self) -> dict:
        if not self.config.get('speed_test', {}).get('enabled'): return {}
        logging.info("--- Stage 3: Performing Selective Speed Tests ---")
        
        candidates = await self.db.get_servers_for_speedtest(self.config['speed_test']['max_candidates_per_location'])
        if not candidates:
            logging.warning("No latency-passed servers available to speed test.")
            return {}

        all_candidates = {link for links in candidates.values() for link in links}
        speed_test_results = await self.tester.run_test(all_candidates, speed_test=True)
        
        best_servers = {}
        results_map = {res['link']: res for res in speed_test_results if res.get('status') == 'passed'}

        for location, loc_candidates in candidates.items():
            best_for_loc = None
            for link in loc_candidates:
                if link in results_map:
                    result = results_map[link]
                    await self.db.save_speed_test_result(result)
                    # Apply min download threshold if configured
                    min_mbps = float(self.config.get('speed_test', {}).get('min_download_mbps') or 0)
                    if float(result.get('download', 0)) < min_mbps:
                        continue
                    if not best_for_loc or float(result.get('download', 0)) > float(best_for_loc.get('download', 0)):
                        best_for_loc = result
            
            if best_for_loc:
                best_servers[location] = best_for_loc['link']
                self.stats.increment('best_servers_found')
        
        return best_servers

    async def _upload_subscription(self, final_servers: dict):
        if not final_servers or not self.config.get('github_repo', {}).get('enabled'): return
        logging.info("--- Stage 4: Uploading Subscription to GitHub Repo ---")
        
        renamed_links = []
        for location, link in final_servers.items():
            renamed_link = self._rename_link_with_location(link, location)
            renamed_links.append(renamed_link)
        
        sub_content = "\n".join(renamed_links)
        encoded_content = base64.b64encode(sub_content.encode()).decode()
        
        await self.uploader.upload(encoded_content)

    def _cleanup_xray_knife_db(self):
        try:
            knife_db_dir = Path.home() / ".xray-knife"
            if knife_db_dir.exists():
                shutil.rmtree(knife_db_dir)
                logging.info(f"Deleted xray-knife directory: {knife_db_dir}")
        except Exception as e:
            logging.error(f"Could not delete xray-knife directory: {e}")

    def _rename_link_with_location(self, link: str, location: str) -> str:
        """Rename a proxy link with location emoji and last tested timestamp in remarks."""
        # Location to emoji mapping
        location_emojis = {
            'US': '🇺🇸', 'United States': '🇺🇸', 'America': '🇺🇸',
            'UK': '🇬🇧', 'United Kingdom': '🇬🇧', 'England': '🇬🇧',
            'DE': '🇩🇪', 'Germany': '🇩🇪',
            'FR': '🇫🇷', 'France': '🇫🇷',
            'JP': '🇯🇵', 'Japan': '🇯🇵',
            'SG': '🇸🇬', 'Singapore': '🇸🇬',
            'HK': '🇭🇰', 'Hong Kong': '🇭🇰',
            'TW': '🇹🇼', 'Taiwan': '🇹🇼',
            'KR': '🇰🇷', 'South Korea': '🇰🇷', 'Korea': '🇰🇷',
            'AU': '🇦🇺', 'Australia': '🇦🇺',
            'CA': '🇨🇦', 'Canada': '🇨🇦',
            'NL': '🇳🇱', 'Netherlands': '🇳🇱',
            'CH': '🇨🇭', 'Switzerland': '🇨🇭',
            'SE': '🇸🇪', 'Sweden': '🇸🇪',
            'NO': '🇳🇴', 'Norway': '🇳🇴',
            'FI': '🇫🇮', 'Finland': '🇫🇮',
            'DK': '🇩🇰', 'Denmark': '🇩🇰',
            'RU': '🇷🇺', 'Russia': '🇷🇺',
            'CN': '🇨🇳', 'China': '🇨🇳',
            'IN': '🇮🇳', 'India': '🇮🇳',
            'BR': '🇧🇷', 'Brazil': '🇧🇷',
            'MX': '🇲🇽', 'Mexico': '🇲🇽',
            'AR': '🇦🇷', 'Argentina': '🇦🇷',
            'CL': '🇨🇱', 'Chile': '🇨🇱',
            'PE': '🇵🇪', 'Peru': '🇵🇪',
            'CO': '🇨🇴', 'Colombia': '🇨🇴',
            'VE': '🇻🇪', 'Venezuela': '🇻🇪',
            'EG': '🇪🇬', 'Egypt': '🇪🇬',
            'ZA': '🇿🇦', 'South Africa': '🇿🇦',
            'NG': '🇳🇬', 'Nigeria': '🇳🇬',
            'KE': '🇰🇪', 'Kenya': '🇰🇪',
            'MA': '🇲🇦', 'Morocco': '🇲🇦',
            'TR': '🇹🇷', 'Turkey': '🇹🇷',
            'IL': '🇮🇱', 'Israel': '🇮🇱',
            'AE': '🇦🇪', 'UAE': '🇦🇪', 'United Arab Emirates': '🇦🇪',
            'SA': '🇸🇦', 'Saudi Arabia': '🇸🇦',
            'QA': '🇶🇦', 'Qatar': '🇶🇦',
            'KW': '🇰🇼', 'Kuwait': '🇰🇼',
            'BH': '🇧🇭', 'Bahrain': '🇧🇭',
            'OM': '🇴🇲', 'Oman': '🇴🇲',
            'JO': '🇯🇴', 'Jordan': '🇯🇴',
            'LB': '🇱🇧', 'Lebanon': '🇱🇧',
            'SY': '🇸🇾', 'Syria': '🇸🇾',
            'IQ': '🇮🇶', 'Iraq': '🇮🇶',
            'IR': '🇮🇷', 'Iran': '🇮🇷',
            'PK': '🇵🇰', 'Pakistan': '🇵🇰',
            'BD': '🇧🇩', 'Bangladesh': '🇧🇩',
            'LK': '🇱🇰', 'Sri Lanka': '🇱🇰',
            'NP': '🇳🇵', 'Nepal': '🇳🇵',
            'MM': '🇲🇲', 'Myanmar': '🇲🇲',
            'TH': '🇹🇭', 'Thailand': '🇹🇭',
            'VN': '🇻🇳', 'Vietnam': '🇻🇳',
            'PH': '🇵🇭', 'Philippines': '🇵🇭',
            'MY': '🇲🇾', 'Malaysia': '🇲🇾',
            'ID': '🇮🇩', 'Indonesia': '🇮🇩',
            'NZ': '🇳🇿', 'New Zealand': '🇳🇿',
            'Unknown': '🌍', 'Other': '🌍'
        }
        
        # Get emoji for location
        emoji = location_emojis.get(location, '🌍')
        
        # Get last tested timestamp from database
        last_tested = self._get_last_tested_timestamp(link)
        timestamp_str = last_tested.strftime('%Y-%m-%d %H:%M') if last_tested else 'Unknown'
        
        # Create new remarks
        new_remarks = f"{emoji} {location} | Tested: {timestamp_str}"
        
        # Update the link with new remarks
        return self._update_link_remarks(link, new_remarks)

    def _get_last_tested_timestamp(self, link: str) -> datetime | None:
        """Get the last tested timestamp for a link from the database."""
        try:
            # This is a simplified approach - in practice you'd want to make this async
            # and query the database properly
            import sqlite3
            conn = sqlite3.connect(self.config['database']['path'])
            cursor = conn.execute(
                "SELECT speed_tested_at FROM servers WHERE link = ? AND status = 'speed_passed'",
                (link,)
            )
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0]:
                return datetime.fromisoformat(result[0])
            return None
        except Exception:
            return None

    def _update_link_remarks(self, link: str, new_remarks: str) -> str:
        """Update the remarks section of a proxy link (after the #)."""
        # Remove existing remarks if any
        if '#' in link:
            link = link.split('#')[0]
        
        # URL encode the remarks
        import urllib.parse
        encoded_remarks = urllib.parse.quote(new_remarks)
        
        # Add new remarks
        return f"{link}#{encoded_remarks}"
