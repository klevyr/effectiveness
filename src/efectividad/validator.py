"""Validación de resultados de efectividad.

Compara conteos entre gestor y consolidado por código de notificación.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from efectividad.logger import setup_logger
from efectividad.models import ValidationResult
from efectividad.storage import delete_transfer_date, read_parquet

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
    consol = read_parquet(base_path, "reporte", date_str)

    results: list[ValidationResult] = []

    for codigo, desc in checks.items():
        total_ges = 0
        total_consol = 0

        if not ges.collect().is_empty():
            total_ges = ges.filter(pl.col("IdCodigo") == codigo).select(pl.len()).collect().item()

        if not consol.collect().is_empty():
            total_consol = consol.filter(pl.col("CdMensaje") == codigo).select(pl.len()).collect().item()

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


def validate_result_effectiveness(
        cfg: dict,
        date_str: str,
        result_check: list[ValidationResult],
) -> None:
    """Valida resultado de efectividad y elimina archivos si es satisfactorio.

    Parameters
    ----------
    date_str : str
        Fecha en formato ``YYYYMMDD``.

    Returns
    -------
    bool
        True si todos los checks pasaron, False si alguno falló.
    """
    results = pl.DataFrame(result_check)
    pass_count = results.filter(
        pl.col("estado").is_in(["pass",])
    ).shape[0]
    danger_count = results.filter(
        pl.col("estado").is_in(["danger", "warning"])
    ).shape[0]
    # Elimina Informacion recuperada si el resultado de validación es satisfactorio
    if pass_count > 0 and pass_count > danger_count:
        log.info(">>> Validación exitosa: %d checks pasaron, %d checks fallaron",
                    pass_count,
                    danger_count
        )    
        """Elimina datos procesados para una fecha específica."""
        transfer_dir: Path = cfg["paths"]["transfer"]
        vendor_dir: Path = cfg["paths"]["vendor"]
        # gestor
        delete_transfer_date(transfer_dir, date_str, mask="*.csv")
        # vendor
        delete_transfer_date(vendor_dir, date_str, mask="")
    else:
        log.warning(">>> Validación fallida: %d checks pasaron, %d checks fallaron",
                    pass_count,
                    danger_count
        )



def _print_validation(results: list[ValidationResult]) -> None:
    """Imprime la tabla de validación en consola."""
    log.info("== VALIDACIONES ============================ GESTOR/EFECTIVIDAD ===== %% ESTADO")
    for r in results:
        indicator = {
            "pass": "🟢 pass",
            "warning": "🟡 warning",
            "danger": "🔴 danger",
        }[r.estado]
        log.info(
            "Checking %-38s %6d / %-6d %7.2f%% %s",
            r.descripcion,
            r.total_gestor,
            r.total_consolidado,
            r.porcentaje,
            indicator,
        )
