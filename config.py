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
        assert isinstance(config['telegram']['api_id'], int) and config['telegram']['api_id'] > 0, "Please configure a valid Telegram api_id (int)."
        assert config['telegram']['api_hash'] != "YOUR_API_HASH" and isinstance(config['telegram']['api_hash'], str) and len(config['telegram']['api_hash']) > 0, "Please configure your Telegram api_hash."
        assert isinstance(config['telegram']['target_groups'], list) and len(config['telegram']['target_groups']) > 0, "Please provide at least one target group id."
        
        if config.get('github_repo', {}).get('enabled'):
            repo_cfg = config['github_repo']
            # Allow env override
            if repo_cfg.get('github_token') == "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN":
                logging.warning("GitHub token is placeholder; set github_repo.github_token or GITHUB_TOKEN env var.")
            assert repo_cfg['owner'] != "YOUR_GITHUB_USERNAME", "Please configure your GitHub repository owner."
            assert repo_cfg['repo'] != "YOUR_REPO_NAME", "Please configure your GitHub repository name."
            # Optional: upload_base64 flag controls content encoding
            if 'upload_base64' not in repo_cfg:
                repo_cfg['upload_base64'] = False

        # Validate that the xray-knife binary is findable
        knife_path = config['xray_knife']['path']
        if not shutil.which(knife_path):
            raise ConfigError(f"xray-knife binary not found or not executable at path: '{knife_path}'. Please check the path or your system's PATH environment variable.")

        assert isinstance(config['database']['max_servers_per_location'], int) and config['database']['max_servers_per_location'] > 0

        # Optional internal proxy validation
        if config.get('internal_proxy', {}).get('enabled'):
            ip = config['internal_proxy']
            assert isinstance(ip.get('listen_port', 1080), int), "internal_proxy.listen_port must be an int"
            if not isinstance(ip.get('selector', 'speed_passed'), str) or ip['selector'] not in ('speed_passed', 'latency_passed'):
                raise ConfigError("internal_proxy.selector must be 'speed_passed' or 'latency_passed'")
            if not isinstance(ip.get('max_links', 1), int) or ip['max_links'] <= 0:
                raise ConfigError("internal_proxy.max_links must be a positive integer")

    except (KeyError, AssertionError) as e:
        raise ConfigError(f"Invalid configuration: {e}")

    return config
