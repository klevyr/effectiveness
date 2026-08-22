"""Configuración centralizada del proyecto.

Carga configuración desde YAML y variables de entorno.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CFG_DIR = _PROJECT_ROOT / "cfg"


def _resolve_path(value: str, base: Path | None = None) -> Path:
    """Resuelve una ruta relativa contra un directorio base."""
    p = Path(value)
    if p.is_absolute():
        return p
    return (base or _PROJECT_ROOT) / p


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    """Lee una variable de entorno."""
    val = os.environ.get(key, default)
    if required and val is None:
        raise EnvironmentError(f"Variable de entorno requerida no encontrada: {key}")
    return val or ""


def _load_env_values() -> dict[str, str | None]:
    """Carga los valores del archivo .env si existe."""
    env_file = _PROJECT_ROOT / ".env"
    return dotenv_values(env_file) if env_file.exists() else {}


def _config_env(
    key: str,
    env_values: dict[str, str | None],
    default: str | None = None,
    required: bool = False,
) -> str:
    """Lee una clave desde .env y usa el entorno como respaldo."""
    value = env_values.get(key)
    if value is None:
        value = os.environ.get(key, default)
    if required and value is None:
        raise EnvironmentError(f"Variable de entorno requerida no encontrada: {key}")
    return value or ""


def load_config(env: str = "dev") -> dict[str, Any]:
    """Carga la configuración completa desde el YAML del entorno indicado.

    Parameters
    ----------
    env : str
        Nombre del entorno (archivo ``cfg/{env}.yml``).

    Returns
    -------
    dict
        Configuración fusionada: rutas resueltas, estados, credenciales ENV.
    """
    cfg_file = _CFG_DIR / f"{env}.yml"
    if not cfg_file.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {cfg_file}")

    with open(cfg_file, encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    env_values = _load_env_values()

    # Resolver rutas relativas
    paths_cfg: dict[str, str] = raw.get("paths", {})
    paths: dict[str, Path] = {}
    for key, val in paths_cfg.items():
        paths[key] = _resolve_path(val)
        paths[key].mkdir(parents=True, exist_ok=True)
    raw["paths"] = paths

    # Credenciales desde variables de entorno
    raw["sftp"] = raw.get("sftp") or {}
    raw["sftp"]["host"] = _config_env("SFTP_HOST", env_values, required=True)
    raw["sftp"]["port"] = int(_config_env("SFTP_PORT", env_values, "22"))
    raw["sftp"]["uid"] = _config_env("SFTP_UID", env_values, required=True)
    raw["sftp"]["pwd"] = _config_env("SFTP_PWD", env_values, required=True)

    raw["as400"] = raw.get("as400") or {}
    raw["as400"]["user"] = _config_env("AS400_USER", env_values, required=True)
    raw["as400"]["password"] = _config_env("AS400_PASS", env_values, required=True)

    return raw
