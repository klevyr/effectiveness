"""Definiciones de schema / dataclasses para el dominio SMS efectividad."""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Columnas derivadas (agregadas durante el pipeline, no vienen del archivo)
# ---------------------------------------------------------------------------

GESTOR_EXTRA_COLUMNS: list[str] = ["TipoCola", "tsges", "MensajeMD5"]

VENDOR_EXTRA_COLUMNS: list[str] = ["Fecha", "Hora", "tsvend", "MessageMD5"]

CONSOLIDATED_COLUMNS: list[str] = [
    "Fecha",
    "Hora",
    "Entidad",
    "Marca",
    "IdCodigo",
    "Tarjeta_Cuenta",
    "Cedula",
    "NumCelular",
    "IdUsuario",
    "ConfId",
    "TransactionId",
    "Mensaje",
    "Carrier",
    "Fecha_Hora_YP",
    "ApplicationStatus",
    "PlatformStatus",
    "ShortCode",
    "DescriptionStatus",
    "seconds_diff",
]

REPORT_COLUMNS: list[str] = [
    "Fecha",
    "Entidad",
    "Marca",
    "CdMensaje",
    "Desc_Banco_Envio",
    "Tarjeta_Cuenta",
    "Num_Doc_Identificacion",
    "NumCelular",
    "IdUsuario",
    "Mensaje",
    "TransactionId",
    "Operadora",
    "ApplicationStatus",
    "PlatformStatus",
    "Desc_Campania",
    "Desc_AreaCampania",
    "Tipo_Campania",
    "Cd_Enlace",
    "Estado_Operadora",
    "Desc",
    "Area",
    "Estado_Proveedor",
    "DescriptionStatus",
    "Volumen",
    "Porc_Exito",
    "Porc_Rechazo",
]


# ---------------------------------------------------------------------------
# Definición de un resultado de validación
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    codigo: str
    descripcion: str
    total_gestor: int
    total_consolidado: int
    porcentaje: float
    estado: str = field(init=False)

    def __post_init__(self) -> None:
        if self.total_gestor == 0:
            self.porcentaje = 100.0
        else:
            self.porcentaje = (self.total_consolidado / self.total_gestor) * 100
        if self.porcentaje >= 99.0:
            self.estado = "pass"
        elif self.porcentaje >= 95.0:
            self.estado = "warning"
        else:
            self.estado = "danger"
