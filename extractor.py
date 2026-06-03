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


# ── CUITs propios de Casa Sergio (nunca son el proveedor) ────────────────────
# Si alguno de estos aparece en la factura, es el COMPRADOR, no el vendedor.
# El primer CUIT que NO esté en este set es el proveedor.
_OWN_CUITS = {
    '20-14018158-8',   # Milne Sergio Gustavo (persona física)
    '30-71662001-4',   # Electro Casa Sergio SRL
}


# ── Entry point ──────────────────────────────────────────────────────────────

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}

def quick_get_cuit(pdf_path):
    """
    Escaneo rápido de la primera página para obtener el CUIT.
    Se usa ANTES de la extracción completa para cargar el config del proveedor.
    """
    try:
        path = Path(pdf_path)
        if path.suffix.lower() in IMAGE_EXTS:
            return None
        with pdfplumber.open(path) as pdf:
            text = (pdf.pages[0].extract_text() or '') if pdf.pages else ''
        cuits = re.findall(r'\d{2}-\d{8}-\d', text)
        return cuits[0] if cuits else None
    except Exception:
        return None


def extract_invoice(pdf_path, config=None):
    """
    Acepta PDF o imagen (JPG/PNG). Detecta automáticamente.
    config: dict con perfil del proveedor (aprendido de facturas anteriores).
    """
    path = Path(pdf_path)
    if path.suffix.lower() in IMAGE_EXTS:
        return _extract_from_image(path)
    return _extract_from_pdf(path, config=config)


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


def _extract_from_pdf(path, config=None):
    """Extracción estándar desde PDF con pdfplumber."""
    with pdfplumber.open(path) as pdf:
        pages_text   = [p.extract_text() or '' for p in pdf.pages]
        pages_tables = [p.extract_tables() or [] for p in pdf.pages]

    full_text  = '\n'.join(pages_text)
    all_tables = [t for page in pages_tables for t in page]

    return _parse_full(full_text, path.name, all_tables, config=config)


def _parse_full(text, filename, tables=None, config=None):
    """Parsea header + ítems desde texto (y opcionalmente tablas pdfplumber)."""
    if tables is None:
        tables = []

    header = _parse_header(text, filename)

    discovered_config = {}   # se llenará si se usa el parser genérico

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
        header_hint = config.get('header_trigger') if config else None
        items = _items_generic(tables, text,
                               header_hint=header_hint,
                               discovered=discovered_config)

    moneda = header.get('moneda', 'ARS')
    for it in items:
        it.setdefault('moneda', moneda)

    result = {**header, 'items': items}
    if discovered_config:
        result['_discovered_config'] = discovered_config
    return result


# ── Parser de cabecera (genérico) ─────────────────────────────────────────────

