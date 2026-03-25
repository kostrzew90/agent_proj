"""
PDF Label Generator using ReportLab.

Generates labels matching the SketchUp template layout from MaxCut/CNC nesting.
Each label contains: part number, dimensions, material, project name,
nesting miniature with highlighted part, and edge banding info.
"""
import io
import os
from typing import List
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from models import LabelData, LabelConfig


def _draw_label(c: canvas.Canvas, label: LabelData, config: LabelConfig):
    """Draw a single label on the current page."""
    w = config.label_width_mm * mm
    h = config.label_height_mm * mm
    margin = 3 * mm

    # === LAYOUT CONSTANTS ===
    left_col_w = 44 * mm          # left column width (qty + part# + miniature)
    divider_x = left_col_w        # vertical divider X
    right_x = divider_x + 3 * mm  # text start in right column
    dim_divider_x = w - 30 * mm   # vertical divider for dimension cells

    # Row heights (from top)
    row1_h = 12 * mm   # operation type + length
    row2_h = 12 * mm   # company info + width
    row3_h = 12 * mm   # material name
    row4_h = 20 * mm   # project name (large)
    # row5 = rest       # edge banding

    row1_top = h
    row1_bot = h - row1_h
    row2_bot = row1_bot - row2_h
    row3_bot = row2_bot - row3_h
    row4_bot = row3_bot - row4_h

    # === OUTER BORDER ===
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1.5)
    c.rect(0, 0, w, h)

    # === GRID LINES ===
    c.setLineWidth(0.8)
    # Vertical: left column divider (full height)
    c.line(divider_x, 0, divider_x, h)
    # Vertical: dimension column (top two rows only)
    c.line(dim_divider_x, h, dim_divider_x, row2_bot)
    # Horizontal rows
    c.line(divider_x, row1_bot, w, row1_bot)
    c.line(divider_x, row2_bot, w, row2_bot)
    c.line(divider_x, row3_bot, w, row3_bot)
    c.line(divider_x, row4_bot, w, row4_bot)

    # ============================
    # TOP-LEFT: Quantity + Part Number in black box
    # ============================
    # Quantity (small number, top-left corner)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 14)
    c.drawString(margin + 1 * mm, h - 12 * mm, str(label.quantity))

    # Black box with part number (rotated 90 CCW)
    box_x = 13 * mm
    box_y = row2_bot + 1 * mm
    box_w = 25 * mm
    box_h = row1_top - row2_bot - 2 * mm

    c.setFillColorRGB(0, 0, 0)
    c.rect(box_x, box_y, box_w, box_h, fill=1)

    # Part number - white text, rotated 90 CCW, centered in box
    c.saveState()
    c.setFillColorRGB(1, 1, 1)
    num_str = str(label.part_number)
    font_size = 28 if len(num_str) <= 3 else 22
    c.setFont("Helvetica-Bold", font_size)
    cx = box_x + box_w / 2
    cy = box_y + box_h / 2
    c.translate(cx, cy)
    c.rotate(90)
    c.drawCentredString(0, -font_size * 0.35, num_str)
    c.restoreState()

    # ============================
    # ROW 1 (top): Operation Type | Length
    # ============================
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(right_x, row1_bot + 4 * mm, label.operation_type or "")

    # Length dimension (large, right-aligned in dim cell)
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(w - 4 * mm, row1_bot + 3 * mm, f"{label.length_mm:.0f}")

    # ============================
    # ROW 2: Company Info | Width
    # ============================
    c.setFont("Helvetica", 7)
    c.drawString(right_x, row2_bot + 5 * mm, label.company_info or "")

    # Width dimension (large, right-aligned in dim cell)
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(w - 4 * mm, row2_bot + 3 * mm, f"{label.width_mm:.0f}")

    # ============================
    # ROW 3: Material Name
    # ============================
    c.setFont("Helvetica-Bold", 10)
    mat_text = label.material_name or ""
    if len(mat_text) > 35:
        mat_text = mat_text[:33] + ".."
    c.drawString(right_x, row3_bot + 4 * mm, mat_text)

    # ============================
    # ROW 4: Project Name (large, centered)
    # ============================
    c.setFont("Helvetica-Bold", 20)
    proj_text = label.project_name or ""
    center_x = divider_x + (w - divider_x) / 2
    text_y = row4_bot + row4_h / 2 - 5 * mm
    c.drawCentredString(center_x, text_y, proj_text)

    # ============================
    # ROW 5 (bottom-right): Edge Banding Info
    # ============================
    eb = label.edge_banding
    edge_lines = []
    # Use arrow symbols: ^ v < >
    if eb.top:
        edge_lines.append(("\u02c4", eb.top))
    if eb.bottom:
        edge_lines.append(("\u02c5", eb.bottom))
    if eb.left:
        edge_lines.append(("\u02c2", eb.left))
    if eb.right:
        edge_lines.append(("\u02c3", eb.right))

    line_h = 5.5 * mm
    for i, (arrow, spec) in enumerate(edge_lines):
        y_pos = row4_bot - (i + 1) * line_h
        if y_pos > margin:
            # Arrow symbol (larger)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(right_x, y_pos, arrow)
            # Edge spec text
            c.setFont("Helvetica-Bold", 10)
            c.drawString(right_x + 8 * mm, y_pos, spec)

    # ============================
    # BOTTOM-LEFT: Nesting Miniature
    # ============================
    if label.nesting_image:
        mini_w = config.miniature_width_mm * mm
        mini_h = config.miniature_height_mm * mm
        mini_x = margin
        mini_y = margin + 2 * mm

        # Border around miniature
        c.setLineWidth(0.5)
        c.rect(mini_x - 1, mini_y - 1, mini_w + 2, mini_h + 2)

        # Embed image
        img_reader = ImageReader(label.nesting_image)
        c.drawImage(img_reader, mini_x, mini_y, mini_w, mini_h,
                    preserveAspectRatio=True, anchor='sw')


def generate_pdf(
    labels: List[LabelData],
    config: LabelConfig,
    output_path: str
):
    """
    Generate a multi-page PDF with one label per page.

    Args:
        labels: List of LabelData (one per part)
        config: Label configuration
        output_path: Output PDF file path
    """
    page_w = config.label_width_mm * mm
    page_h = config.label_height_mm * mm

    c = canvas.Canvas(output_path, pagesize=(page_w, page_h))

    for i, label in enumerate(labels):
        if i > 0:
            c.showPage()
        _draw_label(c, label, config)

    c.save()
    print(f"PDF saved: {output_path} ({len(labels)} labels)")


if __name__ == "__main__":
    from models import EdgeBanding

    config = LabelConfig(
        operation_type="FRONTY-CIECIE-OKLEJANIE",
        company_info="PROJEKT@CNCMEBLE.PL 502963862",
        project_name="ARENA"
    )

    test_label = LabelData(
        part_number=128,
        quantity=1,
        length_mm=564,
        width_mm=299,
        material_name="ADAM - U963 SZARY DIAMENTOWY",
        project_name="ARENA",
        operation_type="FRONTY-CIECIE-OKLEJANIE",
        company_info="PROJEKT@CNCMEBLE.PL 502963862",
        edge_banding=EdgeBanding(bottom="-1x22 (MS) - 1mm")
    )

    generate_pdf([test_label], config, "test_label.pdf")
