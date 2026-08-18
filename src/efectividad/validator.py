"""Validación de resultados de efectividad.

Compara conteos entre gestor y consolidado por código de notificación.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from efectividad.logger import setup_logger
from efectividad.models import ValidationResult
from efectividad.storage import read_parquet

log = setup_logger()


def check_effectiveness(
    base_path: Path,
    date_str: str,
    checks: dict[str, str] | None = None,
) -> list[ValidationResult]:
    """Valida la efectividad por código de notificación.

    Parameters
    ----------
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    checks : dict[str, str] | None
        Mapping ``{codigo: descripcion}``. Si es ``None``, usa los checks
        por defecto del config.

    Returns
    -------
    list[ValidationResult]
        Resultados de validación por código.
    """
    if checks is None:
        checks = {
            "0270": "Consumos",
            "0002": "Pagos",
            "0001": "Saldos",
            "0969": "Actuales cierre",
            "4225": "OTP Placetopay",
            "0923": "Actuales cierre",
            "0260": "PINES",
            "0279": "Consumos ATM",
        }

    ges = read_parquet(base_path, "gestor", date_str)
    consol = read_parquet(base_path, "consolidado", date_str)

    results: list[ValidationResult] = []

    for codigo, desc in checks.items():
        total_ges = 0
        total_consol = 0

        if not ges.is_empty():
            total_ges = ges.filter(pl.col("IdCodigo") == codigo).height

        if not consol.is_empty():
            total_consol = consol.filter(pl.col("CdMensaje") == codigo).height

        vr = ValidationResult(
            codigo=codigo,
            descripcion=desc,
            total_gestor=total_ges,
            total_consolidado=total_consol,
            porcentaje=0.0,
        )
        results.append(vr)

    _print_validation(results)
    return results


def _print_validation(results: list[ValidationResult]) -> None:
    """Imprime la tabla de validación en consola."""
    log.info("*** VALIDACIONES *********************** GESTOR/EFECTIVIDAD ********* %% * ESTADO")
    for r in results:
        indicator = {
            "pass": "pass",
            "warning": "warning",
            "danger": "danger",
        }[r.estado]
        log.info(
            "Checking %-38s %6d / %-6d %7.3f%% %s",
            r.descripcion,
            r.total_gestor,
            r.total_consolidado,
            r.porcentaje,
            indicator,
        )
