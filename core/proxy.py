import asyncio
import logging
import os
import shutil
import tempfile


class ServiceError(Exception):
    pass


class InternalProxyManager:
    """Manages a local SOCKS proxy provided by xray-knife using one or more links.

    Starts xray-knife in proxy mode pointing at a temp file of links.
    Keeps the subprocess alive until stop() is called.
    """

    def __init__(self, xray_knife_config: dict, listen_host: str, listen_port: int, extra_args: list[str] | None = None, subcommand: str = 'proxy'):
        self.xray_knife_config = xray_knife_config
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        self.extra_args = extra_args or []
        self.subcommand = subcommand
        self.process: asyncio.subprocess.Process | None = None
        self._links_file: str | None = None

        path = self.xray_knife_config['path']
        if not shutil.which(path):
            raise ServiceError(f"xray-knife binary not found or not executable at path: {path}")

    async def start(self, links: list[str]) -> dict:
        """Starts the proxy process and returns a proxy config dict for clients.

        Returns a dict compatible with the existing Telegram proxy config shape.
        """
        if not links:
            raise ValueError("No links provided to start internal proxy")

        # Prepare temp links file
        fd, links_path = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
        with open(links_path, 'w', encoding='utf-8') as f:
            for link in links:
                f.write(f"{link}\n")
        self._links_file = links_path

        # Build command. We allow users to override/add args via config if needed.
        # Default attempt: `xray-knife proxy -f <file> --port <port>`
        command = [
            self.xray_knife_config['path'],
            self.subcommand,
            '-f',
            links_path,
            '-I',
            f"socks://{self.listen_host}:{self.listen_port}",
        ] + list(self.extra_args)

        logging.info(f"Starting internal proxy via xray-knife on {self.listen_host}:{self.listen_port} using {len(links)} link(s)...")
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Give it a brief moment to start listening
        try:
            await asyncio.wait_for(self._ensure_started(), timeout=5)
        except asyncio.TimeoutError:
            stdout, stderr = await self.process.communicate()
            raise ServiceError(f"Failed to start internal proxy in time. Stderr: {stderr.decode()}\nStdout: {stdout.decode()}")

        # Return a proxy config dict consistent with TelegramCollector expectations
        return {
            'enabled': True,
            'scheme': 'socks5',
            'hostname': self.listen_host,
            'port': self.listen_port,
        }

    async def _ensure_started(self):
        # Naive wait: ensure the process hasn't exited immediately
        await asyncio.sleep(0.5)
        if self.process and self.process.returncode is not None:
            stdout, stderr = await self.process.communicate()
            raise ServiceError(f"Internal proxy process exited early: {self.process.returncode}. Stderr: {stderr.decode()}\nStdout: {stdout.decode()}")

    async def stop(self):
        if self.process:
            try:
                logging.info("Stopping internal proxy...")
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            finally:
                self.process = None
        if self._links_file:
            try:
                os.remove(self._links_file)
            except OSError:
                pass
            self._links_file = None


