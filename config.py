import os
import json
import subprocess

CONFIG_DIR = os.path.expanduser("~/.lifeboard")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
SECRETS_FILE = os.path.join(CONFIG_DIR, "secrets.json")
BOARD_FILE = os.path.join(CONFIG_DIR, "board.json")
PHONE_BOARD_FILE = os.path.join(CONFIG_DIR, "board_phone.json")
OUTPUT_DIR = os.path.join(CONFIG_DIR, "output")

DEFAULT_THEME = "slate"

IPHONE_RESOLUTIONS = {
    # Physical pixel (width, height, scale). Logical resolution = width/scale, height/scale.
    "iphone_17_pro_max": (1320, 2868, 3),
    "iphone_17_pro": (1206, 2622, 3),
    "iphone_17_air": (1260, 2736, 3),
    "iphone_17": (1206, 2622, 3),
    "iphone_16_pro_max": (1320, 2868, 3),
    "iphone_16_pro": (1206, 2622, 3),
    "iphone_16_plus": (1290, 2796, 3),
    "iphone_16": (1179, 2556, 3),
    "iphone_15_pro_max": (1290, 2796, 3),
    "iphone_15_pro": (1179, 2556, 3),
    "iphone_15_plus": (1290, 2796, 3),
    "iphone_15": (1179, 2556, 3),
    "iphone_14_pro_max": (1290, 2796, 3),
    "iphone_14_pro": (1179, 2556, 3),
    "iphone_14_plus": (1284, 2778, 3),
    "iphone_14": (1170, 2532, 3),
    "iphone_13_mini": (1080, 2340, 3),
    "iphone_se": (750, 1334, 2),
}
DEFAULT_IPHONE_MODEL = "iphone_16_pro_max"

DEFAULT_CONFIG = {
    "theme": DEFAULT_THEME,
    "ai_api_key": "",
    "ai_base_url": "https://openrouter.ai/api/v1",
    "ai_model": "anthropic/claude-sonnet-4.6",
    "finnhub_api_key": "",
    "coingecko_api_key": "",
    "hotkey": "cmd+shift+l",
    "telegram_enabled": False,
    "telegram_bot_token_env": "MY_LIFEBOARD_BOT",
    "telegram_group_id": "",
    "iphone_model": DEFAULT_IPHONE_MODEL,
}


def get_iphone_resolution(config: dict | None = None) -> list[int]:
    """Return *logical* [width, height] (CSS points) for the configured iPhone model.

    Logical = physical / device-scale. This is what we hand to the renderer's
    viewport so CSS px sizes match how iOS would lay them out on the device.
    The renderer multiplies by the scale factor to produce the wallpaper-sized PNG.
    """
    cfg = config if config is not None else load_config()
    model = cfg.get("iphone_model", DEFAULT_IPHONE_MODEL)
    res = IPHONE_RESOLUTIONS.get(model) or IPHONE_RESOLUTIONS[DEFAULT_IPHONE_MODEL]
    width_px, height_px, scale = res
    return [width_px // scale, height_px // scale]


def get_iphone_scale(config: dict | None = None) -> int:
    cfg = config if config is not None else load_config()
    model = cfg.get("iphone_model", DEFAULT_IPHONE_MODEL)
    res = IPHONE_RESOLUTIONS.get(model) or IPHONE_RESOLUTIONS[DEFAULT_IPHONE_MODEL]
    return res[2]

SECRET_CONFIG_KEYS = {
    "ai_api_key",
    "finnhub_api_key",
    "coingecko_api_key",
}


def get_default_resolution() -> list[int]:
    """Return the best initial wallpaper resolution for this Mac."""
    width, height = get_screen_resolution()
    return [width, height]


def get_api_key(config: dict | None = None) -> str:
    """Get AI API key from config or environment."""
    if config:
        key = config.get("ai_api_key", "")
        if key:
            return key
    return os.environ.get("AI_API_KEY", "")


def get_screen_resolution() -> tuple[int, int]:
    """Auto-detect primary screen resolution."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if "Resolution" in line and "Retina" in line:
                parts = line.split()
                w, h = int(parts[1]), int(parts[3])
                return (w * 2, h * 2)  # Retina = 2x
            if "Resolution" in line:
                parts = line.split()
                return (int(parts[1]), int(parts[3]))
    except Exception:
        pass
    return (2560, 1600)


def ensure_dirs():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            config.update(json.load(f))
    if os.path.exists(SECRETS_FILE):
        with open(SECRETS_FILE) as f:
            config.update(json.load(f))
    return config


def save_config(config: dict):
    ensure_dirs()
    existing_secrets = {}
    if os.path.exists(SECRETS_FILE):
        with open(SECRETS_FILE) as f:
            existing_secrets = json.load(f)

    public_config = {
        key: value
        for key, value in config.items()
        if key not in SECRET_CONFIG_KEYS
    }
    secrets = {
        **existing_secrets,
        **{
            key: value
            for key, value in config.items()
            if key in SECRET_CONFIG_KEYS and value
        },
    }

    with open(CONFIG_FILE, "w") as f:
        json.dump(public_config, f, indent=2)
    if secrets:
        with open(SECRETS_FILE, "w") as f:
            json.dump(secrets, f, indent=2)
        os.chmod(SECRETS_FILE, 0o600)
