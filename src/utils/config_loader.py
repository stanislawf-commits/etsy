"""
config_loader.py — ładuje konfigurację YAML z katalogu config/.

Użycie:
    from src.utils.config_loader import cfg
    pricing = cfg("pricing")
    price_min = pricing["product_types"]["cutter"]["price_min"]
"""
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parents[2] / "config"


@lru_cache(maxsize=None)
def cfg(name: str) -> dict:
    """
    Ładuje i zwraca zawartość config/{name}.yaml jako dict.
    Wynik jest cachowany — plik czytany tylko raz per sesja.

    Args:
        name: Nazwa pliku bez rozszerzenia (np. "pricing", "etsy")

    Returns:
        dict z zawartością YAML

    Raises:
        FileNotFoundError: Brak pliku config/{name}.yaml
        ImportError: Brak biblioteki PyYAML (pip install pyyaml)
    """
    try:
        import yaml
    except ImportError as e:
        raise ImportError("PyYAML not installed. Run: pip install pyyaml") from e

    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    log.debug("Loaded config: %s (%d keys)", path.name, len(data) if data else 0)
    return data or {}


def reload(name: str) -> dict:
    """Czyści cache i przeładowuje config. Przydatne w testach."""
    cfg.cache_clear()
    return cfg(name)
