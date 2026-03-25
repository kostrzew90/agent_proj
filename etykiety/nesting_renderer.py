"""
Nesting Renderer: generates miniature images of the sheet layout
with a highlighted part for each label.

Uses matplotlib to draw the sheet and parts, then converts to PIL Image.
"""
import io
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PIL import Image
from typing import Optional
from models import Sheet, DxfPart


def render_nesting_miniature(
    sheet: Sheet,
    highlight_part: Optional[DxfPart] = None,
    image_width_px: int = 300,
    image_height_px: int = 220,
    dpi: int = 150
) -> Image.Image:
    """
    Render a miniature view of the nesting layout.

    Args:
        sheet: Sheet with all parts
        highlight_part: The part to highlight (filled black)
        image_width_px: Output image width in pixels
        image_height_px: Output image height in pixels
        dpi: Rendering DPI

    Returns:
        PIL Image with the nesting miniature
    """
    fig_w = image_width_px / dpi
    fig_h = image_height_px / dpi
    fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), dpi=dpi)

    # Draw sheet border
    sheet_rect = patches.Rectangle(
        (0, 0), sheet.width, sheet.height,
        linewidth=1.5, edgecolor='black', facecolor='white'
    )
    ax.add_patch(sheet_rect)

    # Draw all parts
    for part in sheet.parts:
        is_highlighted = (highlight_part is not None and part.index == highlight_part.index)

        rect = patches.Rectangle(
            (part.min_x, part.min_y),
            part.width, part.height,
            linewidth=0.8 if not is_highlighted else 1.2,
            edgecolor='black',
            facecolor='black' if is_highlighted else 'white'
        )
        ax.add_patch(rect)

    # Set axis limits with small margin
    margin = sheet.width * 0.02
    ax.set_xlim(-margin, sheet.width + margin)
    ax.set_ylim(-margin, sheet.height + margin)
    ax.set_aspect('equal')
    ax.axis('off')

    plt.tight_layout(pad=0.1)

    # Convert to PIL Image
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight',
                pad_inches=0.02, facecolor='white', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).copy()
    buf.close()

    return img


def render_all_miniatures(sheet: Sheet, **kwargs) -> dict:
    """
    Render miniature for each part on the sheet.

    Returns:
        Dict mapping part index to PIL Image
    """
    miniatures = {}
    for part in sheet.parts:
        miniatures[part.index] = render_nesting_miniature(
            sheet, highlight_part=part, **kwargs
        )
    return miniatures


if __name__ == "__main__":
    import sys
    from dxf_parser import parse_dxf

    if len(sys.argv) < 2:
        print("Usage: python nesting_renderer.py <file.dxf>")
        sys.exit(1)

    sheet = parse_dxf(sys.argv[1])
    print(f"Rendering {len(sheet.parts)} miniatures...")

    miniatures = render_all_miniatures(sheet)
    for idx, img in miniatures.items():
        out_path = f"miniature_part_{idx:03d}.png"
        img.save(out_path)
        print(f"  Saved {out_path}")
