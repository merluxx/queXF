#!/usr/bin/env python3
"""
Reconstruit des PDF remplis depuis les questionnaires vérifiés queXF.

Le script :
- prend un qid en paramètre ;
- cherche toutes les entrées dans forms avec ce qid et done=1 ;
- lit les réponses vérifiées dans formboxes / formboxverifytext / formboxverifychar ;
- lit les emplacements des cases/champs depuis le fichier queXF banding XML ;
- dessine les coches et les textes sur une copie du PDF original non rempli.

Dépendances :
    pip install pymysql pypdf reportlab

Exemple :
    python main.py 481332 \
      --db-host localhost \
      --db-user quexf \
      --db-password secret \
      --db-name quexf \
      --pdf quexmlpdf_481332_fr.pdf \
      --banding quexf_banding_481332_fr.xml \
      --out output
"""

from __future__ import annotations

import argparse
import io
import os
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pymysql
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader


# Coordonnées queXF habituelles pour A4 300 DPI.
# Le XML contient généralement des coordonnées image, pas des points PDF.
QUEXF_A4_IMAGE_WIDTH = 2480
QUEXF_A4_IMAGE_HEIGHT = 3508

CHECKBOX_TYPES = {1, 2}
TEXT_TYPES = {3, 4, 6}
DEFAULT_FILLED_THRESHOLD = 0.5


@dataclass(frozen=True)
class Box:
    xml_bid: int
    page_index: int
    group_type: int
    varname: str
    value: str
    tlx: float
    tly: float
    brx: float
    bry: float


@dataclass(frozen=True)
class Form:
    fid: int
    qid: int
    description: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère des PDF remplis à partir des formulaires queXF vérifiés."
    )
    parser.add_argument("qid", type=int, help="Questionnaire ID à exporter")

    parser.add_argument("--db-host", default=os.getenv("QUEXF_DB_HOST", "localhost"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("QUEXF_DB_PORT", "3306")))
    parser.add_argument("--db-user", default=os.getenv("QUEXF_DB_USER", "root"))
    parser.add_argument("--db-password", default=os.getenv("QUEXF_DB_PASSWORD", ""))
    parser.add_argument("--db-name", default=os.getenv("QUEXF_DB_NAME", "quexf"))

    parser.add_argument(
        "--pdf",
        default="quexml.pdf",
        help="PDF original non rempli. Exemple : quexmlpdf_481332_fr.pdf",
    )
    parser.add_argument(
        "--banding",
        required=True,
        help="Fichier XML de banding queXF. Exemple : quexf_banding_481332_fr.xml",
    )
    parser.add_argument("--out", default="output", help="Dossier de sortie")
    parser.add_argument(
        "--filled-threshold",
        type=float,
        default=DEFAULT_FILLED_THRESHOLD,
        help="Seuil formboxes.filled à partir duquel une case est considérée cochée",
    )
    parser.add_argument(
        "--all-checkboxes-from-db",
        action="store_true",
        help=(
            "Si activé, utilise formboxes.filled pour cocher les cases. "
            "Sinon, utilise les valeurs vérifiées quand disponibles, puis formboxes."
        ),
    )
    parser.add_argument(
        "--add-scanned",
        action="store_true",
        help="Ajoute le scan à droite de la page remplie",
    )

    return parser.parse_args()


