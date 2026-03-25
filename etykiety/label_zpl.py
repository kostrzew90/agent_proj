"""
ZPL Label Generator for Zebra thermal printers.

Generates ZPL II code with:
- Text fields (part number, dimensions, material, etc.)
- Embedded bitmap graphics (nesting miniature)
- Optional QR/barcode
"""
import io
import struct
from typing import List
from PIL import Image
from models import LabelData, LabelConfig


def _image_to_zpl_graphic(
    img: Image.Image,
    target_width_dots: int = 200,
    target_height_dots: int = 150
) -> str:
    """
    Convert PIL Image to ZPL ^GFA (Graphic Field ASCII) command.

    Converts image to 1-bit bitmap and encodes as hex for ZPL.
    """
    # Resize to target dimensions
    img = img.resize((target_width_dots, target_height_dots), Image.LANCZOS)

    # Convert to 1-bit (black and white)
    img = img.convert('1')

    # ZPL bitmap format: each row is padded to byte boundary
    bytes_per_row = (target_width_dots + 7) // 8
    total_bytes = bytes_per_row * target_height_dots

    hex_data = []
    for y in range(target_height_dots):
        row_bytes = []
        for byte_idx in range(bytes_per_row):
            byte_val = 0
            for bit in range(8):
                x = byte_idx * 8 + bit
                if x < target_width_dots:
                    pixel = img.getpixel((x, y))
                    # In ZPL: 1 = black, 0 = white (inverted from PIL '1' mode)
                    if pixel == 0:  # black pixel in PIL
                        byte_val |= (1 << (7 - bit))
            row_bytes.append(byte_val)
        hex_data.append(''.join(f'{b:02X}' for b in row_bytes))

    hex_string = ''.join(hex_data)

    return f"^GFA,{total_bytes},{total_bytes},{bytes_per_row},{hex_string}"


def generate_zpl_label(
    label: LabelData,
    config: LabelConfig
) -> str:
    """
    Generate ZPL code for a single label.

    Args:
        label: Label data
        config: Label configuration

    Returns:
        ZPL string ready to send to printer
    """
    dpi = config.zpl_dpi
    dots_per_mm = dpi / 25.4
    lw = int(config.zpl_label_width_mm * dots_per_mm)
    lh = int(config.zpl_label_height_mm * dots_per_mm)

    def mm2d(val_mm):
        return int(val_mm * dots_per_mm)

    zpl = []
    zpl.append("^XA")
    zpl.append(f"^PW{lw}")
    zpl.append(f"^LL{lh}")
    zpl.append("^LH0,0")

    # ── Part number (large, in black box) ──
    box_x, box_y = mm2d(2), mm2d(2)
    box_w, box_h = mm2d(18), mm2d(22)
    zpl.append(f"^FO{box_x},{box_y}^GB{box_w},{box_h},box_h,B^FS")
    # White text on black
    zpl.append(f"^FO{box_x + mm2d(2)},{box_y + mm2d(2)}")
    zpl.append(f"^A0N,{mm2d(14)},{mm2d(10)}")
    zpl.append(f"^FR^FD{label.part_number}^FS")

    # ── Quantity ──
    zpl.append(f"^FO{mm2d(1)},{box_y + box_h + mm2d(2)}")
    zpl.append(f"^A0N,{mm2d(8)},{mm2d(6)}^FD{label.quantity}^FS")

    # ── Operation type ──
    zpl.append(f"^FO{mm2d(24)},{mm2d(2)}")
    zpl.append(f"^A0N,{mm2d(4)},{mm2d(3)}^FD{label.operation_type}^FS")

    # ── Company info ──
    zpl.append(f"^FO{mm2d(24)},{mm2d(8)}")
    zpl.append(f"^A0N,{mm2d(3)},{mm2d(2)}^FD{label.company_info}^FS")

    # ── Dimensions ──
    zpl.append(f"^FO{lw - mm2d(22)},{mm2d(2)}")
    zpl.append(f"^A0N,{mm2d(8)},{mm2d(6)}^FD{label.length_mm:.0f}^FS")
    zpl.append(f"^FO{lw - mm2d(22)},{mm2d(10)}")
    zpl.append(f"^A0N,{mm2d(8)},{mm2d(6)}^FD{label.width_mm:.0f}^FS")

    # ── Horizontal separator ──
    zpl.append(f"^FO{mm2d(22)},{mm2d(18)}^GB{lw - mm2d(24)},1,1^FS")

    # ── Material name ──
    zpl.append(f"^FO{mm2d(24)},{mm2d(20)}")
    zpl.append(f"^A0N,{mm2d(5)},{mm2d(3)}^FD{label.material_name}^FS")

    # ── Separator ──
    zpl.append(f"^FO{mm2d(22)},{mm2d(28)}^GB{lw - mm2d(24)},1,1^FS")

    # ── Project name (large) ──
    zpl.append(f"^FO{mm2d(40)},{mm2d(30)}")
    zpl.append(f"^A0N,{mm2d(10)},{mm2d(8)}^FD{label.project_name}^FS")

    # ── Separator ──
    zpl.append(f"^FO{mm2d(22)},{mm2d(42)}^GB{lw - mm2d(24)},1,1^FS")

    # ── Edge banding ──
    eb = label.edge_banding
    edge_y = mm2d(44)
    edge_spacing = mm2d(5)
    edge_lines = []
    if eb.top:
        edge_lines.append(f"^ {eb.top}")
    if eb.bottom:
        edge_lines.append(f"v {eb.bottom}")
    if eb.left:
        edge_lines.append(f"< {eb.left}")
    if eb.right:
        edge_lines.append(f"> {eb.right}")

    for i, line in enumerate(edge_lines):
        zpl.append(f"^FO{mm2d(24)},{edge_y + i * edge_spacing}")
        zpl.append(f"^A0N,{mm2d(4)},{mm2d(3)}^FD{line}^FS")

    # ── Nesting miniature (bitmap) ──
    if label.nesting_image:
        mini_w_dots = mm2d(20)
        mini_h_dots = mm2d(15)
        gf_cmd = _image_to_zpl_graphic(label.nesting_image, mini_w_dots, mini_h_dots)
        zpl.append(f"^FO{mm2d(1)},{mm2d(32)}{gf_cmd}^FS")

    # ── QR Code (optional) ──
    qr_data = f"{label.part_number}|{label.length_mm:.0f}x{label.width_mm:.0f}"
    zpl.append(f"^FO{lw - mm2d(18)},{lh - mm2d(18)}")
    zpl.append(f"^BQN,2,3^FDQA,{qr_data}^FS")

    zpl.append("^XZ")

    return "\n".join(zpl)


def generate_zpl_file(
    labels: List[LabelData],
    config: LabelConfig,
    output_path: str
):
    """
    Generate a ZPL file with all labels.

    Args:
        labels: List of LabelData
        config: Label configuration
        output_path: Output file path (.zpl)
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        for label in labels:
            zpl = generate_zpl_label(label, config)
            f.write(zpl)
            f.write("\n\n")

    print(f"ZPL saved: {output_path} ({len(labels)} labels)")


if __name__ == "__main__":
    print("Use main.py to run the full pipeline.")
