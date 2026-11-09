"""Экспорт редактируемого черновика осмотра в Word и печатной копии в PDF."""
from io import BytesIO
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.sax.saxutils import escape

from .model import AppError
from .protocol import BY_KEY


PRINT_TITLE = "Предоперационный осмотр врачом-анестезиологом-реаниматологом"
SUBTITLE = "Черновик для проверки врачом"
FORM_SECTIONS = (
    ("Сведения об осмотре", ("patient_name", "chart_number", "birth_date", "sex", "exam_date")),
    ("Жалобы", ("complaints",)),
    ("Анамнез болезни", ("illness",)),
    ("Анамнез жизни", ("life", "medicines", "implants")),
    ("Аллергологический анамнез", ("allergies",)),
    ("Объективный статус", ("objective", "weight", "height", "patient_condition", "skin",
                            "edema_cyanosis", "breathing", "respiratory_rate", "oxygen_saturation",
                            "heart_sounds", "pressure", "pulse", "tongue", "abdomen")),
    ("Перенесённые заболевания", ("past_diseases",)),
    ("Результаты исследований", ("tests",)),
    ("Класс по Mallampati", ("mallampati",)),
    ("Заключение", ("conclusion",)),
    ("Значения оценочных шкал", ("assessment_scales",)),
    ("План вмешательства", ("procedure", "anaesthesia", "manipulations")),
)

# Заголовки из печатного образца. Узкие колонки подогнаны под A4.
TABLE_LAYOUTS = {
    "allergies": (("Тип реакции", "Дата выявления", "Реакция", "Описание агента", "Комментарий",
                   "Лекарственное средство", "Описание реакции", "Критерии серьезности", "Организация выявления"),
                  (105, 95, 90, 92, 120, 123, 92, 108, 108)),
    "assessment_scales": (("Дата", "Шкала", "Баллы", "Интерпретация"), (2159, 3855, 886, 2324)),
}
PAGE_MARGINS_MM = (30, 15, 20, 20)
HEADER = (("Пациент", "patient_name", "№ карты", "chart_number"),
          ("Дата рождения", "birth_date", "Пол", "sex"))


def _value(fields, key):
    value = fields[key]["value"]
    value.encode("utf-8")
    unit = BY_KEY[key].unit
    return f"{value} {unit}" if value and unit else value


def _printable_sections(fields):
    for heading, keys in FORM_SECTIONS[1:]:
        yield heading, [
            (key, BY_KEY[key].label, _value(fields, key)) for key in keys
        ]


def _header_rows(fields):
    return [[_value(fields, label) if index % 2 else label for index, label in enumerate(row)] for row in HEADER]


def _write_docx(output, fields):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    document = Document()
    page = document.sections[0]
    page.page_width, page.page_height = Mm(210), Mm(297)
    page.left_margin, page.right_margin, page.top_margin, page.bottom_margin = map(Mm, PAGE_MARGINS_MM)
    for style_name, size, bold in (("Normal", 11, False), ("Title", 15, True), ("Heading 1", 12, True)):
        style = document.styles[style_name]
        style.font.name, style.font.size, style.font.bold = "Times New Roman", Pt(size), bold
        style.font.color.rgb = RGBColor(0, 0, 0)
        fonts = style.element.rPr.rFonts
        for attribute in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
            fonts.attrib.pop(qn(f"w:{attribute}"), None)
        style.paragraph_format.space_before = Pt(7 if style_name == "Heading 1" else 0)
        style.paragraph_format.space_after = Pt(3)
        border = style.element.pPr.find(qn("w:pBdr"))
        if border is not None:
            style.element.pPr.remove(border)

    def line(label, value):
        paragraph = document.add_paragraph()
        if label:
            paragraph.add_run(label + ": ").bold = True
        paragraph.add_run(value or "____________________")

    def table(headings, ratios):
        grid = document.add_table(rows=2, cols=len(headings))
        grid.style = "Table Grid"
        grid.autofit = False
        margins = OxmlElement("w:tblCellMar")
        for side in ("top", "left", "bottom", "right"):
            margin = OxmlElement("w:" + side)
            margin.set(qn("w:w"), "60")
            margin.set(qn("w:type"), "dxa")
            margins.append(margin)
        grid._tbl.tblPr.insert_element_before(margins, "w:tblLook")
        total = sum(ratios)
        usable_width = page.page_width - page.left_margin - page.right_margin
        for index, (label, ratio) in enumerate(zip(headings, ratios)):
            width = int(usable_width * ratio / total)
            grid.columns[index].width = width
            for row in grid.rows:
                row.cells[index].width = width
            paragraph = grid.cell(0, index).paragraphs[0]
            run = paragraph.add_run(label)
            run.font.size = Pt(7.5)
            run.bold = True
            paragraph.paragraph_format.keep_with_next = True

    document.add_paragraph(PRINT_TITLE, "Title").alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle = document.add_paragraph(SUBTITLE)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.runs[0].italic = True
    header = document.add_table(rows=2, cols=4)
    header.style = "Table Grid"
    for row, values in zip(header.rows, _header_rows(fields)):
        for cell, value in zip(row.cells, values):
            cell.text = value
    line("Дата", _value(fields, "exam_date"))
    for heading, entries in _printable_sections(fields):
        document.add_paragraph(heading, "Heading 1")
        for index, (key, label, value) in enumerate(entries):
            if key in TABLE_LAYOUTS:
                table(*TABLE_LAYOUTS[key])
                if value:
                    line("Сведения", value)
            else:
                line("" if index == 0 and heading == label else label, value)
    line("Подпись врача", "")
    document.save(output)


