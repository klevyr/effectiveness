"""Configuración de logging para el paquete efectividad."""
from __future__ import annotations

import logging
import sys


def setup_logger(name: str = "efectividad", level: int = logging.INFO) -> logging.Logger:
    """Retorna un logger configurado con formato estándar.

    Parameters
    ----------
    name : str
        Nombre del logger.
    level : int
        Nivel de logging (default ``logging.INFO``).

    Returns
    -------
    logging.Logger
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger
