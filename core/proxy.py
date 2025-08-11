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
        # Wait for process to start and then test connectivity
        await asyncio.sleep(0.5)
        if self.process and self.process.returncode is not None:
            stdout, stderr = await self.process.communicate()
            raise ServiceError(f"Internal proxy process exited early: {self.process.returncode}. Stderr: {stderr.decode()}\nStdout: {stdout.decode()}")
        
        # Test if the proxy is actually working
        if not await self._health_check():
            raise ServiceError("Internal proxy started but failed health check")

    async def _health_check(self, timeout: int = 10) -> bool:
        """Test if the internal proxy is working by making an HTTPS request through it.
        Uses requests with SOCKS support (PySocks). Retries until overall timeout elapses.
        """
        try:
            import time
            import requests
            proxies = {
                'http': f'socks5h://{self.listen_host}:{self.listen_port}',
                'https': f'socks5h://{self.listen_host}:{self.listen_port}',
            }
            deadline = time.monotonic() + max(1, timeout)
            last_error = None
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                per_attempt_timeout = max(1, min(3, int(remaining)))
                try:
                    resp = await asyncio.to_thread(
                        requests.get,
                        'https://1.1.1.1/cdn-cgi/trace',
                        proxies=proxies,
                        timeout=per_attempt_timeout,
                    )
                    if resp.status_code == 200:
                        logging.info("Internal proxy health check passed")
                        return True
                    last_error = f"HTTP {resp.status_code}"
                except Exception as e:
                    last_error = e
                # Small backoff before retrying
                await asyncio.sleep(0.5)
            logging.warning(f"Internal proxy health check failed after {timeout}s: {last_error}")
            return False
        except Exception as e:
            logging.warning(f"Internal proxy health check failed unexpectedly: {e}")
            return False

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


