import asyncio
import logging
import csv
import os
import tempfile
import shutil
from .utils import run_subprocess_with_timeout, ServiceError

class XrayKnifeTester:
    def __init__(self, config: dict, stats, shutdown_event: asyncio.Event):
        self.config = config
        self.stats = stats
        self.shutdown_event = shutdown_event
        self._validate_path()

    def _validate_path(self):
        """Ensures the configured xray-knife path is a valid executable."""
        path = self.config.get('path')
        if not path or not shutil.which(path):
            raise ServiceError(f"xray-knife binary not found or not executable at path: {path}")

    async def run_test(self, links_to_test: set, speed_test: bool = False) -> list[dict]:
        """
        Runs a test on a set of links using xray-knife.

        Args:
            links_to_test: A set of proxy links to test.
            speed_test: Whether to perform a speed test or a latency test.

        Returns:
            A list of dictionaries, where each dictionary represents a test result from the CSV output.
        """
        if not links_to_test:
            return []

        # Prepare arguments for xray-knife
        test_args = list(self.config.get('test_args', [])) + ['-x', 'csv']
        if speed_test:
            test_args.append('-p')
        elif self.config.get('latency_url'):
            test_args.extend(['-u', self.config['latency_url']])

        timeout = int(self.config.get('timeout_seconds', 300))

        # Create temporary files for input and output
        input_fd, input_path = tempfile.mkstemp(suffix='.txt', text=True)
        output_fd, output_path = tempfile.mkstemp(suffix='.csv', text=True)

        try:
            # Write links to the input file
            with os.fdopen(input_fd, 'w') as f:
                f.writelines(f"{link}\n" for link in links_to_test)

            command = [self.config['path'], 'http', '-f', input_path, '-o', output_path] + test_args
            logging.info(f"Executing xray-knife (Speedtest: {speed_test}) on {len(links_to_test)} links...")

            await run_subprocess_with_timeout(command, timeout, self.shutdown_event)

            # Read the results from the output file
            with os.fdopen(output_fd, 'r', encoding='utf-8') as f:
                # Filter out empty lines that might be at the end of the file
                non_empty_lines = (line for line in f if line.strip())
                return list(csv.DictReader(non_empty_lines))

        except ServiceError as e:
            logging.error(f"Test failed: {e}")
            return []
        except asyncio.CancelledError:
            logging.warning("Test run was cancelled due to shutdown signal.")
            return []
        finally:
            # Ensure temporary files are cleaned up
            os.close(output_fd) # Close the file descriptor for output_path
            os.remove(input_path)
            os.remove(output_path)
