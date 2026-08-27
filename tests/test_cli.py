from unittest.mock import patch

from typer.testing import CliRunner

from efectividad.cli import app

runner = CliRunner()


def test_process_can_generate_reports_at_end():
    with (
        patch(
            "efectividad.cli.load_config",
            return_value={
                "paths": {
                    "data": "./data",
                    "transfer": "./transfer",
                    "vendor": "./vendor",
                },
                "statuses": [],
                "validation_checks": {},
                "gestor_columns": [
                    "Fecha",
                    "Entidad",
                    "Marca",
                    "Hora",
                    "IdCodigo",
                    "Tarjeta_Cuenta",
                    "Cedula",
                    "NumCel",
                    "Mensaje",
                    "ConfId",
                    "IdUsuario",
                ],
                "vendor_columns": [
                    "MobileNumber",
                    "ShortCode",
                    "Message",
                    "Priority",
                    "TotalFragments",
                    "Type",
                    "Carrier",
                    "Date",
                    "TransactionId",
                    "ApplicationStatus",
                    "ResponseCode",
                    "PlatformStatus",
                    "DescriptionStatus",
                ],
            },
        ),
        patch("efectividad.cli._run_transfers"),
        patch("efectividad.cli.load_gestor"),
        patch("efectividad.cli.load_vendor"),
        patch("efectividad.cli.generate_effectiveness"),
        patch("efectividad.cli.generate_global_report"),
        patch("efectividad.cli.check_effectiveness"),
        patch(
            "efectividad.cli.generate_reports", return_value=["report.xlsx"]
        ) as mock_generate_reports,
        patch("efectividad.cli.generate_length_report") as mock_length_report,
    ):
        result = runner.invoke(app, ["process", "--fecha", "20251022", "--report"])

    assert result.exit_code == 0
    mock_generate_reports.assert_called_once()
    mock_length_report.assert_called_once()
