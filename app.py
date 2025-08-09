# vless_scanner/app.py
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import signal
from config import load_config, ConfigError
from core.pipeline import Pipeline
from core.telegram import TelegramCollector
from core.tester import XrayKnifeTester
from core.database import DatabaseManager
from core.github import GithubUploader
from core.stats import StatsCollector

# --- Graceful Shutdown Handling ---
shutdown_event = asyncio.Event()

def handle_shutdown_signal():
    """Sets the shutdown event when a signal is received."""
    logging.warning("Shutdown signal received. Finishing current tasks...")
    shutdown_event.set()

def setup_logging(config):
    """Initializes the logging configuration."""
    log_level = config.get('logging', {}).get('level', 'INFO').upper()
    log_file = config.get('logging', {}).get('file', 'scanner.log')
    handlers = [logging.StreamHandler()]
    rotate_cfg = config.get('logging', {}).get('rotate', {})
    if rotate_cfg.get('enabled'):
        max_bytes = int(rotate_cfg.get('max_bytes', 5 * 1024 * 1024))
        backups = int(rotate_cfg.get('backup_count', 3))
        handlers.append(RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backups))
    else:
        handlers.append(logging.FileHandler(log_file, mode='a'))

    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s', handlers=handlers)

def main():
    """Initializes and runs the application pipeline."""
    loop = asyncio.get_event_loop()
    
    # Add signal handlers for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown_signal)

    try:
        config = load_config()
        setup_logging(config)

        # --- Dependency Injection ---
        # Each component is created here and passed to the components that need it.
        stats = StatsCollector()
        db = DatabaseManager(config['database']['path'])
        collector = TelegramCollector(config['telegram'], stats)
        tester = XrayKnifeTester(config['xray_knife'], stats, shutdown_event)
        uploader = GithubUploader(config['github_repo'], stats)
        
        pipeline = Pipeline(config, db, collector, tester, uploader, stats, shutdown_event)
        
        loop.run_until_complete(pipeline.run())

    except ConfigError as e:
        logging.critical(f"Configuration failed: {e}")
    except Exception as e:
        logging.critical(f"An unexpected error occurred during startup: {e}", exc_info=True)
    finally:
        logging.info("Application has shut down.")

if __name__ == "__main__":
    main()
