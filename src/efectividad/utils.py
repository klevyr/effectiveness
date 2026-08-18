"""Utilidades y controladores de sistema.

Migrados desde ``bootstrap2.py``: OSTransfersController, SFTPManager,
SplitNamesEC.
"""
from __future__ import annotations

import configparser
import logging
import os
import re
import zipfile
from pathlib import Path
from subprocess import PIPE, Popen

import paramiko

from efectividad.logger import setup_logger

log = setup_logger()


# ---------------------------------------------------------------------------
# AS400 Transfers
# ---------------------------------------------------------------------------

class OSTransfersController:
    """Controla transferencias AS400 vía ``acsbundle.jar``."""

    def __init__(
        self,
        transfer_folder: str | Path,
        as400_user: str,
        as400_pass: str,
        acsbundle_path: str | Path,
    ) -> None:
        self.transfer_folder = Path(transfer_folder)
        self.transfer_folder.mkdir(parents=True, exist_ok=True)
        self._user = as400_user
        self._pass = as400_pass
        self._acsbundle = Path(acsbundle_path)
        self._current_transfer: Path | None = None

    def set_config_transfer(
        self,
        file_transfer: str,
        config_section: str,
        config_key: str,
        config_value: str,
    ) -> None:
        """Modifica un parámetro en un archivo de transferencia."""
        self._current_transfer = self.transfer_folder / file_transfer
        cfg = configparser.ConfigParser()
        cfg.optionxform = str  # type: ignore[assignment]
        cfg.read(self._current_transfer)
        log.info("Cambio %s[%s] → %s", config_section, config_key, config_value)
        cfg.set(config_section, config_key, config_value)
        with open(self._current_transfer, "w", encoding="utf-8") as fh:
            cfg.write(fh, False)

    def acsbundle_init(self) -> None:
        """Inicializa sesión con AS400."""
        proc = Popen(
            [
                "java", "-jar", str(self._acsbundle),
                "/plugin=logon",
                "/system=AS400F35",
                f"/userid={self._user}",
                f"/password={self._pass}",
                "/gui=0",
            ],
            stdin=PIPE, stdout=PIPE, stderr=PIPE,
        )
        output, err = proc.communicate()
        if err:
            log.error("acsbundle_init error: %s", err.decode("utf-8", errors="replace"))
        for line in output.decode("ISO8859-1", errors="replace").splitlines():
            if line.strip():
                log.info(line)

    def acsbundle_download(self) -> None:
        """Descarga archivos desde AS400."""
        if self._current_transfer is None:
            log.error("No hay transferencia configurada")
            return
        proc = Popen(
            [
                "java", "-jar", str(self._acsbundle),
                "/plugin=download",
                "/system=AS400F35",
                f"/userid={self._user}",
                str(self._current_transfer),
            ],
            stdin=PIPE, stdout=PIPE, stderr=PIPE,
        )
        output, err = proc.communicate()
        if err:
            log.error("acsbundle_download error: %s", err)
        for line in output.decode("ISO8859-1", errors="replace").splitlines():
            stripped = line.strip()
            if stripped[:6].upper() == "FILAS ":
                rows = stripped.split(":")[1].strip()
                log.info("Descargadas %s filas", rows)

    def acsbundle_upload(self) -> None:
        """Carga archivos a AS400."""
        if self._current_transfer is None:
            log.error("No hay transferencia configurada")
            return
        proc = Popen(
            [
                "java", "-jar", str(self._acsbundle),
                "/plugin=upload",
                str(self._current_transfer),
                f"/userid={self._user}",
            ],
            stdin=PIPE, stdout=PIPE, stderr=PIPE,
        )
        output, err = proc.communicate()
        if err:
            log.error("acsbundle_upload error: %s", err)
        for line in output.decode("ISO8859-1", errors="replace").splitlines():
            stripped = line.strip()
            if stripped[:6].upper() == "FILAS ":
                rows = stripped.split(":")[1].strip()
                log.info("Subidas %s filas", rows)


# ---------------------------------------------------------------------------
# SFTP Manager
# ---------------------------------------------------------------------------

class SFTPManager:
    """Descarga de archivos vendor desde SFTP."""

    def __init__(
        self,
        host: str,
        port: int,
        uid: str,
        pwd: str,
        remote_path: str = "./LINK MOBILE LINKMBL BTS_ SMS/",
        local_dir: str | Path = "./vendor",
    ) -> None:
        self._host = host
        self._port = port
        self._uid = uid
        self._pwd = pwd
        self._remote_path = remote_path
        self._local_dir = Path(local_dir)
        self._local_dir.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> paramiko.SFTPClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self._host,
            self._port,
            self._uid,
            self._pwd,
            allow_agent=False,
            look_for_keys=False,
        )
        return client.open_sftp()

    def get_files_list(self) -> list[str]:
        """Lista archivos disponibles en el directorio remoto."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self._host, self._port, self._uid, self._pwd,
                allow_agent=False, look_for_keys=False,
            )
            sftp = client.open_sftp()
            log.info("Conexión SFTP exitosa")
            files = sorted(sftp.listdir(self._remote_path))
            sftp.close()
            return files
        finally:
            client.close()

    def download_file(self, filename: str) -> Path:
        """Descarga un archivo y lo comprime como ZIP.

        Parameters
        ----------
        filename : str
            Nombre del archivo en el servidor remoto.

        Returns
        -------
        Path
            Ruta del archivo ZIP local.
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            log.info("Descargando %s...", filename)
            client.connect(
                self._host, self._port, self._uid, self._pwd,
                allow_agent=False, look_for_keys=False,
            )
            sftp = client.open_sftp()
            local_file = self._local_dir / filename
            sftp.get(f"{self._remote_path}/{filename}", str(local_file))
            sftp.close()

            zip_path = self._local_dir / f"{filename}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(local_file, arcname=local_file.name)
            local_file.unlink()
            log.info("Descarga completada: %s", zip_path)
            return zip_path
        finally:
            client.close()


# ---------------------------------------------------------------------------
# Nombre helpers
# ---------------------------------------------------------------------------

class SplitNamesEC:
    """Separación de nombres completos ecuatorianos."""

    _ESPECIALES = frozenset([
        "da", "de", "di", "do", "del", "la", "las",
        "le", "los", "mac", "mc", "van", "von", "y", "i", "san", "santa",
    ])

    def split(self, nombre: str) -> tuple[str, str, str, str]:
        """Retorna (nombre1, nombre2, apellido1, apellido2)."""
        tokens = nombre.split()
        parts: list[str] = []
        prev = ""
        for tok in tokens:
            if tok.lower() in self._ESPECIALES:
                prev += tok + " "
            else:
                parts.append(prev + tok)
                prev = ""

        n = len(parts)
        n1 = n2 = a1 = a2 = ""

        if n == 0:
            pass
        elif n == 1:
            n1 = parts[0]
        elif n == 2:
            a1, n1 = parts
        elif n == 3:
            a1, a2, n1 = parts
        elif n == 4:
            a1, a2, n1, n2 = parts
        else:
            a1, a2 = parts[0], parts[1]
            n1 = parts[2]
            n2 = " ".join(parts[3:5])

        return (n1.title(), n2.title(), a1.title(), a2.title())

    def val_identification_number(self, cid: str) -> bool:
        """Valida cédula/ruc ecuatoriana de 10 dígitos."""
        return bool(re.fullmatch(r"[0-9]{10}", cid))