def _parse_header(text, filename):
    h = {'archivo_nombre': filename}

    # ── Separar la sección del PROVEEDOR de la del COMPRADOR ─────────────────
    # En una factura argentina el vendedor va PRIMERO y luego los datos del
    # cliente aparecen tras líneas como "Señor(es):", "Cliente:", "Sr.(es):", etc.
    # Solo buscamos nombre y CUIT del proveedor ANTES de esa línea divisoria.
    _BUYER_RE = re.compile(
        r'^(?:'
        r'Se[ñn]ore?s?\s*[:(]|'          # Señor(es): / Señores:
        r'Sr\.\s*\(?es\)?[\s:]|'           # Sr.(es): / Sr.:
        r'A\s*:|'                           # A:
        r'Cliente\s*[:\d(]|'               # Cliente: / Cliente 16987
        r'Comprador\s*:|'
        r'Receptor\s*:|'
        r'DATOS\s+DEL\s+(?:RECEPTOR|CLIENTE)|'
        r'Nombre\s+del\s+[Cc]liente'
        r')',
        re.MULTILINE | re.IGNORECASE
    )
    buyer_m  = _BUYER_RE.search(text)
    sup_text = text[:buyer_m.start()] if buyer_m else text
    # Si la sección del proveedor quedó muy corta, usamos todo el texto como fallback
    if len(sup_text.strip()) < 40:
        sup_text = text

    # Palabras que indican que una línea pertenece al comprador, no al proveedor
    _BUYER_LINE = re.compile(
        r'^(?:Se[ñn]or|Sr\.|Cliente|Comprador|Receptor|Direcci[oó]n|'
        r'Localidad|Condici[oó]n|Domicilio|IVA\s*:|CUIT\s*N[°º]|'
        r'Cod\.?\s*Cliente|C\.P\.|Tel[eé]fono)',
        re.IGNORECASE
    )

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

    # Fecha (DD/MM/YYYY) — buscar en todo el texto
    for pat in [
        r'(?:Fecha[^\n:]*:|FECHA:)\s*(\d{2}/\d{2}/\d{4})',
        r'(?:Fecha\s+emisi[oó]n:?\s*)(\d{2}/\d{2}/\d{4})',
        r'\bFecha:\s*(\d{2}/\d{2}/\d{4})',
        r'\b(\d{2}/\d{2}/\d{4})\b',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            h['fecha'] = m.group(1)
            break

    # CUITs — excluir los CUITs propios de Casa Sergio; el primero restante es el proveedor
    def _prov_cuits_from(src):
        found = re.findall(r'(\d{2}-\d{8}-\d)', src)
        return [c for c in found if c not in _OWN_CUITS]

    prov_cuits = _prov_cuits_from(text)   # buscar en TODO el texto
    if not prov_cuits:
        # Fallback OCR: 11 dígitos sin guiones
        for raw in re.findall(r'\b(\d{11})\b', text):
            norm = f'{raw[:2]}-{raw[2:10]}-{raw[10]}'
            if norm not in _OWN_CUITS:
                prov_cuits = [norm]
                break
    if prov_cuits:
        h['proveedor_cuit'] = prov_cuits[0]

    # ── Detectar facturas de VENTA (emitidas por Casa Sergio) ───────────────
    # Si el primer CUIT del documento (el del emisor/vendedor) es propio,
    # esta factura la emitió Casa Sergio → es una VENTA, no una compra.
    primer_cuit = None
    mfirst = re.search(r'(\d{2}-\d{8}-\d)', text)
    if mfirst:
        primer_cuit = mfirst.group(1)
    es_venta_propia = (
        primer_cuit in _OWN_CUITS
        or re.search(r'(?:Electricidad e iluminaci[oó]n|de\s+Sergio\s+Gustavo\s+Milne|'
                     r'ELECTRO\s+CASA\s+SERGIO)', text[:400], re.IGNORECASE) is not None
    )
    if es_venta_propia:
        h['es_venta'] = True

    # Razón social del proveedor — varios intentos en orden de confianza
    _nombres_por_cuit = {
        '30-66180083-2': 'BAW ELECTRIC S.A.',
        '30-67854721-9': 'GEN ROD S.A.',
        '30-71178446-9': 'CORESA GROUP S.R.L.',
        '30-65233757-7': 'ACROPOLIS CABLES S.A. (KALOP)',
        '20-14772827-2': 'PRIOLO DANIEL ROBERTO',
        '20147728272':   'PRIOLO DANIEL ROBERTO',
    }
    for cuit_known, nombre_known in _nombres_por_cuit.items():
        if cuit_known in text:
            h.setdefault('proveedor_nombre', nombre_known)
            break

    if 'proveedor_nombre' not in h:
        # Estrategia 1: etiqueta explícita "Razón Social:"
        m = re.search(r'Raz[oó]n\s+Social[^\n:]*:\s*([^\n]{3,60})', sup_text, re.IGNORECASE)
        if m:
            h['proveedor_nombre'] = m.group(1).strip()

    if 'proveedor_nombre' not in h:
        # Estrategia 2: línea que termina exactamente en S.A. / S.R.L. / etc.
        m = re.search(
            r'^([A-ZÁÉÍÓÚÑ][^\n]{2,50}?\s+'
            r'(?:S\.A\.S?|S\.R\.L\.|SRL|S\.A\.|SA|LTDA|S\.C\.S?|E\.V\.I\.C\.S\.A\.)\.?)\s*$',
            sup_text, re.MULTILINE | re.IGNORECASE
        )
        if m:
            h['proveedor_nombre'] = m.group(1).strip()

    if 'proveedor_nombre' not in h:
        # Estrategia 2b: S.A./SA/SRL al inicio de línea, puede continuar con más datos
        # Ej: "Melectric S.A. Fecha: ..."  →  captura "Melectric S.A."
        # Ej: "Distribuidora Interelec SA C.U.I.T.: ..."  →  captura "Distribuidora Interelec SA"
        m = re.search(
            r'^([A-ZÁÉÍÓÚÑ][^\n]{2,45}\s+'
            r'(?:S\.A\.S?|S\.R\.L\.|SRL|S\.A\.|SA|LTDA)\.?)'
            r'(?:\s+[A-ZÁÉÍÓÚÑ]|\s*$)',
            sup_text, re.MULTILINE | re.IGNORECASE
        )
        if m:
            h['proveedor_nombre'] = m.group(1).strip()

    if 'proveedor_nombre' not in h:
        # Estrategia 3: "Nombre Apellido C.U.I.T.:" — persona física / monotributista
        m = re.search(
            r'^([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]{4,50}?)\s+C\.?U\.?I\.?T\.?\s*:',
            sup_text, re.MULTILINE
        )
        if m:
            candidate = m.group(1).strip()
            if not _BUYER_LINE.match(candidate):
                h['proveedor_nombre'] = candidate

    if 'proveedor_nombre' not in h:
        # Estrategia 4: primera línea con aspecto de nombre en la sección del proveedor
        _EXCL = re.compile(
            r'^(FACTURA|REMITO|PRESUPUESTO|NOTA|RECIBO|Fecha|CUIT|Tel|'
            r'COD\.|N[°º]|IVA|INICIO|ORIGINAL|DUPLICADO|TIPO|PUNTO|'
            r'Se[ñn]or|Sr\.|Cliente|Comprador|Direcci[oó]n|Localidad|A\s*:|'
            r'Responsable|Ing\.|Inic\.|Moneda|Av\.|Calle)',
            re.IGNORECASE
        )
        for line in sup_text.split('\n'):
            line = line.strip()
            # Limpiar info extra appended (Fecha:, C.U.I.T.:, etc.) de la misma línea
            clean = re.split(r'\s+(?:Fecha|C\.?U\.?I\.?T|Tel|Inic|Ing\.)\s*[.:]', line, flags=re.IGNORECASE)[0].strip()
            if (5 < len(clean) < 70
                    and re.search(r'[A-Za-z]{3,}', clean)       # al menos 3 letras seguidas
                    and re.match(r'^[A-ZÁÉÍÓÚÑ]', clean)        # empieza con mayúscula
                    and not _EXCL.match(clean)
                    and not re.match(r'^[\d\W]+$', clean)):
                h['proveedor_nombre'] = clean
                break

    # Moneda y tipo de cambio
    is_usd = (re.search(r'\bUSD\b', text) or
              re.search(r'D[oó]lar\s+Billete|Moneda[:\s]+D[oó]lar', text, re.IGNORECASE))
    if is_usd:
        h['moneda'] = 'USD'
        # Intentar extraer TC de varias fórmulas
        for tc_pat in [
            r'USD\s*1\s*=\s*\$\s*([\d.,]+)',                           # USD 1 = $1430
            r'TC\s+aplicado[^\d$]*\$?\s*([\d.,]+)',                     # TC aplicado... $1430
            r'tipo\s+de\s+cambio[^\d$]*:?\s*([\d.,]+)',                 # tipo de cambio: 1430
            r'\$\s*([\d.,]+)\s+por\s+(?:cada\s+)?d[oó]lar',            # $1430 por dólar
        ]:
            m = re.search(tc_pat, text, re.IGNORECASE)
            if m:
                h['tipo_cambio'] = _parse_num(m.group(1))
                break
        else:
            h['tipo_cambio'] = 1.0
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
        # 3) "Subtotal: USD 2.093,62" / "Subtotal: 500.00"
        m = re.search(r'\bSubtotal\b\s*:?\s*(?:USD\s*)?\$?\s*([\d.,]+)', text, re.IGNORECASE)
    if m:
        h['subtotal'] = _parse_num(m.group(1))
    if not h.get('subtotal'):
        # "Neto Gravado: $ 1,804.44" (Melectric y similares)
        m = re.search(r'Neto\s+Gravado\s*:\s*\$?\s*([\d.,]+)', text, re.IGNORECASE)
        if m:
            h['subtotal'] = _parse_num(m.group(1))
    if not h.get('subtotal'):
        # "BRUTO $1,816,100.00" (Interelec y similares)
        m = re.search(r'\bBRUTO\b[^\d$\n]*\$?\s*([\d.,]+)', text, re.IGNORECASE)
        if m:
            h['subtotal'] = _parse_num(m.group(1))

    # IVA 21% — tolerar "_", ":", "$" y "USD" entre etiqueta y número
    m = re.search(r'IVA[\s_]*21[%,°]?\s*[:\$]?\s*(?:USD\s*)?([\d.,]+)', text, re.IGNORECASE)
    if m:
        h['iva_21'] = _parse_num(m.group(1))

    # IVA 10.5% — igual tolerancia
    m = re.search(r'IVA[\s_]*10[,.]?5[%,°]?\s*[:\$]?\s*(?:USD\s*)?([\d.,]+)', text, re.IGNORECASE)
    if m:
        h['iva_105'] = _parse_num(m.group(1))

    # Percepciones — "Percepción IIBB: 90.22"
    m = re.search(r'Percepc?i[oó]n\b[^\n\d]+([\d.,]+)', text, re.IGNORECASE)
    if m:
        h['percepciones'] = _parse_num(m.group(1))

    # Total — excluir SUBTOTAL (lookbehind); tomar el mayor valor encontrado
    totales = re.findall(r'(?<![A-Za-z])TOTAL\b[^\d\n$]*\$?\s*([\d.,]+)', text, re.IGNORECASE)
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

    # Fallback texto — Coresa USD con descripción multi-línea. Dos formatos:
    #
    # FORMATO FACTURA AFIP:
    #   item código descripción | Cant | USD PrecioUnit | Bon% | USD Pr.C/Dto | IVA% | USD SubTotal
    #   0 P48-605-PMMA-4800 PANEL PRO... 60 USD 60,550 50.00% USD 30,275 21.0% USD 1.816,50
    #     LM-CW 4800LM AC100-260V...                ← continuación de descripción
    #
    # FORMATO ORDEN DE VENTA:
    #   item código descripción | USD PrecioUnit | Cant | Desc% | USD Pr.C/Dto | IVA% | USD SubTotal
    #   001 MILAN-2CN-B TECLA MILAN... USD 3,44 50 50% USD 1,72 10,50 USD 86,00
    if not items:
        lines = text.split('\n')
        in_table = False

        # Formato FACTURA: Cant ANTES del precio
        RE_FACTURA = re.compile(
            r'^(\d{1,4})\s+'                 # item
            r'(.+?)\s+'                       # código + descripción (se separan luego)
            r'(\d+(?:[.,]\d+)?)\s+'          # cantidad
            r'USD\s*([\d.,]+)\s+'            # precio unitario
            r'([\d.,]+)\s*%\s+'              # bonificación %
            r'USD\s*([\d.,]+)\s+'            # precio c/dto
            r'([\d.,]+)\s*%\s+'              # IVA %
            r'USD\s*([\d.,]+)$',             # subtotal s/IVA
            re.IGNORECASE
        )
        # Formato ORDEN DE VENTA: Cant DESPUÉS del precio
        RE_OV = re.compile(
            r'^(\d{1,4})\s+'                 # item
            r'([A-Z0-9][A-Z0-9\-/.]*)\s+'    # código
            r'(.+?)\s+'                       # descripción
            r'USD\s*([\d.,]+)\s+'            # precio unitario
            r'(\d+(?:[.,]\d+)?)\s+'          # cantidad
            r'([\d.,]+)\s*%\s+'              # descuento %
            r'USD\s*([\d.,]+)\s+'            # precio c/desc
            r'([\d.,]+)\s*%?\s+'             # IVA %
            r'USD\s*([\d.,]+)$',             # subtotal s/iva
            re.IGNORECASE
        )

        def _split_cod_desc(blob):
            """Separa 'P48-605 PANEL PRO...' → ('P48-605', 'PANEL PRO...')."""
            parts = blob.strip().split(None, 1)
            if len(parts) == 2:
                return parts[0], parts[1].strip()
            return blob.strip(), ''

        def _ncor(s):
            """Número Coresa: la coma SIEMPRE es decimal (ej '60,550'=60.55, '1.816,50'=1816.50)."""
            s = re.sub(r'[USD$%\s]', '', str(s)).strip()
            if not s or s == '-':
                return 0.0
            if '.' in s and ',' in s:        # 1.816,50 → punto miles, coma decimal
                return float(s.replace('.', '').replace(',', '.'))
            if ',' in s:                      # 60,550 → coma decimal
                return float(s.replace(',', '.'))
            try:
                return float(s)
            except ValueError:
                return 0.0

        for line in lines:
            lu = line.upper()
            # Encabezado robusto (tolerante a codificación rara): tiene DESCRIPCI + CANT
            if not in_table:
                if 'DESCRIPCI' in lu and 'CANT' in lu:
                    in_table = True
                continue

            if re.match(r'\s*(Subtotal|TOTAL|Son\s+Pesos|Para\s+la\s+cancelaci|'
                        r'Neto\s+Gravado|CAE|Esta\s+factura|Saldo\s+en)',
                        line, re.IGNORECASE):
                break

            stripped = line.strip()
            if not stripped:
                continue

            m = RE_FACTURA.match(stripped)
            if m:
                sku, desc = _split_cod_desc(m.group(2))
                items.append({
                    'sku':              sku,
                    'descripcion':      desc,
                    'cantidad':         _ncor(m.group(3)),
                    'precio_unit':      _ncor(m.group(4)),
                    'descuento_pct':    _ncor(m.group(5)),
                    'precio_neto_unit': _ncor(m.group(6)),
                    'iva_pct':          _ncor(m.group(7)),
                    'subtotal_siva':    _ncor(m.group(8)),
                    'moneda':           'USD',
                })
                continue

            m = RE_OV.match(stripped)
            if m:
                items.append({
                    'sku':              m.group(2),
                    'descripcion':      m.group(3).strip(),
                    'cantidad':         _ncor(m.group(5)),
                    'precio_unit':      _ncor(m.group(4)),
                    'descuento_pct':    _ncor(m.group(6)),
                    'precio_neto_unit': _ncor(m.group(7)),
                    'iva_pct':          _ncor(m.group(8)),
                    'subtotal_siva':    _ncor(m.group(9)),
                    'moneda':           'USD',
                })
                continue

            # Línea de continuación → se suma a la descripción del último ítem
            if items and 'USD' not in stripped:
                items[-1]['descripcion'] += ' ' + stripped

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

def _items_generic(tables, text, header_hint=None, discovered=None):
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

    return _items_generic_text(text, header_hint=header_hint, discovered=discovered)


def _items_generic_text(text, header_hint=None, discovered=None):
    """
    Extracción genérica por texto libre, con soporte de aprendizaje por CUIT.

    Principio: en cualquier factura argentina los ítems siguen el patrón
        [SKU/código]  [descripción]  [números al final: precio / subtotal]

    Parámetros:
        header_hint  : línea de encabezado conocida del proveedor (de facturas previas)
        discovered   : dict vacío → se llena con {'header_trigger': ..., 'sku_offset': ...}
                       para guardar en el perfil del proveedor.

    Proceso:
        1. PASADA 1: encontrar la línea de encabezado de la tabla de ítems.
           Si hay hint, se usa ese fragmento antes de intentar la detección genérica.
        2. PASADA 2: parsear líneas de ítems tras el encabezado.
    """

    # ── Patrones de detección ─────────────────────────────────────────────────

    # Encabezado de tabla: sinónimo de "código" + "descripción/precio"
    HDR = re.compile(
        r'(?:C[OÓ]D(?:IGO)?|SKU|ART[IÍ]CULO|PRODUCTO|ITEM)\b.{0,80}'
        r'(?:DESCRIP|DETALLE|DENOMIN|PRECIO|IMPORTE|TOTAL)',
        re.IGNORECASE
    )

    # Pie de factura → parar
    FOOTER = re.compile(
        r'^\s*(?:SUB[\s-]?TOTAL|TOTAL\b|I\.?V\.?A\.?\b|PERCEP|C\.?A\.?E\.?\b|'
        r'Son\s+pesos|BONIF|CHEQUES|CONDICI[OÓ]N\s+DE\s+VENTA|VENCIM)',
        re.IGNORECASE
    )

    SKU_RE   = re.compile(r'^[A-Z0-9][A-Z0-9\-./]{0,29}$', re.IGNORECASE)
    STOPWORDS = re.compile(
        r'^(?:DE|EL|LA|LOS|LAS|UN|UNA|Y|O|POR|CON|SIN|PARA|QUE|AL|DEL|EN|A|'
        r'NO|NI|SU|MAS|MÁS|SI|MI|ME|TE|LE|ES|HA|HI|HO|SE|SER|SUS)$',
        re.IGNORECASE
    )
    NUM_RE = re.compile(r'^[\d.,]+$')

    lines = text.split('\n')

    # ── PASADA 1: localizar encabezado ────────────────────────────────────────

    header_idx        = None
    found_header_line = None

    # Primero intentar con el hint guardado (más rápido y confiable)
    if header_hint:
        for i, line in enumerate(lines):
            if header_hint.upper() in line.upper():
                header_idx        = i
                found_header_line = line.strip()
                break

    # Si el hint no funcionó, usar detección genérica
    if header_idx is None:
        for i, line in enumerate(lines):
            if HDR.search(line):
                header_idx        = i
                found_header_line = line.strip()
                break

    if header_idx is None:
        return []   # factura sin tabla de ítems reconocible

    # ── PASADA 2: parsear ítems ───────────────────────────────────────────────

    items      = []
    sku_offsets = []   # para calcular sku_offset promedio

    for line in lines[header_idx + 1:]:
        if FOOTER.match(line):
            break

        stripped = line.strip()
        if not stripped or len(stripped) < 4:
            continue

        tokens = stripped.split()
        if len(tokens) < 2:
            continue

        # Fusionar "21.00 %" → "21.00%" para que el scan de tail los ignore
        merged = []
        ti = 0
        while ti < len(tokens):
            if (ti + 1 < len(tokens) and tokens[ti + 1] == '%'
                    and NUM_RE.match(tokens[ti])):
                merged.append(tokens[ti] + '%')
                ti += 2
            else:
                merged.append(tokens[ti])
                ti += 1
        tokens = merged

        # Separar números del lado derecho (hasta 5), saltando tokens de IVA/descuento "%"
        split_pos = len(tokens)
        tail = []
        k = len(tokens) - 1
        while k >= 0 and len(tail) < 5:
            if NUM_RE.match(tokens[k]):
                tail.insert(0, tokens[k])
                split_pos = k
                k -= 1
            elif re.match(r'^\d+[.,]?\d*%$', tokens[k]):
                split_pos = k   # también excluir de left
                k -= 1          # pero no agregar a tail
            else:
                break

        if not tail:
            continue

        left = tokens[:split_pos]

        # Identificar SKU: primer token código-like
        # Los números puros cortos (< 4 dígitos) son cantidades, no SKUs
        sku     = None
        sku_pos = 0
        for i, tok in enumerate(left):
            if i == 0 and re.match(r'^\d{1,2}$', tok):
                continue   # saltar ordinal de ítem
            if SKU_RE.match(tok) and not STOPWORDS.match(tok):
                if re.match(r'^\d+$', tok) and len(tok) < 4:
                    continue   # número corto → probable cantidad, no SKU
                sku     = tok.upper()
                sku_pos = i
                break

        if not sku:
            continue

        # Descripción: tokens entre SKU y los números, sin "21.00%" etc.
        desc_parts = [t for t in left[sku_pos + 1:]
                      if not re.match(r'^\d+[.,]?\d*\s*%$', t)]
        descripcion = ' '.join(desc_parts).strip()

        # Precios
        subtotal    = _parse_num(tail[-1])
        precio_unit = _parse_num(tail[-2]) if len(tail) >= 2 else 0.0
        if precio_unit == 0 and subtotal > 0:
            precio_unit = subtotal

        if subtotal == 0 and precio_unit == 0:
            continue

        # Cantidad (tokens numéricos antes del SKU, saltar ordinal)
        qty     = 1.0
        pre_sku = left[:sku_pos]
        nums_pre = [t for t in pre_sku if NUM_RE.match(t)]
        if nums_pre:
            if len(nums_pre) == 1:
                val = nums_pre[0]
                if not (re.match(r'^\d{1,2}$', val) and int(val) <= 99):
                    qty = _parse_num(val, context='qty')
            else:
                qty = _parse_num(nums_pre[-1], context='qty')

        sku_offsets.append(sku_pos)
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

    # ── Guardar config descubierto ────────────────────────────────────────────

    if discovered is not None and found_header_line:
        discovered['header_trigger'] = found_header_line.upper()
        if sku_offsets:
            # posición más frecuente del SKU en las líneas de ítems
            discovered['sku_offset'] = max(set(sku_offsets), key=sku_offsets.count)

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
