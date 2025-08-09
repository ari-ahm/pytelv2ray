# vless_scanner/config.py
import json
import logging
import shutil

class ConfigError(Exception):
    pass

def load_config(path='config.json'):
    """Loads and validates the configuration from a JSON file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Configuration file '{path}' not found.")
    except json.JSONDecodeError:
        raise ConfigError(f"Could not decode '{path}'. Check for syntax errors.")

    # Perform rigorous validation
    try:
        assert config['telegram']['api_hash'] != "YOUR_API_HASH", "Please configure your Telegram api_hash."
        
        if config.get('github_repo', {}).get('enabled'):
            repo_cfg = config['github_repo']
            assert repo_cfg['github_token'] != "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN", "Please configure your GitHub token."
            assert repo_cfg['owner'] != "YOUR_GITHUB_USERNAME", "Please configure your GitHub repository owner."
            assert repo_cfg['repo'] != "YOUR_REPO_NAME", "Please configure your GitHub repository name."

        # Validate that the xray-knife binary is findable
        knife_path = config['xray_knife']['path']
        if not shutil.which(knife_path):
             raise ConfigError(f"xray-knife binary not found or not executable at path: '{knife_path}'. Please check the path or your system's PATH environment variable.")

        assert isinstance(config['database']['max_servers_per_location'], int) and config['database']['max_servers_per_location'] > 0

    except (KeyError, AssertionError) as e:
        raise ConfigError(f"Invalid configuration: {e}")

    return config
