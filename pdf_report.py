"""Generate PDF report for a UAT review. Compact, modern layout with BC branding."""
import os
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# Logo path: project assets folder
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(_SCRIPT_DIR, "assets", "BigCommerce-logo-dark.svg")


class SVGFlowable(Flowable):
    """Flowable that renders an SVG drawing (e.g. logo) at a fixed size."""

    def __init__(self, path, width_inch=1.4, height_inch=0.35):
        self.path = path
        self.width_inch = width_inch
        self.height_inch = height_inch
        self.drawing = None
        try:
            from svglib.svglib import svg2rlg

            if os.path.isfile(path):
                self.drawing = svg2rlg(path)
                if self.drawing and getattr(self.drawing, "width", 0) and getattr(self.drawing, "height", 0):
                    # Scale to fit in box, preserving aspect ratio (points: 72 per inch)
                    target_w = width_inch * 72
                    target_h = height_inch * 72
                    orig_w = self.drawing.width
                    orig_h = self.drawing.height
                    scale = min(target_w / orig_w, target_h / orig_h)
                    self.drawing.scale(scale, scale)
                    self.drawing.width = orig_w * scale
                    self.drawing.height = orig_h * scale
        except Exception:
            pass

    def wrap(self, availableWidth, availableHeight):
        return (self.width_inch * 72, self.height_inch * 72)

    def draw(self):
        if not self.drawing:
            return
        try:
            from reportlab.graphics import renderPDF

            renderPDF.draw(self.drawing, self.canv, 0, 0)
        except Exception:
            pass


def _logo_flowable():
    if os.path.isfile(LOGO_PATH):
        # Larger logo to match header prominence (~2.2" wide, ~1.3" tall by aspect)
        return SVGFlowable(LOGO_PATH, width_inch=2.4, height_inch=1.35)
    return None


# Result display: text only (no icons), with color for professional styling
RESULT_CONFIG = {
    "Pass": ("Pass", colors.HexColor("#0d8050")),
    "Fail": ("Fail", colors.HexColor("#c23030")),
    "Partial": ("Partial", colors.HexColor("#b86f00")),
    "NA": ("N/A", colors.HexColor("#666666")),
}


def _footer_canvas(canvas, doc, title=None):
    """Draw PDF metadata (title), confidentiality notice, and page number on each page."""
    canvas.saveState()
    # Set document title so viewers don't show "(anonymous)"
    if title:
        canvas.setTitle(title)
    # Position footer well above bottom edge so it stays visible (not clipped by viewers/printers)
    footer_y = 0.6 * inch
    footer_font_size = 9
    line_y = footer_y + (footer_font_size * 0.6)
    canvas.setStrokeColor(colors.HexColor("#888"))
    canvas.setLineWidth(0.5)
    canvas.line(0.5 * inch, line_y, 8 * inch, line_y)
    canvas.setFont("Helvetica-Bold", footer_font_size)
    canvas.setFillColor(colors.HexColor("#333"))
    canvas.drawString(0.5 * inch, footer_y, "Confidential \u2014 Not for public release.")
    canvas.drawRightString(8 * inch, footer_y, f"Page {doc.page}")
    canvas.restoreState()


# Minimum gap between logo and title when title is below logo (20px ≈ 20pt at 72 dpi)
HEADER_TITLE_GAP_BELOW_LOGO = 20 / 72 * inch  # 20pt minimum


