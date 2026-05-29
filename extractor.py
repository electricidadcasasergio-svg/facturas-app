"""
Extractor de facturas PDF para Casa Sergio.
Soporta: BAW Electric, GENROD, CORESA, y formato genérico.
"""
import re
from pathlib import Path
import pdfplumber

# ── Utilidades numéricas ─────────────────────────────────────────────────────

def _parse_num(s, context='price'):
    """
    Convierte strings numéricos argentinos/USD a float.

    context='price' → "48.456,00" = 48456.0 | "6,740" (USD) = 6.74
    context='qty'   → "7,000" = 7000
    """
    if not s:
        return 0.0
    s = re.sub(r'[USD$\s%]', '', str(s)).strip()
    if not s or s == '-':
        return 0.0
    # Si es muy largo o tiene letras, no es un número
    if len(s) > 25 or re.search(r'[a-zA-Z]', s):
        return 0.0

    # Formato argentino estándar: 1.234,56
    if re.search(r'\d\.\d{3},', s):
        return float(s.replace('.', '').replace(',', '.'))

    # Formato americano: coma como miles, punto decimal: 500,118.00 / 2,000.00
    if re.match(r'^\d{1,3}(,\d{3})+(\.\d+)?$', s):
        return float(s.replace(',', ''))

    # OCR confunde punto con coma en separador de miles: "86,007,37" → "86.007,37"
    if re.match(r'^\d{1,3},\d{3},\d{2}$', s):
        p = s.split(',')
        return float(p[0] + p[1] + '.' + p[2])

    # "7,000" o "6,740" — 3 dígitos tras la coma
    if re.match(r'^\d{1,3},\d{3}$', s):
        if context == 'qty':
            return float(s.replace(',', ''))   # miles → 7000
        else:
            return float(s.replace(',', '.'))  # decimal → 6.740

    # Coma decimal simple: "1,5"
    if re.match(r'^\d+,\d{1,2}$', s):
        return float(s.replace(',', '.'))

    # Punto decimal simple: "45.4"
    try:
        return float(s)
    except ValueError:
        return 0.0


# ── Entry point ──────────────────────────────────────────────────────────────

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}

def extract_invoice(pdf_path):
    """Acepta PDF o imagen (JPG/PNG). Detecta automáticamente."""
    path = Path(pdf_path)
    if path.suffix.lower() in IMAGE_EXTS:
        return _extract_from_image(path)
    return _extract_from_pdf(path)


def _extract_from_image(path):
    """OCR sobre foto de factura. Requiere pytesseract + Tesseract instalado."""
    try:
        import pytesseract
        from PIL import Image, ImageFilter, ImageEnhance
    except ImportError:
        raise RuntimeError(
            "Para procesar imágenes instalá pytesseract:\n"
            "  py -m pip install pytesseract pillow\n"
            "Y Tesseract OCR para Windows:\n"
            "  https://github.com/UB-Mannheim/tesseract/wiki"
        )

    # Apuntar al binario de Tesseract (instalado pero no en PATH)
    import os
    tess_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    ]
    for tp in tess_paths:
        if os.path.exists(tp):
            pytesseract.pytesseract.tesseract_cmd = tp
            break

    img = Image.open(path)

    # Preprocesado: grises → upscale → contraste → sharpening
    img = img.convert('L')
    w, h = img.size
    # Tesseract funciona mejor con ~300 DPI; las fotos de WhatsApp suelen ser 96 DPI
    # Escalamos para que el lado más largo llegue a ~4000px
    scale = max(1, int(4000 / max(w, h)))
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = ImageEnhance.Sharpness(img).enhance(2.0)

    cfg = r'--oem 3 --psm 6'
    try:
        text = pytesseract.image_to_string(img, lang='spa', config=cfg)
    except Exception:
        # Fallback: idioma inglés si no está instalado el paquete español
        text = pytesseract.image_to_string(img, config=cfg)

    return _parse_full(text, path.name)


def _extract_from_pdf(path):
    """Extracción estándar desde PDF con pdfplumber."""
    with pdfplumber.open(path) as pdf:
        pages_text   = [p.extract_text() or '' for p in pdf.pages]
        pages_tables = [p.extract_tables() or [] for p in pdf.pages]

    full_text  = '\n'.join(pages_text)
    all_tables = [t for page in pages_tables for t in page]

    return _parse_full(full_text, path.name, all_tables)