def _write_pdf(output, fields):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if not (fonts / "times.ttf").is_file():
        fonts = Path("/usr/share/fonts/truetype/dejavu")
        font_files = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
    else:
        font_files = ("times.ttf", "timesbd.ttf")
    if not all((fonts / name).is_file() for name in font_files):
        raise AppError("Для PDF требуется шрифт Times New Roman или DejaVu Sans с поддержкой кириллицы.")
    for name, file in zip(("Protocol", "Protocol-Bold"), font_files):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / file)))
    pdfmetrics.registerFontFamily("Protocol", normal="Protocol", bold="Protocol-Bold")

    left, right, top, bottom = (value * mm for value in PAGE_MARGINS_MM)
    document = SimpleDocTemplate(output, pagesize=A4, title=PRINT_TITLE,
                                 leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom)
    body = ParagraphStyle("Protocol body", fontName="Protocol", fontSize=11, leading=14, spaceAfter=3)
    title = ParagraphStyle("Protocol title", parent=body, fontName="Protocol-Bold", fontSize=15,
                           leading=18, alignment=1, keepWithNext=True)
    subtitle = ParagraphStyle("Protocol subtitle", parent=body, alignment=1, keepWithNext=True)
    heading_style = ParagraphStyle("Protocol heading", parent=body, fontName="Protocol-Bold",
                                   fontSize=12, spaceBefore=7, keepWithNext=True)
    cell_style = ParagraphStyle("Protocol cell", parent=body, fontSize=7.5, leading=9.5, spaceAfter=0)
    story = [Paragraph(PRINT_TITLE, title), Paragraph(SUBTITLE, subtitle)]

    def plain(text, style):
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    def line(label, value):
        caption = f"<b>{escape(label)}:</b> " if label else ""
        story.append(Paragraph(caption + escape(value or "____________________").replace("\n", "<br/>"), body))

    def table(rows, ratios, commands=(), repeat_rows=0):
        widths = [(document.width - 12) * ratio / sum(ratios) for ratio in ratios]
        style = TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#808080")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            *commands,
        ])
        story.append(Table(rows, colWidths=widths, hAlign="LEFT", style=style,
                           repeatRows=repeat_rows, splitInRow=1, spaceAfter=4))

    table([[plain(value, body) for value in row] for row in _header_rows(fields)], (24, 36, 17, 23))
    line("Дата", _value(fields, "exam_date"))
    for heading, entries in _printable_sections(fields):
        story.append(Paragraph(escape(heading), heading_style))
        for index, (key, label, value) in enumerate(entries):
            if key in TABLE_LAYOUTS:
                labels, ratios = TABLE_LAYOUTS[key]
                rows = [[plain(label, cell_style) for label in labels], [""] * len(labels)]
                table(rows, ratios, (("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),), 1)
                if value:
                    line("Сведения", value)
            else:
                line("" if index == 0 and heading == label else label, value)
    line("Подпись врача", "")
    document.build(story)
def _atomic_write(path, content):
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".protocol-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def export_protocol_form(document, path):
    """Экспортирует актуальные значения формы, включая ручные правки."""
    draft = document.protocol
    if draft is None or draft["source_text"] != document.text:
        raise AppError("Сформируйте протокол для текущей расшифровки перед экспортом.")
    target = Path(path)
    writer = {".docx": _write_docx, ".pdf": _write_pdf}.get(target.suffix.lower())
    if writer is None:
        raise AppError("Выберите файл Word (.docx) или PDF (.pdf).")
    try:
        output = BytesIO()
        writer(output, draft["fields"])
        _atomic_write(target, output.getvalue())
    except ImportError as exc:
        raise AppError("Для экспорта установите зависимости приложения через setup.cmd.") from exc
    except (OSError, ValueError) as exc:
        raise AppError("Не удалось экспортировать протокол. Проверьте текст, папку и имя файла.") from exc