def build_pdf(review, sections_criteria, header_title_position="right_top"):
    """Build a PDF report for the given review and criteria grouped by section. Returns BytesIO buffer.

    header_title_position: "right_top" = title at top of right column, block vertically centered;
                          "below_logo" = title directly below logo (min 20pt gap).
    """
    buf = BytesIO()
    margin = 0.5 * inch
    bottom_with_footer = 0.9 * inch  # room for footer so it's not clipped
    doc = BaseDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=bottom_with_footer,
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="normal",
    )
    app_name = (review.get("app_name") or "Report").strip()
    pdf_title = f"Marketplace App Review Results \u2014 {app_name}"

    def on_page(canvas, doc):
        _footer_canvas(canvas, doc, title=pdf_title)

    doc.addPageTemplates([PageTemplate(id="all", frames=frame, onPage=on_page)])
    # Content width on letter with 0.5" margins = 7.5"
    content_width = 7.5 * inch
    styles = getSampleStyleSheet()

    # Compact styles: smaller fonts for more content per page
    header_title_style = ParagraphStyle(
        "HeaderTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        spaceBefore=0,
        spaceAfter=0,
        textColor=colors.HexColor("#333"),
    )
    header_meta_style = ParagraphStyle(
        "HeaderMeta",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#444"),
        leading=11,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=8,
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=7,
    )
    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=7,
        leading=8,
        spaceBefore=0,
        spaceAfter=0,
    )

    # Alternating row color for data rows (light gray)
    ROW_ALT_BG = colors.HexColor("#E8E8EC")
    REF_MAX_LEN = 50

    def _truncate(s, max_len):
        s = (s or "").strip()
        if len(s) <= max_len:
            return s
        return s[: max_len - 3] + "..."

    body = []

    # ---- Header: left = logo + title stacked; right = metadata block; vertical separator ----
    app_name = review.get("app_name") or "\u2014"
    app_id = str(review.get("app_id") or "\u2014")
    date_val = review.get("date") or "\u2014"
    submitter_email = review.get("app_owner_email") or "\u2014"

    # Right column: one label per line (block format)
    meta_block = (
        f"App: {app_name}<br/>"
        f"ID: {app_id}<br/>"
        f"Date: {date_val}<br/>"
        f"Submitter: {submitter_email}"
    )
    logo = _logo_flowable()
    logo_col = 2.5 * inch
    meta_col = content_width - logo_col

    if logo:
        title_para = Paragraph("Marketplace App Review Results", header_title_style)
        if header_title_position == "right_top":
            # Left column: logo only. Right column: title at top, then metadata block; vertically centered.
            left_content = [logo]
            right_content = [
                title_para,
                Spacer(1, 0.12 * inch),
                Paragraph(meta_block, header_meta_style),
            ]
            header_content = [[left_content, right_content]]
            valign_right = "MIDDLE"
        else:
            # below_logo: title directly below logo with minimum 20pt gap
            left_content = [
                logo,
                Spacer(1, HEADER_TITLE_GAP_BELOW_LOGO),
                title_para,
            ]
            right_content = Paragraph(meta_block, header_meta_style)
            header_content = [[left_content, right_content]]
            valign_right = "MIDDLE"

        header_table = Table(
            header_content,
            colWidths=[logo_col, meta_col],
        )
        header_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (0, 0), "TOP"),
                ("VALIGN", (1, 0), (1, 0), valign_right),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 8),
                ("LEFTPADDING", (1, 0), (1, -1), 12),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LINEBEFORE", (1, 0), (1, -1), 0.5, colors.HexColor("#ccc")),  # vertical separator
            ])
        )
    else:
        header_content = [[
            Paragraph("Marketplace App Review Results", header_title_style),
            Paragraph(meta_block, header_meta_style),
        ]]
        header_table = Table(header_content, colWidths=[logo_col, meta_col])
        header_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LINEBEFORE", (1, 0), (1, -1), 0.5, colors.HexColor("#ccc")),
            ])
        )
    body.append(header_table)
    body.append(Spacer(1, 0.25 * inch))

    # ---- Criteria table: wide, small font, tight padding ----
    col_num = 0.35 * inch
    col_result = 0.65 * inch
    col_reference = 1.0 * inch
    col_criterion = content_width - col_num - col_result - col_reference

    counts = {"Pass": 0, "Fail": 0, "Partial": 0, "NA": 0}
    global_idx = 1
    for section in sections_criteria:
        body.append(Paragraph(section.get("name", "General"), section_style))
        items = section.get("items", [])
        table_data = [["#", "Criterion", "Result", "Reference"]]
        result_styles = []  # (row_index, result_key) for color styling
        for c in items:
            raw_result = c.get("result") or ""
            if raw_result in counts:
                counts[raw_result] += 1
            display_text, _ = RESULT_CONFIG.get(raw_result, ("—", colors.HexColor("#666666")))
            criterion_text = c.get("text", "")
            criterion_cell = Paragraph(escape(criterion_text), table_cell_style)
            attachment = (c.get("attachment") or "").strip()
            if attachment:
                ref_display = _truncate(attachment, REF_MAX_LEN)
                if attachment.startswith("https://") or attachment.startswith("http://"):
                    ref_cell = Paragraph(
                        f'<a href="{escape(attachment)}" color="#3C64F4">{escape(ref_display)}</a>',
                        table_cell_style,
                    )
                else:
                    ref_cell = Paragraph(escape(ref_display), table_cell_style)
            else:
                ref_cell = "—"
            table_data.append([str(global_idx), criterion_cell, display_text, ref_cell])
            result_styles.append((len(table_data) - 1, raw_result))
            global_idx += 1
        if table_data:
            crit_table = Table(
                table_data,
                colWidths=[col_num, col_criterion, col_result, col_reference],
                repeatRows=1,
            )
            style_commands = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34313F")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ddd")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),  # center text vertically in each row
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#34313F")),
            ]
            for row_idx in range(1, len(table_data)):
                if row_idx % 2 == 1:
                    style_commands.append(
                        ("BACKGROUND", (0, row_idx), (-1, row_idx), ROW_ALT_BG)
                    )
            for row_idx, result_key in result_styles:
                if result_key in RESULT_CONFIG:
                    _, color = RESULT_CONFIG[result_key]
                    style_commands.append(("TEXTCOLOR", (2, row_idx), (2, row_idx), color))
            crit_table.setStyle(TableStyle(style_commands))
            body.append(crit_table)
    body.append(Spacer(1, 0.15 * inch))

    if review.get("overall_notes"):
        body.append(Paragraph("<b>Overall notes:</b> " + review["overall_notes"], body_style))
        body.append(Spacer(1, 0.1 * inch))

    summary = (
        f"Summary: Pass {counts['Pass']}, Fail {counts['Fail']}, "
        f"Partial {counts['Partial']}, N/A {counts['NA']}"
    )
    body.append(Paragraph(summary, body_style))

    doc.build(body)
    return buf
