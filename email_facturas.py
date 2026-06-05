"""
email_facturas.py — lee casillas de Gmail por IMAP y devuelve los correos
recientes que traen facturas adjuntas (PDF / imagen).

Requiere, por cada cuenta, una "Contraseña de aplicación" de Gmail
(no la contraseña normal). Se configuran en .streamlit/secrets.toml:

    [email]
    cuentas = [
        { usuario = "electricidadcasasergio@gmail.com", password = "xxxx xxxx xxxx xxxx" },
        { usuario = "infoadmics@gmail.com",             password = "yyyy yyyy yyyy yyyy" },
    ]
"""
import os
import imaplib
import email
from email.header import decode_header, make_header

IMAP_HOST = 'imap.gmail.com'
EXTS_VALIDAS = ('.pdf', '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff')


def _decode(s):
    """Decodifica encabezados MIME (asuntos, nombres de archivo con acentos)."""
    if not s:
        return ''
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return str(s)


import re as _re

# Palabras de asunto que indican un comprobante (factura / nota de crédito-débito)
_RX_COMPROBANTE = _re.compile(
    r'(factura|comprob|f\.?\s?c\.?\b|\bfc\b|\bfca\b|'
    r'nota\s+de\s+cr[eé]dito|nota\s+de\s+d[eé]bito|\bnota\s+cr|\bnota\s+deb|\bnc\b|\bnd\b)',
    _re.IGNORECASE
)
# Palabras que descartan el correo (no es una factura de compra)
_RX_NO_COMPROBANTE = _re.compile(
    r'(orden\s+de\s+venta|nota\s+de\s+venta|cotiza|presupuesto|remito|'
    r'listo\s+para\s+retirar|pedido|orden\s+de\s+compra|recibo|comprobante\s+de\s+pago|'
    r'transferencia|resumen|estado\s+de\s+cuenta)',
    _re.IGNORECASE
)


def _es_comprobante(asunto):
    """True si el asunto parece una factura/nota de crédito-débito (y no orden/cotización/etc.)."""
    a = asunto or ''
    if _RX_NO_COMPROBANTE.search(a):
        return False
    return bool(_RX_COMPROBANTE.search(a))


def get_cuentas():
    """Lee las cuentas configuradas desde st.secrets. Devuelve lista de dicts."""
    try:
        import streamlit as st
        conf = st.secrets.get('email', {})
        cuentas = conf.get('cuentas', [])
        return [dict(c) for c in cuentas]
    except Exception:
        return []


def fetch_bandeja(cuentas=None, dias=30, max_por_cuenta=80, texto='', solo_facturas=True):
    """
    Devuelve una lista de correos (más nuevos primero) con adjuntos de factura.
    Cada item: {cuenta, remitente, asunto, fecha, adjuntos:[(nombre, bytes)], error?}

    texto: filtra en Gmail por ese término (remitente/asunto/cuerpo). Ej: 'coresa'.
    solo_facturas: si True, restringe a comprobantes (factura / nota de crédito / débito)
                   y excluye órdenes de venta, cotizaciones, presupuestos, remitos, etc.
    """
    if cuentas is None:
        cuentas = get_cuentas()

    resultados = []
    for c in cuentas:
        usuario = c.get('usuario', '').strip()
        passwd  = c.get('password', '').replace(' ', '').strip()  # las app passwords se copian con espacios
        if not usuario or not passwd:
            continue
        try:
            M = imaplib.IMAP4_SSL(IMAP_HOST)
            M.login(usuario, passwd)
            M.select('INBOX')
            # Búsqueda Gmail: con adjunto, recientes y (opcional) por término del proveedor
            consulta = f'has:attachment newer_than:{dias}d'
            if texto and texto.strip():
                consulta += f' {texto.strip()}'
            try:
                typ, data = M.search(None, 'X-GM-RAW', f'"{consulta}"')
            except Exception:
                typ, data = M.search(None, 'ALL')
            ids = data[0].split() if data and data[0] else []
            ids = list(reversed(ids))[:max_por_cuenta]

            for num in ids:
                typ, md = M.fetch(num, '(RFC822)')
                if not md or not md[0]:
                    continue
                msg = email.message_from_bytes(md[0][1])
                asunto = _decode(msg.get('Subject', '(sin asunto)'))

                # Filtro por asunto: solo comprobantes (factura / nota de crédito-débito)
                if solo_facturas and not _es_comprobante(asunto):
                    continue

                adjuntos = []
                for part in msg.walk():
                    if part.get_content_maintype() == 'multipart':
                        continue
                    fn = part.get_filename()
                    if not fn:
                        continue
                    fn = _decode(fn)
                    if os.path.splitext(fn)[1].lower() in EXTS_VALIDAS:
                        payload = part.get_payload(decode=True)
                        if payload:
                            adjuntos.append((fn, payload))
                if adjuntos:
                    resultados.append({
                        'cuenta':    usuario,
                        'remitente': _decode(msg.get('From', '')),
                        'asunto':    asunto,
                        'fecha':     _decode(msg.get('Date', '')),
                        'adjuntos':  adjuntos,
                    })
            M.logout()
        except imaplib.IMAP4.error as e:
            resultados.append({'cuenta': usuario, 'error': f'Login/IMAP: {e}'})
        except Exception as e:
            resultados.append({'cuenta': usuario, 'error': str(e)})

    return resultados
