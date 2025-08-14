import json
import logging
import shutil
from pathlib import Path

class ConfigError(Exception):
    pass

def _get_nested(config: dict, path: str):
    """Safely retrieve a nested value from a dictionary using dot notation."""
    keys = path.split('.')
    value = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value

def _validate_config(config: dict):
    """
    Performs rigorous validation of the configuration dictionary.
    Raises ConfigError if validation fails.
    """
    # --- Telegram Validation ---
    if not isinstance(_get_nested(config, 'telegram.api_id'), int) or _get_nested(config, 'telegram.api_id') <= 0:
        raise ConfigError("Please configure a valid Telegram api_id (positive integer).")
    if _get_nested(config, 'telegram.api_hash') in (None, "YOUR_API_HASH"):
        raise ConfigError("Please configure your Telegram api_hash.")
    if not isinstance(_get_nested(config, 'telegram.target_groups'), list) or not _get_nested(config, 'telegram.target_groups'):
        raise ConfigError("Please provide at least one target group ID in telegram.target_groups.")

    # --- GitHub Repo Validation (optional section) ---
    if _get_nested(config, 'github_repo.enabled'):
        if _get_nested(config, 'github_repo.github_token') == "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN":
            logging.warning("GitHub token is a placeholder; set github_repo.github_token or GITHUB_TOKEN env var.")
        if _get_nested(config, 'github_repo.owner') in (None, "YOUR_GITHUB_USERNAME"):
            raise ConfigError("Please configure your GitHub repository owner in github_repo.owner.")
        if _get_nested(config, 'github_repo.repo') in (None, "YOUR_REPO_NAME"):
            raise ConfigError("Please configure your GitHub repository name in github_repo.repo.")

    # --- Xray-Knife Validation ---
    knife_path_str = _get_nested(config, 'xray_knife.path')
    if not knife_path_str:
        raise ConfigError("xray_knife.path is a required setting.")
    if not shutil.which(knife_path_str):
        raise ConfigError(f"xray-knife binary not found or not executable at path: '{knife_path_str}'. Check the path and permissions.")

    latency_url = _get_nested(config, 'xray_knife.latency_url')
    if latency_url is not None and not isinstance(latency_url, str):
        raise ConfigError("xray_knife.latency_url must be a string if provided.")

    # --- Database Validation ---
    max_servers = _get_nested(config, 'database.max_servers_per_location')
    if not isinstance(max_servers, int) or max_servers <= 0:
        raise ConfigError("database.max_servers_per_location must be a positive integer.")

    # --- Internal Proxy Validation (optional section) ---
    if _get_nested(config, 'internal_proxy.enabled'):
        selector = _get_nested(config, 'internal_proxy.selector')
        if selector not in ('speed_passed', 'latency_passed'):
            raise ConfigError("internal_proxy.selector must be 'speed_passed' or 'latency_passed'.")

        max_links = _get_nested(config, 'internal_proxy.max_links')
        if not isinstance(max_links, int) or max_links <= 0:
            raise ConfigError("internal_proxy.max_links must be a positive integer.")

def load_config(path: str = 'config.json') -> dict:
    """Loads and validates the configuration from a JSON file."""
    config_file = Path(path)
    if not config_file.is_file():
        raise ConfigError(f"Configuration file '{path}' not found.")

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Could not decode '{path}'. Check for syntax errors: {e}")

    try:
        _validate_config(config)
    except (KeyError, TypeError, AssertionError) as e:
        # Catching broader errors during validation and wrapping them
        raise ConfigError(f"Invalid configuration: {e}")

    return config