def connect_db(args: argparse.Namespace):
    return pymysql.connect(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=args.db_password,
        database=args.db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def get_verified_forms(conn, qid: int) -> List[Form]:
    sql = """
        SELECT fid, qid, description
        FROM forms
        WHERE qid = %s AND done = 1
        ORDER BY fid
    """
    with conn.cursor() as cur:
        cur.execute(sql, (qid,))
        rows = cur.fetchall()

    return [
        Form(
            fid=int(row["fid"]),
            qid=int(row["qid"]),
            description=row.get("description") or "",
        )
        for row in rows
    ]


def parse_banding_xml(path: str | Path) -> List[Box]:
    tree = ET.parse(path)
    root = tree.getroot()

    boxes: List[Box] = []
    xml_bid = 1

    pages = root.findall(".//questionnaire/page")
    for page_index, page in enumerate(pages):
        for group in page.findall("boxgroup"):
            group_type = int((group.findtext("type") or "0").strip())
            varname = (group.findtext("varname") or "").strip()

            for box in group.findall("box"):
                boxes.append(
                    Box(
                        xml_bid=xml_bid,
                        page_index=page_index,
                        group_type=group_type,
                        varname=varname,
                        value=(box.findtext("value") or "").strip(),
                        tlx=float((box.findtext("tlx") or "0").strip()),
                        tly=float((box.findtext("tly") or "0").strip()),
                        brx=float((box.findtext("brx") or "0").strip()),
                        bry=float((box.findtext("bry") or "0").strip()),
                    )
                )
                xml_bid += 1

    return boxes


def get_db_boxes_for_qid(conn, qid: int) -> List[dict]:
    """
    Récupère les boxes queXF depuis la base.

    Important :
    - les identifiants bid de la base sont ceux utilisés par formboxes,
      formboxverifytext et formboxverifychar ;
    - le XML de banding ne contient généralement pas bid ;
    - on associe donc XML <-> DB par ordre naturel : page, sortorder, box.
    """
    sql = """
        SELECT
            b.bid,
            b.tlx,
            b.tly,
            b.brx,
            b.bry,
            b.value,
            b.label,
            b.pid,
            b.bgid,
            bgt.btid,
            bgt.varname,
            bgt.sortorder,
            p.pidentifierval
        FROM boxes b
        INNER JOIN boxgroupstype bgt ON b.bgid = bgt.bgid
        INNER JOIN pages p ON b.pid = p.pid
        WHERE p.qid = %s
        ORDER BY p.pidentifierval, bgt.sortorder, b.bid
    """
    with conn.cursor() as cur:
        cur.execute(sql, (qid,))
        return list(cur.fetchall())


def build_box_id_mapping(xml_boxes: List[Box], db_boxes: List[dict]) -> Dict[int, Box]:
    """
    Retourne un mapping bid DB -> Box XML.

    On suppose que la structure de banding XML et la structure en DB sont issues
    du même questionnaire et sont donc dans le même ordre.
    """
    if len(xml_boxes) != len(db_boxes):
        print_box_differences(xml_boxes, db_boxes)

        raise RuntimeError(
            "Le nombre de boxes dans le XML ne correspond pas au nombre de boxes en base : "
            f"XML={len(xml_boxes)}, DB={len(db_boxes)}. "
            "Les différences ont été affichées ci-dessus."
        )

    mapping: Dict[int, Box] = {}
    for xml_box, db_box in zip(xml_boxes, db_boxes):
        mapping[int(db_box["bid"])] = xml_box

    return mapping


def normalize_box_value(value) -> str:
    return str(value or "").strip()


def xml_box_key(box: Box) -> tuple:
    return (
        box.page_index,
        box.group_type,
        normalize_box_value(box.varname),
        int(round(box.tlx)),
        int(round(box.tly)),
        int(round(box.brx)),
        int(round(box.bry)),
        normalize_box_value(box.value),
    )


def db_box_key(row: dict) -> tuple:
    page_identifier = str(row.get("pidentifierval") or "")
    page_index = guess_page_index_from_identifier(page_identifier)

    return (
        page_index,
        int(row.get("btid") or 0),
        normalize_box_value(row.get("varname")),
        int(round(float(row.get("tlx") or 0))),
        int(round(float(row.get("tly") or 0))),
        int(round(float(row.get("brx") or 0))),
        int(round(float(row.get("bry") or 0))),
        normalize_box_value(row.get("value")),
    )


def guess_page_index_from_identifier(page_identifier: str) -> int:
    """
    Convertit un pidentifierval queXF en index de page 0-based.

    Exemple :
        48133201 -> 0
        48133202 -> 1
    """
    if len(page_identifier) >= 2 and page_identifier[-2:].isdigit():
        return int(page_identifier[-2:]) - 1

    return -1


def print_box_differences(xml_boxes: List[Box], db_boxes: List[dict]) -> None:
    xml_by_key: Dict[tuple, List[Box]] = {}
    db_by_key: Dict[tuple, List[dict]] = {}

    for box in xml_boxes:
        xml_by_key.setdefault(xml_box_key(box), []).append(box)

    for row in db_boxes:
        db_by_key.setdefault(db_box_key(row), []).append(row)

    xml_keys = set(xml_by_key)
    db_keys = set(db_by_key)

    only_xml_keys = sorted(xml_keys - db_keys)
    only_db_keys = sorted(db_keys - xml_keys)

    print()
    print("========== DIFFÉRENCES BOXES XML / BASE ==========")
    print(f"Nombre de boxes XML  : {len(xml_boxes)}")
    print(f"Nombre de boxes base : {len(db_boxes)}")
    print(f"En plus dans XML     : {sum(len(xml_by_key[k]) for k in only_xml_keys)}")
    print(f"En plus dans base    : {sum(len(db_by_key[k]) for k in only_db_keys)}")
    print()

    if only_xml_keys:
        print("----- Boxes présentes dans le XML mais absentes de la base -----")
        for key in only_xml_keys:
            for box in xml_by_key[key]:
                print(
                    "XML "
                    f"page={box.page_index + 1}, "
                    f"type={box.group_type}, "
                    f"varname={box.varname!r}, "
                    f"value={box.value!r}, "
                    f"coords=({box.tlx}, {box.tly}, {box.brx}, {box.bry})"
                )
        print()

    if only_db_keys:
        print("----- Boxes présentes dans la base mais absentes du XML -----")
        for key in only_db_keys:
            for row in db_by_key[key]:
                print(
                    "DB  "
                    f"bid={row.get('bid')}, "
                    f"page={row.get('pidentifierval')}, "
                    f"type={row.get('btid')}, "
                    f"varname={row.get('varname')!r}, "
                    f"value={normalize_box_value(row.get('value'))!r}, "
                    f"coords=({row.get('tlx')}, {row.get('tly')}, {row.get('brx')}, {row.get('bry')})"
                )
        print()

    print("==================================================")
    print()


def get_checked_bid_set(conn, fid: int, filled_threshold: float) -> set[int]:
    sql = """
        SELECT bid
        FROM formboxes
        WHERE fid = %s AND filled >= %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (fid, filled_threshold))
        return {int(row["bid"]) for row in cur.fetchall()}


def get_verified_text_by_bid(conn, fid: int) -> Dict[int, str]:
    """
    Texte vérifié pour les champs de type texte / long texte.
    Plusieurs lignes possibles : on garde la dernière saisie par bid.
    """
    sql = """
        SELECT bid, val
        FROM formboxverifytext
        WHERE fid = %s
        ORDER BY fbvtid
    """
    result: Dict[int, str] = {}

    with conn.cursor() as cur:
        cur.execute(sql, (fid,))
        for row in cur.fetchall():
            result[int(row["bid"])] = row["val"] or ""

    return result


def get_verified_chars_by_bid(conn, fid: int) -> Dict[int, str]:
    """
    Caractères vérifiés pour les champs numériques / champs découpés en cases.

    Chaque bid correspond généralement à un caractère.
    """
    sql = """
        SELECT bid, val
        FROM formboxverifychar
        WHERE fid = %s
        ORDER BY fbvcid
    """
    result: Dict[int, str] = {}

    with conn.cursor() as cur:
        cur.execute(sql, (fid,))
        for row in cur.fetchall():
            result[int(row["bid"])] = row["val"] or ""

    return result


def get_verified_choice_values(conn, fid: int) -> Dict[str, set[str]]:
    """
    Déduit les choix vérifiés depuis les tables de vérification texte/caractère.

    Selon les installations queXF, les choix peuvent être disponibles via :
    - formboxes.filled ;
    - ou via les valeurs exportées par groupe/varname dans les tables verify.

    Comme les tables attachent surtout bid/fid/val, ce script utilise d'abord
    formboxes pour les cases, qui est le plus direct et fiable.
    """
    return {}


def xml_to_pdf_rect(
    box: Box,
    page_width: float,
    page_height: float,
    image_width: float = QUEXF_A4_IMAGE_WIDTH,
    image_height: float = QUEXF_A4_IMAGE_HEIGHT,
) -> Tuple[float, float, float, float]:
    """
    Convertit les coordonnées image queXF vers coordonnées PDF ReportLab.

    queXF :
        origine en haut-gauche, y vers le bas.
    PDF :
        origine en bas-gauche, y vers le haut.
    """
    x1 = box.tlx / image_width * page_width
    x2 = box.brx / image_width * page_width

    y_top = page_height - (box.tly / image_height * page_height)
    y_bottom = page_height - (box.bry / image_height * page_height)

    return x1, y_bottom, x2, y_top


def draw_checkmark(c: canvas.Canvas, x1: float, y1: float, x2: float, y2: float) -> None:
    width = x2 - x1
    height = y2 - y1

    pad_x = width * 0.18
    pad_y = height * 0.18

    c.setLineWidth(max(1.2, min(width, height) * 0.08))
    c.line(x1 + pad_x, y1 + height * 0.48, x1 + width * 0.42, y1 + pad_y)
    c.line(x1 + width * 0.42, y1 + pad_y, x2 - pad_x, y2 - pad_y)

def draw_cross(c: canvas.Canvas, x1: float, y1: float, x2: float, y2: float) -> None:
    width = x2 - x1
    height = y2 - y1

    c.setLineWidth(max(1.2, min(width, height) * 0.08))
    c.line(x1, y1, x2, y2)
    c.line(x1, y2, x2, y1)

def wrap_text_to_width(text: str, max_width: float, font_name: str, font_size: float) -> List[str]:
    lines: List[str] = []

    for paragraph in str(text).splitlines() or [""]:
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue

        current = ""
        for word in paragraph.split():
            candidate = word if not current else f"{current} {word}"
            if stringWidth(candidate, font_name, font_size) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word

        if current:
            lines.append(current)

    return lines


def draw_text_in_box(
    c: canvas.Canvas,
    text: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    font_name: str = "Helvetica",
    font_size: float = 9,
) -> None:
    if not text:
        return

    max_width = max(10, x2 - x1 - 4)
    line_height = font_size * 1.25
    lines = wrap_text_to_width(text, max_width, font_name, font_size)

    c.setFont(font_name, font_size)

    y = y2 - font_size - 2
    min_y = y1 + 2

    for line in lines:
        if y < min_y:
            break
        c.drawString(x1 + 2, y, line)
        y -= line_height


def create_overlay_pdf(
    original_reader: PdfReader,
    boxes_by_db_bid: Dict[int, Box],
    checked_bids: set[int],
    text_by_bid: Dict[int, str],
    char_by_bid: Dict[int, str],
) -> PdfReader:
    packet = io.BytesIO()
    c = canvas.Canvas(packet)

    page_count = len(original_reader.pages)

    for page_index in range(page_count):
        page = original_reader.pages[page_index]
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)

        c.setPageSize((page_width, page_height))
        c.setStrokeColorRGB(0, 0, 0)
        c.setFillColorRGB(0, 0, 0)

        for bid, box in boxes_by_db_bid.items():
            if box.page_index != page_index:
                continue

            x1, y1, x2, y2 = xml_to_pdf_rect(box, page_width, page_height)

            if box.group_type in CHECKBOX_TYPES:
                checkbox_value = str(char_by_bid.get(bid, "")).strip().lower()

                if bid in checked_bids or checkbox_value in {"1", "x", "true", "yes", "oui"}:
                    draw_cross(c, x1, y1, x2, y2)

            elif box.group_type in TEXT_TYPES:
                value = text_by_bid.get(bid)
                if value is None:
                    value = char_by_bid.get(bid, "")

                if value:
                    font_size = 10 if box.group_type in {3, 4} else 9
                    draw_text_in_box(c, value, x1, y1, x2, y2, font_size=font_size)

            elif bid in char_by_bid:
                draw_text_in_box(c, char_by_bid[bid], x1, y1, x2, y2, font_size=10)

        c.showPage()

    c.save()
    packet.seek(0)
    return PdfReader(packet)


def merge_overlay(original_pdf_path: str | Path, overlay_reader: PdfReader, output_path: str | Path) -> None:
    original_reader = PdfReader(str(original_pdf_path))
    writer = PdfWriter()

    for i, page in enumerate(original_reader.pages):
        if i < len(overlay_reader.pages):
            page.merge_page(overlay_reader.pages[i])
        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)


def safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value.strip())
    return cleaned[:120] or "formulaire"


def export_form_pdf(
    conn,
    form: Form,
    original_pdf_path: str | Path,
    boxes_by_db_bid: Dict[int, Box],
    out_dir: str | Path,
    filled_threshold: float,
    add_scanned: bool = False,
) -> Path:
    original_reader = PdfReader(str(original_pdf_path), strict=False)

    checked_bids = get_checked_bid_set(conn, form.fid, filled_threshold)
    text_by_bid = get_verified_text_by_bid(conn, form.fid)
    char_by_bid = get_verified_chars_by_bid(conn, form.fid)

    overlay_reader = create_overlay_pdf(
        original_reader=original_reader,
        boxes_by_db_bid=boxes_by_db_bid,
        checked_bids=checked_bids,
        text_by_bid=text_by_bid,
        char_by_bid=char_by_bid,
    )

    if add_scanned:
        sql = """
              SELECT pid, filename, image
              FROM formpages
              WHERE fid = %s
              ORDER BY pid \
              """

        with conn.cursor() as cur:
            cur.execute(sql, (form.fid,))
            form_pages = list(cur.fetchall())

        packet = io.BytesIO()
        c = canvas.Canvas(packet)

        page_count = len(original_reader.pages)

        for page_index in range(page_count):
            page = original_reader.pages[page_index]

            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)

            # PDF final : original à gauche + scan à droite
            c.setPageSize((page_width, page_height))

            # Image scannée correspondante par ordre SQL
            if page_index < len(form_pages):
                form_page = form_pages[page_index]
                scanned_image_data = io.BytesIO(form_page["image"])
                scanned_image = Image.open(scanned_image_data)

                if scanned_image.mode != "RGB":
                    scanned_image = scanned_image.convert("RGB")

                img_reader = ImageReader(scanned_image)
                c.drawImage(
                    img_reader,
                    0,
                    0,
                    width=page_width,
                    height=page_height,
                    preserveAspectRatio=False,
                    mask='auto'
                )

            c.showPage()

        c.save()
        packet.seek(0)

        scanned_overlay_reader = PdfReader(packet, strict=False)

        # Construction finale
        writer = PdfWriter()
        filename_description = safe_filename(form.description)

        for i, original_page in enumerate(original_reader.pages):

            # nouvelle page double largeur
            from pypdf import PageObject

            new_page = PageObject.create_blank_page(
                width=float(original_page.mediabox.width) * 2,
                height=float(original_page.mediabox.height),
            )

            # page originale à gauche
            try:
                new_page.merge_translated_page(original_page, 0, 0)
            except Exception as e:
                print(f"Erreur {filename_description} page {i}: {e}")

            # scan à droite
            if i < len(scanned_overlay_reader.pages):
                try:
                    new_page.merge_translated_page(
                        scanned_overlay_reader.pages[i],
                        float(original_page.mediabox.width),
                        0,
                    )
                except Exception as e:
                    print(f"Erreur {filename_description} page {i}: {e}")

            # overlay réponses
            if i < len(overlay_reader.pages):
                new_page.merge_page(overlay_reader.pages[i])

            writer.add_page(new_page)



        output_path = (
                Path(out_dir)
                / f"qid_{form.qid}_fid_{form.fid}_{filename_description}.pdf"
        )

        with open(output_path, "wb") as f:
            writer.write(f)

        return output_path

    filename_description = safe_filename(form.description)
    output_path = Path(out_dir) / f"qid_{form.qid}_fid_{form.fid}_{filename_description}.pdf"

    if not add_scanned:
        merge_overlay(original_pdf_path, overlay_reader, output_path)

    return output_path


def main() -> None:
    args = parse_args()

    original_pdf_path = Path(args.pdf)
    banding_path = Path(args.banding)
    out_dir = Path(args.out)

    if not original_pdf_path.exists():
        raise FileNotFoundError(f"PDF original introuvable : {original_pdf_path}")

    if not banding_path.exists():
        raise FileNotFoundError(f"Banding XML introuvable : {banding_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    xml_boxes = parse_banding_xml(banding_path)

    with connect_db(args) as conn:
        forms = get_verified_forms(conn, args.qid)

        if not forms:
            print(f"Aucun formulaire vérifié trouvé pour qid={args.qid}")
            return

        db_boxes = get_db_boxes_for_qid(conn, args.qid)
        boxes_by_db_bid = build_box_id_mapping(xml_boxes, db_boxes)

        print(f"{len(forms)} formulaire(s) vérifié(s) trouvé(s) pour qid={args.qid}")

        for form in forms:
            output_path = export_form_pdf(
                conn=conn,
                form=form,
                original_pdf_path=original_pdf_path,
                boxes_by_db_bid=boxes_by_db_bid,
                out_dir=out_dir,
                filled_threshold=args.filled_threshold,
                add_scanned=args.add_scanned,
            )
            print(f"PDF généré : {output_path}")


if __name__ == "__main__":
    main()
