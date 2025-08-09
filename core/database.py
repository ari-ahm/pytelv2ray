# vless_scanner/core/database.py
import aiosqlite
import datetime
import logging

DB_SCHEMA_VERSION = 5

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None

    async def connect(self):
        if self.conn is not None:
            return
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        await self.conn.execute("PRAGMA foreign_keys = ON;")
        await self._migrate_schema()
        logging.info(f"Database connection opened for {self.db_path}")

    async def _migrate_schema(self):
        cursor = await self.conn.execute("PRAGMA user_version")
        current_version = (await cursor.fetchone())[0]
        if current_version >= DB_SCHEMA_VERSION: return
        
        logging.info(f"DB schema version: {current_version}. Migrating to: {DB_SCHEMA_VERSION}")
        if current_version < 5:
            await self._migrate_to_v5()
        
        await self.conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
        await self.conn.commit()

    async def _migrate_to_v5(self):
        logging.info("Applying schema v5: Granular status and speed test tracking")
        # Non-destructive migration
        await self.conn.execute('CREATE TABLE IF NOT EXISTS servers (id INTEGER PRIMARY KEY, link TEXT NOT NULL UNIQUE)')
        await self.conn.execute('CREATE TABLE IF NOT EXISTS group_progress (group_id INTEGER PRIMARY KEY, last_message_id INTEGER NOT NULL)')
        
        # Add columns if they don't exist
        table_info = await self.conn.execute("PRAGMA table_info(servers)")
        columns = [row['name'] for row in await table_info.fetchall()]
        
        if 'status' not in columns: await self.conn.execute("ALTER TABLE servers ADD COLUMN status TEXT")
        if 'delay' not in columns: await self.conn.execute("ALTER TABLE servers ADD COLUMN delay INTEGER")
        if 'download' not in columns: await self.conn.execute("ALTER TABLE servers ADD COLUMN download REAL")
        if 'upload' not in columns: await self.conn.execute("ALTER TABLE servers ADD COLUMN upload REAL")
        if 'location' not in columns: await self.conn.execute("ALTER TABLE servers ADD COLUMN location TEXT")
        if 'last_tested' not in columns: await self.conn.execute("ALTER TABLE servers ADD COLUMN last_tested TIMESTAMP")
        if 'speed_tested_at' not in columns: await self.conn.execute("ALTER TABLE servers ADD COLUMN speed_tested_at TIMESTAMP")
        if 'retry_count' not in columns: await self.conn.execute("ALTER TABLE servers ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")

    async def get_group_progress(self, group_id):
        async with self.conn.execute("SELECT last_message_id FROM group_progress WHERE group_id = ?", (group_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def update_group_progress(self, group_id, message_id):
        await self.conn.execute("INSERT OR REPLACE INTO group_progress (group_id, last_message_id) VALUES (?, ?)", (group_id, message_id))
        await self.conn.commit()

    async def get_links_to_test(self, new_links: set, retest_window_hours: int, max_retries: int) -> set:
        links_to_test = set(new_links)
        now = datetime.datetime.utcnow()
        retest_threshold = now - datetime.timedelta(hours=retest_window_hours)
        query = (
            "SELECT link FROM servers "
            "WHERE (status = 'failed' AND retry_count < ?) "
            "OR (last_tested IS NULL OR last_tested < ?)"
        )
        async with self.conn.execute(query, (max_retries, retest_threshold)) as cursor:
            async for row in cursor:
                links_to_test.add(row[0])
        return links_to_test

    async def save_latency_test_results(self, results: list[dict], max_servers_per_loc: int):
        async with self.conn.execute("BEGIN"):
            for res in results:
                if res.get('status') == 'passed':
                    await self._handle_passed_server(res, max_servers_per_loc)
                else:
                    await self._handle_failed_server(res)
        await self.conn.commit()

    async def _handle_passed_server(self, res: dict, max_per_loc: int):
        location = res.get('location')
        new_delay = int(res.get('delay', 0))
        
        if location:
            # Atomically check count and get the worst server in one go
            query = "SELECT id, delay FROM servers WHERE location = ? AND status != 'failed' ORDER BY delay DESC, last_tested ASC LIMIT 1"
            async with self.conn.execute(query, (location,)) as cursor:
                worst_server = await cursor.fetchone()

            async with self.conn.execute("SELECT COUNT(*) FROM servers WHERE location = ? AND status != 'failed'", (location,)) as cursor:
                loc_count = (await cursor.fetchone())[0]

            if loc_count >= max_per_loc and (not worst_server or new_delay >= worst_server['delay']):
                return # Location is full and this server isn't better than the worst one
            
            if loc_count >= max_per_loc:
                await self.conn.execute("DELETE FROM servers WHERE id = ?", (worst_server['id'],))

        update_query = """
            INSERT INTO servers (link, status, delay, location, last_tested, retry_count) VALUES (?, 'latency_passed', ?, ?, ?, 0)
            ON CONFLICT(link) DO UPDATE SET status='latency_passed', delay=excluded.delay, location=excluded.location, last_tested=excluded.last_tested, retry_count=0;
        """
        await self.conn.execute(update_query, (res['link'], new_delay, location, datetime.datetime.now()))

    async def _handle_failed_server(self, res: dict):
        query = "INSERT INTO servers (link, status, last_tested, retry_count) VALUES (?, 'failed', ?, 1) ON CONFLICT(link) DO UPDATE SET status='failed', last_tested=excluded.last_tested, retry_count=retry_count+1;"
        await self.conn.execute(query, (res['link'], datetime.datetime.now()))

    async def save_speed_test_result(self, result: dict):
        query = "UPDATE servers SET status = 'speed_passed', download = ?, upload = ?, speed_tested_at = ? WHERE link = ?"
        await self.conn.execute(query, (float(result.get('download', 0.0)), float(result.get('upload', 0.0)), datetime.datetime.now(), result['link']))
        await self.conn.commit()

    async def get_servers_for_speedtest(self, max_candidates_per_loc: int) -> dict[str, list[str]]:
        servers_by_location = {}
        query = """
            SELECT location, link FROM (
                SELECT *, ROW_NUMBER() OVER(PARTITION BY location ORDER BY delay ASC) as rn
                FROM servers WHERE status = 'latency_passed' AND location IS NOT NULL AND location != ''
            ) WHERE rn <= ?
        """
        async with self.conn.execute(query, (max_candidates_per_loc,)) as cursor:
            async for row in cursor:
                location, link = row
                if location not in servers_by_location: servers_by_location[location] = []
                servers_by_location[location].append(link)
        return servers_by_location

    async def get_proxy_candidates(self, selector: str = 'speed_passed', max_links: int = 1) -> list[str]:
        """Returns a list of links to be used for running an internal proxy.

        selector:
          - 'speed_passed': prefer servers with recorded download speed, order by download desc
          - 'latency_passed': fall back to latency-passed, order by delay asc
        """
        links: list[str] = []
        if selector == 'speed_passed':
            query = """
                SELECT link FROM servers
                WHERE status = 'speed_passed'
                ORDER BY (download IS NULL) ASC, download DESC, (speed_tested_at IS NULL) ASC, speed_tested_at DESC
                LIMIT ?
            """
            async with self.conn.execute(query, (max_links,)) as cursor:
                async for row in cursor:
                    links.append(row[0])
            if links:
                return links

        # Fallback to latency_passed when no speed_passed found or selector is latency_passed
        query = """
            SELECT link FROM servers
            WHERE status = 'latency_passed'
            ORDER BY (delay IS NULL) ASC, delay ASC, (last_tested IS NULL) ASC, last_tested DESC
            LIMIT ?
        """
        async with self.conn.execute(query, (max_links,)) as cursor:
            async for row in cursor:
                links.append(row[0])
        return links

    async def close(self):
        if self.conn: await self.conn.close()
