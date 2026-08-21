from io import BytesIO

from openpyxl import load_workbook

from app.reporting_schemas import ReportTable
from app.reports import export_csv, export_pdf, export_xlsx


def sample_table() -> ReportTable:
    return ReportTable(
        code="productivity",
        title="Продуктивность сотрудников",
        columns=["employee_name", "productive_percent"],
        rows=[{"employee_name": "Иван Иванов", "productive_percent": 78.5}],
    )


def test_csv_export_has_utf8_bom_and_cyrillic():
    content = export_csv(sample_table(), sample_table().columns)
    assert content.startswith(b"\xef\xbb\xbf")
    assert "Иван Иванов" in content.decode("utf-8-sig")


def test_xlsx_export_is_readable_and_contains_data():
    content = export_xlsx(sample_table(), sample_table().columns)
    workbook = load_workbook(BytesIO(content))
    sheet = workbook.active
    assert sheet["A2"].value == "Иван Иванов"
    assert sheet["B2"].value == "78.5"


def test_pdf_export_is_a_pdf():
    content = export_pdf(sample_table(), sample_table().columns)
    assert content.startswith(b"%PDF-")
    assert len(content) > 1000