def _parse_full(text, filename, tables=None):
    """Parsea header + ítems desde texto (y opcionalmente tablas pdfplumber)."""
    if tables is None:
        tables = []

    header = _parse_header(text, filename)

    # Rutear al parser del proveedor según CUIT detectado en el texto
    if '30-66180083-2' in text:
        header.setdefault('proveedor_nombre', 'BAW ELECTRIC S.A.')
        items = _items_baw(text)
    elif '30-67854721-9' in text:
        header.setdefault('proveedor_nombre', 'GEN ROD S.A.')
        items = _items_genrod(tables, text)
    elif '30-71178446-9' in text:
        header.setdefault('proveedor_nombre', 'CORESA GROUP S.R.L.')
        items = _items_coresa(tables, text)
    elif '30-65233757-7' in text:
        header.setdefault('proveedor_nombre', 'ACROPOLIS CABLES S.A. (KALOP)')
        items = _items_kalop(tables, text)
    elif '20-14772827-2' in text or '20147728272' in text:
        header.setdefault('proveedor_nombre', 'PRIOLO DANIEL ROBERTO')
        items = _items_priolo(text)
    else:
        items = _items_generic(tables, text)

    moneda = header.get('moneda', 'ARS')
    for it in items:
        it.setdefault('moneda', moneda)

    return {**header, 'items': items}


# ── Parser de cabecera (genérico) ─────────────────────────────────────────────

