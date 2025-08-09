# vless_scanner/core/tester.py
import asyncio
import logging
import csv
import os
import tempfile
import shutil

class ServiceError(Exception):
    pass

class XrayKnifeTester:
    def __init__(self, config: dict, stats, shutdown_event: asyncio.Event):
        self.config = config
        self.stats = stats
        self.shutdown_event = shutdown_event
        self._validate_path()

    def _validate_path(self):
        path = self.config['path']
        if not shutil.which(path):
            raise ServiceError(f"xray-knife binary not found or not executable at path: {path}")

    async def run_test(self, links_to_test: set, speed_test=False) -> list[dict]:
        if not links_to_test: return []

        test_args = self.config['test_args'] + ['-x', 'csv']
        if speed_test: test_args.append('-p')

        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as input_f, \
             tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as output_f:
            input_filename, output_filename = input_f.name, output_f.name
            input_f.writelines(f"{link}\n" for link in links_to_test)
            input_f.flush()

        process = None
        try:
            command = [self.config['path'], 'http', '-f', input_filename, '-o', output_filename] + test_args
            logging.info(f"Executing xray-knife (Speedtest: {speed_test}) on {len(links_to_test)} links...")
            
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            # Wait for the process to complete or for a shutdown signal
            wait_task = asyncio.create_task(process.wait())
            shutdown_task = asyncio.create_task(self.shutdown_event.wait())
            
            done, pending = await asyncio.wait(
                {wait_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED
            )

            if shutdown_task in done:
                logging.warning("Shutdown signal received, terminating xray-knife process...")
                process.terminate()
                await process.wait()
                # Cancel the process wait task to avoid a warning
                wait_task.cancel()
                raise asyncio.CancelledError()

            # If we are here, the process finished on its own
            shutdown_task.cancel() # Clean up the shutdown watcher

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise ServiceError(f"xray-knife failed. Stderr:\n{stderr.decode()}")

            with open(output_filename, 'r', encoding='utf-8') as f:
                return list(csv.DictReader(f))
        
        finally:
            if process and process.returncode is None:
                process.terminate() # Ensure cleanup on unexpected exit
                await process.wait()
            os.remove(input_filename)
            os.remove(output_filename)