def _parse_header(text, filename):
    h = {'archivo_nombre': filename}

    # Número de factura — varios formatos posibles
    for pat in [
        r'N[°º]?\s*:?\s*([A-Z]-\d{5}-\d{8})',          # A-00005-00235741
        r'N[°º]\s*:\s*(\d{5}-\d{6,8})',                  # 00004-00246028
        r'Factura\s+N[°º]?:?\s*(\d{4}-\d{5,8})',         # 0006-00139834
        r'Nº\s+(\d{4}\s*-\s*\d{5,8})',                   # Nº 0005 - 00113645 (KALOP)
        r'Nro\.CONTROL:(\w+)',                             # Nro.CONTROL:0005A00113645
        r'\b([A-Z]?\d{4,5}-\d{6,8})\b',                  # fallback genérico
    ]:
        m = re.search(pat, text)
        if m:
            h['numero'] = m.group(1).strip()
            break

    # Fecha (DD/MM/YYYY)
    for pat in [
        r'(?:Fecha[^\n:]*:|FECHA:)\s*(\d{2}/\d{2}/\d{4})',
        r'(?:Fecha\s+emisi[oó]n:?\s*)(\d{2}/\d{2}/\d{4})',
        r'\bFecha:\s*(\d{2}/\d{2}/\d{4})',
        r'\b(\d{2}/\d{2}/\d{4})\b',          # fallback: primera fecha que aparezca
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            h['fecha'] = m.group(1)
            break

    # CUITs — el primero suele ser el proveedor
    cuits = re.findall(r'(\d{2}-\d{8}-\d)', text)
    if not cuits:
        # Fallback OCR: buscar 11 dígitos seguidos (CUIT sin guiones)
        raw = re.findall(r'\b(\d{11})\b', text)
        if raw:
            c = raw[0]
            cuits = [f'{c[:2]}-{c[2:10]}-{c[10]}']
    if cuits:
        h['proveedor_cuit'] = cuits[0]

    # Razón social del proveedor (si no lo detecta el parser específico)
    # Intenta varias estrategias en orden de confianza
    _nombres_por_cuit = {
        '30-66180083-2': 'BAW ELECTRIC S.A.',
        '30-67854721-9': 'GEN ROD S.A.',
        '30-71178446-9': 'CORESA GROUP S.R.L.',
        '30-65233757-7': 'ACROPOLIS CABLES S.A. (KALOP)',
        '20-14772827-2': 'PRIOLO DANIEL ROBERTO',
        '20147728272':   'PRIOLO DANIEL ROBERTO',   # sin guiones (OCR)
    }
    for cuit_known, nombre_known in _nombres_por_cuit.items():
        if cuit_known in text:
            h.setdefault('proveedor_nombre', nombre_known)
            break

    if 'proveedor_nombre' not in h:
        # Estrategia 1: "Razón Social: NOMBRE"
        m = re.search(r'Raz[oó]n\s+Social[^\n:]*:\s*([^\n]{3,60})', text, re.IGNORECASE)
        if m:
            h['proveedor_nombre'] = m.group(1).strip()

    if 'proveedor_nombre' not in h:
        # Estrategia 2: línea que termina en S.A. / S.R.L. / S.A.S. / SRL / SA
        m = re.search(
            r'^([A-ZÁÉÍÓÚÑ][^\n]{2,50}?\s+(?:S\.A\.S?|S\.R\.L\.|SRL|S\.A\.|SA|LTDA|S\.C\.S?|E\.V\.I\.C\.S\.A\.)\.?)\s*$',
            text, re.MULTILINE | re.IGNORECASE
        )
        if m:
            h['proveedor_nombre'] = m.group(1).strip()

    if 'proveedor_nombre' not in h:
        # Estrategia 3: "Nombre Apellido C.U.I.T.:" — personas físicas / monotributistas
        m = re.search(
            r'^([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]{4,50}?)\s+C\.?U\.?I\.?T\.?\s*:',
            text, re.MULTILINE
        )
        if m:
            candidate = m.group(1).strip()
            # Descartar si parece un código o dato del comprador
            if not re.match(r'^(COD|IVA|CUIT|FECHA|Señor|Se\xf1or|DOMICILIO)', candidate, re.IGNORECASE):
                h['proveedor_nombre'] = candidate

    if 'proveedor_nombre' not in h:
        # Estrategia 4: primera línea no vacía que parezca un nombre de empresa
        for line in text.split('\n'):
            line = line.strip()
            if (len(line) > 4 and len(line) < 60
                    and re.search(r'[A-ZÁÉÍÓÚÑ]{3}', line)
                    and not re.match(
                        r'^(FACTURA|REMITO|PRESUPUESTO|Fecha|CUIT|Tel|COD\.|N[°º]|IVA|INICIO)',
                        line, re.IGNORECASE)):
                h['proveedor_nombre'] = line
                break

    # Moneda y tipo de cambio
    if re.search(r'\bUSD\b', text):
        h['moneda'] = 'USD'
        m = re.search(r'USD\s*1\s*=\s*\$\s*([\d.,]+)', text)
        h['tipo_cambio'] = _parse_num(m.group(1)) if m else 1.0
    else:
        h['moneda'] = 'ARS'
        h['tipo_cambio'] = 1.0

    # CAE
    m = re.search(r'CAE[^\d]*(\d{14,18})', text)
    if m:
        h['cae'] = m.group(1)

    # Totales del pie
    # Subtotal: 1) mismo línea con número contiguo
    m = re.search(r'\bSUBTOTAL\b[^\S\n]+([\d.,]+)', text, re.IGNORECASE)
    if not m:
        # 2) línea de totales (contiene GRAVADO/PARCIAL/IMPORTE antes de SUBTOTAL)
        #    los números están en la línea siguiente
        m = re.search(
            r'(?:GRAVADO|PARCIAL|IMPORTE)[^\n]*\bSUBTOTAL\b[^\n]*\n\s*([\d.,]+)',
            text, re.IGNORECASE
        )
    if not m:
        # 3) "Subtotal: 500.00" con dos puntos o etiqueta explícita
        m = re.search(r'\bSubtotal\b\s*:\s*([\d.,]+)', text, re.IGNORECASE)
    if m:
        h['subtotal'] = _parse_num(m.group(1))

    m = re.search(r'IVA\s*21[%,°]?\s*([\d.,]+)', text, re.IGNORECASE)
    if m:
        h['iva_21'] = _parse_num(m.group(1))

    m = re.search(r'IVA\s*10[,.]?5[%,°]?\s*([\d.,]+)', text, re.IGNORECASE)
    if m:
        h['iva_105'] = _parse_num(m.group(1))

    # Total — excluir SUBTOTAL (lookbehind); tomar el mayor valor encontrado
    totales = re.findall(r'(?<![A-Za-z])TOTAL\b[^\d\n]*([\d.,]+)', text, re.IGNORECASE)
    if totales:
        h['total'] = max((_parse_num(t) for t in totales), default=0)

    return h


# ── Parser BAW ELECTRIC ───────────────────────────────────────────────────────
# Columnas: Artículo | Cantidad | DESCRIPCION | Desc.% | I.V.A.% | Precio Unit. | Neto total

def _items_baw(text):
    items = []
    lines = text.split('\n')
    in_table = False

    for line in lines:
        if re.search(r'Art[íi]culo\s+Cantidad\s+DESCRIPCION', line, re.IGNORECASE):
            in_table = True
            continue
        if not in_table:
            continue
        if re.match(r'\s*(Subtotal|TOTAL|Percepciones|CHEQUES|DOMICILIO|IVA\s*%|CAE|Impuestos)',
                    line, re.IGNORECASE):
            break

        line = line.strip()
        if not line:
            continue

        parts = line.split()
        # Primera token debe ser código de artículo (letras + dígitos, sin espacios)
        if not parts or not re.match(r'^[A-Z][A-Z0-9\-]+$', parts[0]):
            continue
        if len(parts) < 6:
            continue

        try:
            sku = parts[0]
            qty = _parse_num(parts[1], context='qty')

            # Los últimos 4 tokens numéricos son: Desc% IVA% PrecioUnit Neto
            num_re = re.compile(r'^[\d.,]+$')
            tail = []
            j = len(parts) - 1
            while j >= 2 and num_re.match(parts[j]) and len(tail) < 4:
                tail.insert(0, parts[j])
                j -= 1

            if len(tail) < 4:
                continue

            desc_pct    = _parse_num(tail[0])
            iva_pct     = _parse_num(tail[1])
            precio_unit = _parse_num(tail[2])
            neto        = _parse_num(tail[3])
            descripcion = ' '.join(parts[2:j + 1])
            precio_neto = round(precio_unit * (1 - desc_pct / 100), 4) if desc_pct else precio_unit

            items.append({
                'sku':              sku,
                'descripcion':      descripcion,
                'cantidad':         qty,
                'precio_unit':      precio_unit,
                'descuento_pct':    desc_pct,
                'precio_neto_unit': precio_neto,
                'iva_pct':          iva_pct,
                'subtotal_siva':    neto,
            })
        except Exception:
            continue

    return items


# ── Parser GENROD ─────────────────────────────────────────────────────────────
# Columnas: IT | ARTICULO | DETALLE | CANTIDAD | PRECIO | TOTAL
# Nota: pdfplumber suele fusionar toda la tabla en una celda → usamos texto primero.

def _items_genrod(tables, text):
    items = []

    # ① Parser de texto (primario)
    lines = text.split('\n')
    in_table = False
    for line in lines:
        if re.search(r'IT\s+ARTICULO\s+DETALLE', line, re.IGNORECASE):
            in_table = True
            continue
        if not in_table:
            continue
        if re.match(r'\s*(SUBTOTAL|TOTAL|El IVA|Son pesos)', line, re.IGNORECASE):
            break
        line = line.strip()
        if not line:
            continue
        # " 1.00 087402 Caja de toma 500 A c/6 bases NH T3 7,000 277.197,75 1.940.384,25"
        m = re.match(
            r'^[\d.]+\s+([A-Z0-9][A-Z0-9\-]*)\s+(.+?)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)$',
            line
        )
        if m:
            precio = _parse_num(m.group(4))
            items.append({
                'sku':              m.group(1),
                'descripcion':      m.group(2).strip(),
                'cantidad':         _parse_num(m.group(3), context='qty'),
                'precio_unit':      precio,
                'precio_neto_unit': precio,
                'descuento_pct':    0,
                'iva_pct':          21.0,
                'subtotal_siva':    _parse_num(m.group(5)),
            })

    # ② Fallback: extracción por tabla pdfplumber (si el texto no encontró nada)
    if not items:
        items = _extract_table_items(
            tables,
            header_keywords=('ARTICULO', 'DETALLE'),
            col_map={
                'sku':           ('ARTICULO',),
                'descripcion':   ('DETALLE', 'DESCRIPCION'),
                'cantidad':      ('CANTIDAD',),
                'precio_unit':   ('PRECIO',),
                'subtotal_siva': ('TOTAL',),
            },
            sku_pattern=r'^[A-Z0-9]',
            qty_context='qty',
        )
        for it in items:
            it.setdefault('precio_neto_unit', it.get('precio_unit', 0))

    for it in items:
        it.setdefault('descuento_pct', 0)
        it.setdefault('precio_neto_unit', it.get('precio_unit', 0))
        it.setdefault('iva_pct', 21.0)

    return items


# ── Parser CORESA ─────────────────────────────────────────────────────────────
# Columnas: Item | COD | Descripción | Cant. | Precio Unitario | Bon(%) | Pr.C/Dto | IVA | Subtotal s/IVA

def _items_coresa(tables, text):
    items = _extract_table_items(
        tables,
        header_keywords=('COD', 'DESCRIPCION'),
        col_map={
            'sku':              ('COD',),
            'descripcion':      ('DESCRIPCION', 'DESCRIPCI'),
            'cantidad':         ('CANT',),
            'precio_unit':      ('PRECIO UNITARIO', 'PRECIO'),
            'descuento_pct':    ('BON',),
            'precio_neto_unit': ('PR. C/DTO', 'PR.C/DTO', 'C/DTO'),
            'iva_pct':          ('IVA',),
            'subtotal_siva':    ('SUBTOTAL', 'TOTAL'),
        },
        sku_pattern=r'^[A-Z0-9]',
        qty_context='qty',
        price_context='price',   # USD usa coma decimal
    )

    # Fallback texto
    if not items:
        lines = text.split('\n')
        in_table = False
        for line in lines:
            if re.search(r'Descripci[oó]n\s+Cant', line, re.IGNORECASE):
                in_table = True
                continue
            if not in_table:
                continue
            if re.match(r'\s*(Subtotal|TOTAL|Para la cancelaci)', line, re.IGNORECASE):
                break
            line = line.strip()
            if not line:
                continue
            # "0 PER12CW DESC... 60 USD 6,740 50.00% USD 3,370 21.0% USD 202,20"
            m = re.match(
                r'^(\d+)\s+([A-Z0-9\-]+)\s+(.+?)\s+(\d+)\s+'
                r'(?:USD\s*)?([\d,]+)\s+([\d.]+)%?\s+'
                r'(?:USD\s*)?([\d,]+)\s+([\d.]+)%?\s+'
                r'(?:USD\s*)?([\d,]+)$',
                line
            )
            if m:
                items.append({
                    'sku':              m.group(2),
                    'descripcion':      m.group(3).strip(),
                    'cantidad':         _parse_num(m.group(4), context='qty'),
                    'precio_unit':      _parse_num(m.group(5)),
                    'descuento_pct':    _parse_num(m.group(6)),
                    'precio_neto_unit': _parse_num(m.group(7)),
                    'iva_pct':          _parse_num(m.group(8)),
                    'subtotal_siva':    _parse_num(m.group(9)),
                    'moneda':           'USD',
                })

    return items


# ── Parser KALOP / ACROPOLIS CABLES ──────────────────────────────────────────
# Columnas: CODIGO | UNID. | CAJ | DESCUENTOS | DETALLES | PRECIO DE LISTA | PRECIO DE VENTA | IVA% | IMPORTE NETO GRAV
# Descuentos escalonados: "47+14+10"

def _items_kalop(tables, text):
    items = []
    lines = text.split('\n')
    in_table = False

    for line in lines:
        if re.search(r'CODIGO\s+UNID', line, re.IGNORECASE):
            in_table = True
            continue
        if not in_table:
            continue
        # Fin de la tabla
        if re.match(r'\s*(PRECIO\s+DE\s+LISTA|SUBTOTAL|C\.A\.E|LA FALTA)', line, re.IGNORECASE):
            break
        # Saltar líneas del encabezado partido ("PRECIO", "DE LISTA", etc.)
        if re.match(r'^\s*(PRECIO|DE LISTA|DE VENTA|NETO GRAV|IMPORTE|\(IVA\))\s*$', line, re.IGNORECASE):
            continue

        line = line.strip()
        if not line:
            continue

        # KL02360 63 7 47+14+10 Caja de paso 170x210x75mm Bco(1ca*9u 12654,75 5191,23 21,0 327047,59
        m = re.match(
            r'^([A-Z][A-Z0-9]+)\s+'        # CODIGO
            r'(\d+)\s+'                     # UNID (cantidad)
            r'(\d+)\s+'                     # CAJ
            r'(\d+(?:\+\d+)*)\s+'          # DESCUENTOS  ej: 47+14+10
            r'(.+?)\s+'                     # DETALLES (lazy)
            r'([\d.,]+)\s+'                 # PRECIO DE LISTA
            r'([\d.,]+)\s+'                 # PRECIO DE VENTA
            r'([\d.,]+)\s+'                 # IVA%
            r'([\d.,]+)$',                  # IMPORTE NETO GRAV
            line
        )
        if m:
            precio_lista = _parse_num(m.group(6))
            precio_venta = _parse_num(m.group(7))
            dto_pct = round((1 - precio_venta / precio_lista) * 100, 2) if precio_lista else 0

            items.append({
                'sku':              m.group(1),
                'descripcion':      m.group(5).strip(),
                'cantidad':         _parse_num(m.group(2), context='qty'),
                'precio_unit':      precio_lista,
                'descuento_pct':    dto_pct,
                'precio_neto_unit': precio_venta,
                'iva_pct':          _parse_num(m.group(8)),
                'subtotal_siva':    _parse_num(m.group(9)),
            })

    # Fallback por tabla pdfplumber
    if not items:
        items = _extract_table_items(
            tables,
            header_keywords=('CODIGO', 'DESCUENTOS'),
            col_map={
                'sku':              ('CODIGO',),
                'descripcion':      ('DETALLES', 'DETALLE'),
                'cantidad':         ('UNID',),
                'precio_unit':      ('PRECIO DE LISTA', 'LISTA'),
                'precio_neto_unit': ('PRECIO DE VENTA', 'VENTA'),
                'iva_pct':          ('IVA',),
                'subtotal_siva':    ('IMPORTE', 'NETO GRAV'),
            },
            sku_pattern=r'^[A-Z][A-Z0-9]+$',
            qty_context='qty',
        )

    for it in items:
        it.setdefault('descuento_pct', 0)
        it.setdefault('precio_neto_unit', it.get('precio_unit', 0))
        it.setdefault('iva_pct', 21.0)

    return items


# ── Parser PRIOLO DANIEL ROBERTO ─────────────────────────────────────────────
# Columnas: Cantidad | Código | Descripción | Precio Unit. | Bonif. | Subtotal
# Bonif. puede ser un % ("52,50%") o sin descuento ("-").

def _items_priolo(text):
    items = []
    lines = text.split('\n')
    in_table = False

    for line in lines:
        # Detección flexible del encabezado — el OCR produce variantes como:
        #   "Cantidad C6digo _Desscripci6n Precio..."  (upscale 2x)
        #   "Cantidad) C6diga\| Descripci6n ..."       (sin upscale)
        # Buscamos fragmentos robustos: CANTIDAD + parte de CODIGO + PRECIO
        lu = line.upper()
        if ('CANTIDAD' in lu and 'DIGO' in lu
                and ('PRECIO' in lu or 'SCRIPCI' in lu)):
            in_table = True
            continue
        if not in_table:
            continue
        if re.match(
            r'\s*(Subtotal\b|TOTAL\b|IVA\b|Percepci[oó]n|Importe\s+total|'
            r'Neto\s+total|Observaci)',
            line, re.IGNORECASE
        ):
            break

        line = line.strip()
        if not line:
            continue

        # "2 121 Cañería rígida 3/4 lisa x 3mts  12.345,00  52,50%  11.727,38"
        # "1 182 Tomacorriente doble              5.678,00   -        5.678,00"
        # Tolera hasta 2 letras por OCR en el código (ej: "a2" → debería ser "182")
        # Bonif puede tener punto por OCR ("52.50%" en vez de "52,50%") y es opcional
        m = re.match(
            r'^(\d+(?:[.,]\d+)?)\s+'        # Cantidad
            r'([A-Za-z]{0,2}\d{1,6})\s+'   # Código (puede tener letra por OCR)
            r'(.+?)\s+'                      # Descripción (lazy)
            r'([\d.,]+)\s+'                  # Precio unitario
            r'(?:(-|[\d.,]+%?)\s+)?'         # Bonificación (opcional): "-" o "52,50%"
            r'([\d.,]+)$',                   # Subtotal s/IVA
            line
        )
        if m:
            bonif_str = (m.group(5) or '-').strip().rstrip('%').replace('.', ',')
            bonif      = 0.0 if bonif_str == '-' else _parse_num(bonif_str)
            precio_unit = _parse_num(m.group(4))
            precio_neto = round(precio_unit * (1 - bonif / 100), 4) if bonif else precio_unit

            items.append({
                'sku':              m.group(2),
                'descripcion':      m.group(3).strip(),
                'cantidad':         _parse_num(m.group(1), context='qty'),
                'precio_unit':      precio_unit,
                'descuento_pct':    bonif,
                'precio_neto_unit': precio_neto,
                'iva_pct':          21.0,
                'subtotal_siva':    _parse_num(m.group(6)),
            })

    return items


# ── Parser genérico ────────────────────────────────────────────────────────────

def _items_generic(tables, text):
    """Intenta tabla pdfplumber primero; si no hay nada, parsea el texto libre."""

    items = _extract_table_items(
        tables,
        header_keywords=('ARTICULO', 'CODIGO', 'COD', 'SKU'),
        col_map={
            'sku':           ('ARTICULO', 'CODIGO', 'COD', 'SKU', 'ITEM'),
            'descripcion':   ('DESCRIPCION', 'DETALLE', 'DESCRIPCI', 'DENOMINACION'),
            'cantidad':      ('CANTIDAD', 'CANT', 'QTY'),
            'precio_unit':   ('PRECIO UNIT', 'PRECIO', 'P. UNIT'),
            'subtotal_siva': ('TOTAL', 'SUBTOTAL', 'NETO', 'IMPORTE'),
        },
        sku_pattern=r'^[A-Z0-9]',
        qty_context='qty',
    )
    if items:
        return items

    return _items_generic_text(text)


def _items_generic_text(text):
    """
    Extracción genérica por texto libre.

    Principio: en cualquier factura argentina los ítems siguen el patrón
        [SKU/código]  [descripción]  [números al final: precio / subtotal]

    1. Detectar la línea de encabezado de la tabla (Código/Descripción/Precio…)
    2. Por cada línea posterior:
         a. Separar tokens numéricos del final → precios
         b. El primer token alfanumérico que parezca código → SKU
         c. El resto → descripción
    3. Parar al encontrar el pie de factura (Subtotal / Total / IVA / CAE…)
    """

    # ── Patrones de detección ─────────────────────────────────────────────────

    # Encabezado de tabla: debe mencionar algún sinónimo de "código" Y "descripción/precio"
    HDR = re.compile(
        r'(?:C[OÓ]D(?:IGO)?|SKU|ART[IÍ]CULO|PRODUCTO|ITEM)\b.{0,80}'
        r'(?:DESCRIP|DETALLE|DENOMIN|PRECIO|IMPORTE|TOTAL)',
        re.IGNORECASE
    )

    # Pie de factura → dejar de leer ítems
    FOOTER = re.compile(
        r'^\s*(?:SUB[\s-]?TOTAL|TOTAL\b|I\.?V\.?A\.?\b|PERCEP|C\.?A\.?E\.?\b|'
        r'Son\s+pesos|BONIF|CHEQUES|CONDICI[OÓ]N\s+DE\s+VENTA|VENCIM)',
        re.IGNORECASE
    )

    # Token que parece un SKU (alfanumérico, puede tener guión/punto/barra)
    SKU_RE = re.compile(r'^[A-Z0-9][A-Z0-9\-./]{0,29}$', re.IGNORECASE)

    # Palabras del lenguaje cotidiano que no son SKUs
    STOPWORDS = re.compile(
        r'^(?:DE|EL|LA|LOS|LAS|UN|UNA|Y|O|POR|CON|SIN|PARA|QUE|AL|DEL|EN|A|'
        r'NO|NI|SU|MAS|MÁS|SI|MI|ME|TE|LE|ES|HA|HI|HO|SE|SER|CON|SUS)$',
        re.IGNORECASE
    )

    NUM_RE = re.compile(r'^[\d.,]+$')

    # ── Recorrida de líneas ───────────────────────────────────────────────────

    lines = text.split('\n')
    items = []
    in_table = False

    for line in lines:
        # --- esperar el encabezado ---
        if not in_table:
            if HDR.search(line):
                in_table = True
            continue

        # --- detectar fin de tabla ---
        if FOOTER.match(line):
            break

        stripped = line.strip()
        if not stripped or len(stripped) < 4:
            continue

        tokens = stripped.split()
        if len(tokens) < 2:
            continue

        # --- separar números del lado derecho (hasta 5) ---
        # Recorremos de derecha a izquierda mientras sean numéricos puros
        split_pos = len(tokens)
        tail = []
        for k in range(len(tokens) - 1, -1, -1):
            if NUM_RE.match(tokens[k]) and len(tail) < 5:
                tail.insert(0, tokens[k])
                split_pos = k
            else:
                break

        if not tail:
            continue  # línea sin ningún número → no es ítem

        left = tokens[:split_pos]  # parte izquierda: ordinal? + qty? + unidad? + sku + descripción

        # --- identificar SKU: primer token código-like en "left" ---
        sku = None
        sku_pos = 0

        for i, tok in enumerate(left):
            # Saltar número de orden puro al inicio (1, 2, 3 … 99)
            if i == 0 and re.match(r'^\d{1,2}$', tok):
                continue
            if SKU_RE.match(tok) and not STOPWORDS.match(tok):
                sku = tok.upper()
                sku_pos = i
                break

        if not sku:
            continue

        # --- descripción: tokens después del SKU (sin % sueltos de IVA) ---
        desc_parts = left[sku_pos + 1:]
        # Quitar tokens del tipo "21.00%" o "10,5%" que son columnas de IVA/descuento
        desc_parts = [t for t in desc_parts if not re.match(r'^\d+[.,]?\d*\s*%$', t)]
        descripcion = ' '.join(desc_parts).strip()

        # --- asignar precios (de derecha a izquierda) ---
        # tail[-1] = subtotal/total  |  tail[-2] = precio unitario (si existe)
        subtotal    = _parse_num(tail[-1])
        precio_unit = _parse_num(tail[-2]) if len(tail) >= 2 else 0.0

        if precio_unit == 0 and subtotal > 0:
            precio_unit = subtotal  # un solo número → usarlo como precio

        if subtotal == 0 and precio_unit == 0:
            continue

        # --- cantidad: buscar en los tokens ANTES del SKU ---
        # Ej: "1 2,000.00 nº 56KL …" → left[0]='1'(ordinal), left[1]='2,000.00'(qty)
        qty = 1.0
        pre_sku = left[:sku_pos]
        nums_pre = [t for t in pre_sku if NUM_RE.match(t)]
        if nums_pre:
            if len(nums_pre) == 1:
                val = nums_pre[0]
                # Si es un pequeño entero (≤99) probablemente es ordinal → ignorar
                if not (re.match(r'^\d{1,2}$', val) and int(val) <= 99):
                    qty = _parse_num(val, context='qty')
            else:
                # Primer número = ordinal → el último es la cantidad real
                qty = _parse_num(nums_pre[-1], context='qty')

        items.append({
            'sku':              sku,
            'descripcion':      descripcion,
            'cantidad':         qty,
            'precio_unit':      precio_unit,
            'descuento_pct':    0.0,
            'precio_neto_unit': precio_unit,
            'iva_pct':          21.0,
            'subtotal_siva':    subtotal,
        })

    return items


# ── Helper: extracción de tabla pdfplumber ────────────────────────────────────

def _extract_table_items(tables, header_keywords, col_map,
                          sku_pattern=r'^[A-Z0-9]',
                          qty_context='qty', price_context='price'):
    """
    Recorre todas las tablas extraídas por pdfplumber buscando la que
    contenga los header_keywords. Mapea columnas según col_map y devuelve items.
    """
    items = []

    for table in tables:
        if not table or len(table) < 2:
            continue

        # Buscar fila de cabecera
        hdr_idx = None
        for i, row in enumerate(table[:6]):
            row_str = ' '.join(str(c or '') for c in row).upper()
            if all(kw in row_str for kw in header_keywords[:2]):
                hdr_idx = i
                break
        if hdr_idx is None:
            continue

        hdr = [str(c or '').strip().upper() for c in table[hdr_idx]]

        # Resolver índice de columna para cada campo
        resolved = {}
        for field, candidates in col_map.items():
            for cand in candidates:
                for j, h in enumerate(hdr):
                    if cand in h:
                        resolved[field] = j
                        break
                if field in resolved:
                    break

        if 'sku' not in resolved:
            continue

        for row in table[hdr_idx + 1:]:
            if not row:
                continue
            cells = [str(c or '').strip() for c in row]
            if not any(cells):
                continue

            sku_idx = resolved['sku']
            if sku_idx >= len(cells):
                continue
            sku = cells[sku_idx]
            if not sku or not re.match(sku_pattern, sku) or len(sku) > 40:
                continue

            it = {'sku': sku}
            for field, j in resolved.items():
                if field == 'sku' or j >= len(cells):
                    continue
                val = cells[j]
                if field == 'descripcion':
                    it[field] = val
                elif field == 'cantidad':
                    it[field] = _parse_num(val, context=qty_context)
                else:
                    it[field] = _parse_num(val, context=price_context)

            it.setdefault('descripcion', '')
            it.setdefault('cantidad', 0)
            it.setdefault('precio_unit', 0)
            it.setdefault('descuento_pct', 0)
            it.setdefault('precio_neto_unit', it['precio_unit'])
            it.setdefault('iva_pct', 21.0)
            it.setdefault('subtotal_siva', 0)
            items.append(it)

    return items
