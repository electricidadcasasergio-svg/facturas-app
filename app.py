import base64
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import importlib
import database as db
import extractor
import email_facturas

# Forzar recarga del código desde disco en cada ejecución.
# Streamlit cachea los módulos importados; sin esto, los cambios de
# extractor.py / database.py no se aplican hasta reiniciar el servidor.
importlib.reload(extractor)
importlib.reload(db)
importlib.reload(email_facturas)

# Versión del programa (subila cada vez que hay cambios para verificar actualizaciones)
APP_VERSION = "2026.06.04-j"

# ── Config ───────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Casa Sergio — Facturas",
    page_icon="⚡",
    layout="wide",
)

db.init_db()

# ── CSS personalizado ─────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Ocultar header de Streamlit */
header[data-testid="stHeader"] { display: none !important; }

/* Fondo principal */
.main .block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}

/* ── Sidebar oscuro ── */
section[data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(170deg, #071e3d 0%, #1558a7 100%);
}
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div { color: rgba(255,255,255,0.88) !important; }
section[data-testid="stSidebar"] .stRadio > div { gap: 4px; }
section[data-testid="stSidebar"] .stRadio label {
    background: rgba(255,255,255,0.07);
    border-radius: 8px;
    padding: 8px 14px !important;
    transition: background 0.2s;
    font-size: 0.95rem !important;
}
section[data-testid="stSidebar"] .stRadio label:hover {
    background: rgba(255,255,255,0.18) !important;
}

/* ── Tarjetas de métricas ── */
div[data-testid="metric-container"] {
    background: #ffffff;
    border-radius: 14px;
    padding: 18px 20px !important;
    box-shadow: 0 4px 18px rgba(21,88,167,0.10);
    border-top: 4px solid #1558a7;
}
div[data-testid="metric-container"] [data-testid="stMetricLabel"] > div {
    font-size: 0.75rem !important;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: #7a93b4 !important;
}
div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 1.65rem !important;
    font-weight: 700;
    color: #071e3d !important;
}

/* ── Expanders ── */
div[data-testid="stExpander"] {
    border: 1px solid #d8e5f5 !important;
    border-radius: 12px !important;
    box-shadow: 0 2px 8px rgba(21,88,167,0.06);
    background: #ffffff;
}
div[data-testid="stExpander"] summary {
    font-weight: 600;
}

/* ── Botones ── */
div.stButton > button {
    border-radius: 9px !important;
    font-weight: 600 !important;
    letter-spacing: 0.3px;
    transition: all 0.2s !important;
}
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1558a7, #071e3d) !important;
    border: none !important;
    box-shadow: 0 4px 14px rgba(21,88,167,0.35) !important;
}
div.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(21,88,167,0.45) !important;
}
div.stButton > button:not([kind="primary"]):hover {
    border-color: #1558a7 !important;
    color: #1558a7 !important;
}

/* ── Tablas / Data editor ── */
div[data-testid="stDataFrame"], div[data-testid="data_editor"] {
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 2px 10px rgba(0,0,0,0.06);
}

/* ── Alertas ── */
div[data-testid="stAlert"] { border-radius: 10px !important; }

/* ── Divisor ── */
hr { border-color: #d8e5f5 !important; margin: 1.5rem 0 !important; }

/* ── Selectbox / inputs ── */
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div {
    border-radius: 8px !important;
}
</style>
""", unsafe_allow_html=True)


# ── Helper: encabezado de página ──────────────────────────────────────────────

def _page_header(icon: str, title: str, subtitle: str = ""):
    sub_html = (
        f'<p style="color:rgba(255,255,255,0.75);margin:6px 0 0;font-size:0.9rem;">{subtitle}</p>'
        if subtitle else ""
    )
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, #1558a7 0%, #071e3d 100%);
        border-radius: 16px;
        padding: 22px 28px;
        margin-bottom: 22px;
        box-shadow: 0 8px 28px rgba(21,88,167,0.22);
    ">
        <h1 style="color:white;margin:0;font-size:1.7rem;font-weight:700;">
            {icon}&nbsp; {title}
        </h1>
        {sub_html}
    </div>
    """, unsafe_allow_html=True)


# ── Generar PDF de una tabla (para el control de faltantes) ──────────────────

def generar_pdf_tabla(df, columnas, titulo, subtitulo=""):
    """Devuelve los bytes de un PDF con la tabla dada. Requiere fpdf2."""
    from fpdf import FPDF

    def _s(x):  # sanitizar texto a latin-1 (fpdf core fonts)
        return str(x).encode('latin-1', 'replace').decode('latin-1')

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font('Helvetica', 'B', 15)
    pdf.cell(0, 9, _s(titulo), ln=1)
    pdf.set_font('Helvetica', '', 9)
    fecha_hoy = date.today().strftime('%d/%m/%Y')
    pdf.cell(0, 6, _s(f"Casa Sergio  ·  Generado: {fecha_hoy}  ·  {subtitulo}"), ln=1)
    pdf.ln(3)

    ancho = pdf.epw
    w = ancho / max(1, len(columnas))

    def _encabezado():
        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_fill_color(21, 88, 167)
        pdf.set_text_color(255, 255, 255)
        for col in columnas:
            pdf.cell(w, 8, _s(str(col))[:38], border=1, align='C', fill=True)
        pdf.ln()
        pdf.set_text_color(0, 0, 0)

    _encabezado()
    pdf.set_font('Helvetica', '', 8)
    fill = False
    for _, row in df.iterrows():
        if pdf.get_y() > pdf.h - 16:
            pdf.add_page()
            _encabezado()
            pdf.set_font('Helvetica', '', 8)
        pdf.set_fill_color(240, 244, 250)
        for col in columnas:
            pdf.cell(w, 7, _s(str(row[col]))[:40], border=1, fill=fill)
        pdf.ln()
        fill = not fill

    return bytes(pdf.output())


# ── Procesar y guardar un comprobante (reutilizable: subir y bandeja mail) ────

_ITEM_COLS = ['sku', 'descripcion', 'cantidad', 'precio_unit',
              'descuento_pct', 'precio_neto_unit', 'iva_pct', 'subtotal_siva']
_TIPO_LABEL = {'FC': 'Factura', 'ND': 'Nota de Débito', 'NC': 'Nota de Crédito'}


def procesar_comprobante(nombre, datos_bytes, key_prefix, expandido=True):
    """Procesa un PDF/imagen (bytes), muestra la previsualización editable y permite guardar."""
    suffix = Path(nombre).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(datos_bytes)
        tmp_path = tmp.name

    try:
        cuit_hint = extractor.quick_get_cuit(tmp_path)
    except AttributeError:
        cuit_hint = None
    proveedor_config = db.get_proveedor_config(cuit_hint) if cuit_hint else None
    nombre_guardado  = (db.get_proveedor_nombre_por_cuit(cuit_hint)
                        if cuit_hint and hasattr(db, 'get_proveedor_nombre_por_cuit')
                        else None)

    with st.spinner(f"Procesando **{nombre}**…"):
        try:
            data = extractor.extract_invoice(tmp_path, config=proveedor_config)
            data['archivo_nombre'] = nombre
            error = None
        except Exception as e:
            data, error = None, str(e)
    Path(tmp_path).unlink(missing_ok=True)

    if error:
        st.error(f"❌ **{nombre}**: {error}")
        return

    items    = data.get('items', [])
    tipo_doc = data.get('tipo', 'FC')
    label = (
        f"✅ {nombre}  —  {_TIPO_LABEL.get(tipo_doc, 'Factura')}  |  "
        f"{data.get('proveedor_nombre','?')}  |  {data.get('numero','?')}  |  "
        f"{data.get('fecha','?')}"
    )

    with st.expander(label, expanded=expandido):
        ya = None
        if hasattr(db, 'factura_ya_cargada'):
            ya = db.factura_ya_cargada(data.get('proveedor_cuit', ''),
                                       data.get('numero', ''), tipo_doc)
        if ya:
            st.error(f"🔁 **Este comprobante YA está cargado.** Número {ya['numero']} — "
                     f"total ${ya.get('total', 0):,.2f}. No hace falta volver a subirlo.")

        if tipo_doc == 'NC':
            st.info("🟦 **Nota de Crédito** — se RESTARÁ del saldo del proveedor.")
        elif tipo_doc == 'ND':
            st.info("🟧 **Nota de Débito** — se SUMARÁ al saldo del proveedor.")

        if data.get('es_venta'):
            st.error("🛑 **Parece una factura de VENTA emitida por Casa Sergio**, no una compra. "
                     "Revisá antes de guardar.")

        if proveedor_config:
            st.success("✅ Proveedor conocido — se usó perfil guardado.")

        st.markdown("#### Datos del encabezado")
        st.caption("Revisá y corregí si algo no se detectó bien.")

        c1, c2 = st.columns(2)
        if data.get('proveedor_nombre_fiable'):
            nombre_det = data.get('proveedor_nombre', '')
        else:
            nombre_det = nombre_guardado or data.get('proveedor_nombre', '')
        cuit_det   = data.get('proveedor_cuit', '')
        numero_det = data.get('numero', '')
        fecha_det  = data.get('fecha', date.today().strftime('%d/%m/%Y'))
        moneda_det = data.get('moneda', 'ARS')
        tc_det     = data.get('tipo_cambio', 1.0)

        prov_nombre = c1.text_input("Proveedor" + (" ⚠️ no detectado" if not nombre_det else ""),
                                    value=nombre_det, key=f"nombre_{key_prefix}")
        prov_cuit   = c1.text_input("CUIT" + (" ⚠️ no detectado" if not cuit_det else ""),
                                    value=cuit_det, key=f"cuit_{key_prefix}")
        fac_numero  = c2.text_input("Número de factura" + (" ⚠️ no detectado" if not numero_det else ""),
                                    value=numero_det, key=f"nro_{key_prefix}")
        fac_fecha   = c2.text_input("Fecha (DD/MM/AAAA)", value=fecha_det, key=f"fecha_{key_prefix}")

        c3, c4 = st.columns(2)
        moneda = c3.selectbox("Moneda", ['ARS', 'USD'], index=0 if moneda_det == 'ARS' else 1,
                              key=f"moneda_{key_prefix}")
        tc = c4.number_input("Tipo de cambio (ARS/USD)", value=float(tc_det), min_value=1.0,
                             key=f"tc_{key_prefix}") if moneda == 'USD' else 1.0

        st.markdown("#### Ítems")
        if not items:
            st.warning("⚠️ No se encontraron ítems automáticamente. Podés agregarlos en la tabla.")

        df_items = (pd.DataFrame(items).reindex(columns=_ITEM_COLS)
                    if items else pd.DataFrame(columns=_ITEM_COLS))
        for col, default in [('cantidad', 1.0), ('precio_unit', 0.0), ('descuento_pct', 0.0),
                             ('precio_neto_unit', 0.0), ('iva_pct', 21.0), ('subtotal_siva', 0.0)]:
            df_items[col] = pd.to_numeric(df_items.get(col, default), errors='coerce').fillna(default)
        df_items['sku']         = df_items.get('sku', '').fillna('').astype(str)
        df_items['descripcion'] = df_items.get('descripcion', '').fillna('').astype(str)

        edited_items_df = st.data_editor(
            df_items,
            column_config={
                'sku':              st.column_config.TextColumn('Código / SKU', required=True),
                'descripcion':      st.column_config.TextColumn('Descripción'),
                'cantidad':         st.column_config.NumberColumn('Cantidad',      format="%.2f"),
                'precio_unit':      st.column_config.NumberColumn('Precio lista',  format="%.4f"),
                'descuento_pct':    st.column_config.NumberColumn('Dto %',         format="%.2f"),
                'precio_neto_unit': st.column_config.NumberColumn('Precio neto',   format="%.4f"),
                'iva_pct':          st.column_config.NumberColumn('IVA %',         format="%.1f"),
                'subtotal_siva':    st.column_config.NumberColumn('Subtotal s/IVA', format="%.2f"),
            },
            num_rows="dynamic", use_container_width=True, key=f"items_{key_prefix}",
        )
        n_items = len(edited_items_df[edited_items_df['sku'].str.strip() != ''])
        st.caption(f"{n_items} ítem(s) — podés agregar/editar/eliminar filas en la tabla.")

        if not prov_nombre:
            st.error("Completá el nombre del proveedor antes de guardar.")
        elif not fac_numero:
            st.error("Completá el número de factura antes de guardar.")
        elif st.button("💾 Guardar en base de datos", key=f"save_{key_prefix}"):
            items_to_save = [row for row in edited_items_df.to_dict('records')
                             if str(row.get('sku', '')).strip()]
            for it in items_to_save:
                it.setdefault('moneda', moneda)
            try:
                prov_id = db.upsert_proveedor(prov_nombre,
                                              prov_cuit or f'sin-cuit-{prov_nombre[:20]}', moneda)
                fac_id = db.insert_factura(
                    prov_id, fac_numero, fac_fecha, data.get('subtotal', 0),
                    data.get('iva_21', 0), data.get('iva_105', 0), data.get('percepciones', 0),
                    data.get('total', 0), moneda, tc, nombre, data.get('cae', ''),
                    data.get('tipo', 'FC'),
                )
                if fac_id:
                    if items_to_save:
                        db.insert_items(fac_id, items_to_save)
                    try:
                        dest = db.ARCHIVOS_DIR / f"{fac_id}{suffix}"
                        dest.write_bytes(datos_bytes)
                        db.set_archivo_factura(fac_id, str(dest))
                    except Exception:
                        pass
                    discovered = data.get('_discovered_config', {})
                    if discovered and prov_cuit:
                        db.save_proveedor_config(prov_cuit, discovered)
                    st.success(f"✅ Guardada — **{prov_nombre}** — {len(items_to_save)} ítems."
                               + (" 🧠 Perfil aprendido." if discovered and prov_cuit else ""))
                else:
                    st.error(f"🔁 **Ya habías subido este comprobante** "
                             f"({_TIPO_LABEL.get(tipo_doc,'Factura')} {fac_numero} de {prov_nombre}).")
            except Exception as e:
                st.error(f"Error al guardar: {e}")


# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.markdown("""
<div style="text-align:center; padding:12px 0 24px;">
    <div style="font-size:2.8rem; line-height:1;">⚡</div>
    <div style="font-size:1.15rem; font-weight:700; color:white; margin-top:6px;">Casa Sergio</div>
    <div style="font-size:0.72rem; color:rgba(255,255,255,0.55); letter-spacing:1px;
                text-transform:uppercase; margin-top:2px;">Gestión de Facturas</div>
</div>
""", unsafe_allow_html=True)

page = st.sidebar.radio(
    "Navegación",
    ["🏠 Inicio", "📤 Subir Facturas", "📧 Bandeja", "📄 Facturas", "✅ Control", "📊 Cta. Cte.", "🔍 SKUs", "⚖️ Comparar", "🏢 Proveedores"],
    label_visibility="collapsed",
)

st.sidebar.markdown(
    f"<div style='position:fixed;bottom:10px;font-size:0.7rem;color:rgba(255,255,255,0.45);'>"
    f"versión {APP_VERSION}</div>",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# 🏠  INICIO
# ─────────────────────────────────────────────────────────────────────────────
if page == "🏠 Inicio":
    _page_header("🏠", "Casa Sergio", "Panel de control de compras y facturas")

    with db.get_conn() as conn:
        n_fact  = conn.execute("SELECT COUNT(*) FROM facturas").fetchone()[0]
        n_prov  = conn.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0]
        n_skus  = conn.execute("SELECT COUNT(DISTINCT sku) FROM items").fetchone()[0]
        tot_ars = conn.execute(
            "SELECT COALESCE(SUM(subtotal),0) FROM facturas WHERE moneda='ARS'"
        ).fetchone()[0]

    pagos = db.get_resumen_pagos()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧾 Facturas cargadas", f"{n_fact:,}")
    c2.metric("🏢 Proveedores",        f"{n_prov:,}")
    c3.metric("🔖 SKUs distintos",     f"{n_skus:,}")
    c4.metric("💰 Compras netas ARS",  f"${tot_ars:,.0f}")

    # Resumen de pagos
    if n_fact > 0:
        st.markdown("---")
        cp1, cp2, cp3 = st.columns(3)
        cp1.metric("✅ Facturas pagas",    f"{pagos['pagadas']:,}")
        cp2.metric("⏳ Facturas pendientes", f"{pagos['pendientes']:,}")
        cp3.metric("💸 Deuda pendiente ARS", f"${pagos['monto_pendiente_ars']:,.0f}")
        if pagos['pendientes'] > 0:
            st.warning(f"⚠️ Tenés **{pagos['pendientes']} factura(s) sin pagar** por un total de **${pagos['monto_pendiente_ars']:,.0f} ARS**. Entrá a 📄 Facturas para registrar los pagos.")

    if n_fact == 0:
        st.info("Todavía no hay facturas. Usá **📤 Subir Facturas** para empezar.")
    else:
        meses = db.get_compras_por_mes()
        if meses:
            df_m = pd.DataFrame(meses)
            fig = px.bar(
                df_m, x="mes", y="total_ars",
                title="Compras netas por mes (ARS equivalente)",
                labels={"mes": "Mes", "total_ars": "$"},
            )
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)

        # Top 10 proveedores por gasto
        with db.get_conn() as conn:
            top_prov = conn.execute("""
                SELECT p.nombre,
                       SUM(CASE WHEN f.moneda='ARS' THEN f.subtotal
                                ELSE f.total * f.tipo_cambio END) AS total
                FROM facturas f
                JOIN proveedores p ON f.proveedor_id = p.id
                GROUP BY p.id ORDER BY total DESC LIMIT 10
            """).fetchall()
        if top_prov:
            df_tp = pd.DataFrame(top_prov, columns=["Proveedor", "Total ARS"])
            fig2 = px.bar(
                df_tp, x="Total ARS", y="Proveedor",
                orientation="h", title="Top proveedores por gasto",
            )
            st.plotly_chart(fig2, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# 📤  SUBIR FACTURAS
# ─────────────────────────────────────────────────────────────────────────────
elif page == "📤 Subir Facturas":
    _page_header("📤", "Subir Facturas", "PDFs o fotos JPG/PNG — se previsualizan antes de guardar")

    uploaded = st.file_uploader(
        "Arrastrá los archivos acá (PDF, JPG, PNG)",
        type=["pdf", "jpg", "jpeg", "png"],
        accept_multiple_files=True,
    )

    if not uploaded:
        st.stop()

    for f in uploaded:
        procesar_comprobante(f.name, f.getvalue(), key_prefix=f.name)


# ─────────────────────────────────────────────────────────────────────────────
# 📧  BANDEJA (facturas que llegan por mail)
# ─────────────────────────────────────────────────────────────────────────────
elif page == "📧 Bandeja":
    _page_header("📧", "Bandeja de facturas", "Facturas que llegaron por mail a Casa Sergio")

    cuentas = email_facturas.get_cuentas()
    if not cuentas:
        st.warning("⚠️ Todavía no configuraste las casillas de correo.")
        with st.expander("📋 Cómo configurar (una sola vez)", expanded=True):
            st.markdown("""
**1. En cada cuenta de Gmail, generá una Contraseña de aplicación:**
- Entrá a tu cuenta → **Seguridad** → activá la **Verificación en 2 pasos**
- Después entrá a **https://myaccount.google.com/apppasswords**
- Creá una contraseña (nombre: "Facturas App") → te da 16 letras (ej: `abcd efgh ijkl mnop`)

**2. Pegá los datos en el archivo de secretos**
Creá/editá el archivo `.streamlit/secrets.toml` en la carpeta del programa con esto:

```toml
[email]
cuentas = [
    { usuario = "electricidadcasasergio@gmail.com", password = "abcd efgh ijkl mnop" },
    { usuario = "infoadmics@gmail.com",             password = "qrst uvwx yz12 3456" },
]
```

**3. Reiniciá el servidor** (`INICIAR_SERVIDOR.bat`) y volvé a esta pantalla.

🔒 Ese archivo NO se sube a internet (está protegido), las contraseñas quedan solo en tu PC.
            """)
        st.stop()

    st.caption(f"Casillas configuradas: " + " · ".join(c.get('usuario','') for c in cuentas))
    cc1, cc2, cc3 = st.columns([1, 2, 1])
    dias = cc1.selectbox("Período", [7, 15, 30, 60], index=0, key="band_dias",
                         format_func=lambda d: f"Últimos {d} días")
    filtro = cc2.text_input("🔎 Buscar", placeholder="proveedor, asunto o archivo…",
                            key="band_filtro")
    buscar_btn = cc3.button("🔄 Revisar correos", type="primary")

    # Cachear el resultado para no reconectar en cada interacción
    @st.cache_data(show_spinner="Conectando a los correos…", ttl=300)
    def _bandeja(dias_):
        return email_facturas.fetch_bandeja(dias=dias_)

    if buscar_btn:
        _bandeja.clear()

    correos = _bandeja(dias)

    errores = [c for c in correos if c.get('error')]
    validos = [c for c in correos if not c.get('error')]
    for e in errores:
        st.error(f"❌ No se pudo leer **{e['cuenta']}**: {e['error']}")

    if not validos:
        st.info("No se encontraron correos con facturas adjuntas en el período.")
        st.stop()

    # Filtro de búsqueda (remitente / asunto / cuenta / nombre de adjunto)
    if filtro:
        ft = filtro.lower()
        def _coincide(c):
            texto = " ".join([
                c.get('remitente', ''), c.get('asunto', ''), c.get('cuenta', ''),
                " ".join(fn for fn, _ in c.get('adjuntos', []))
            ]).lower()
            return ft in texto
        validos = [c for c in validos if _coincide(c)]
        if not validos:
            st.warning(f"Ningún correo coincide con «{filtro}».")
            st.stop()

    total_adj = sum(len(c['adjuntos']) for c in validos)
    extra = f" (filtrado por «{filtro}»)" if filtro else ""
    st.success(f"📨 {len(validos)} correo(s) con {total_adj} adjunto(s) en los últimos {dias} días{extra}.")

    for ci, correo in enumerate(validos):
        with st.container(border=True):
            st.markdown(
                f"**De:** {correo['remitente']}  \n"
                f"**Asunto:** {correo['asunto']}  \n"
                f"**Fecha:** {correo['fecha']}  ·  📥 {correo['cuenta']}"
            )
            for ai, (fn, datos) in enumerate(correo['adjuntos']):
                vc1, vc2 = st.columns([3, 1])
                vc1.markdown(f"📎 `{fn}`")
                vc2.download_button("⬇️ Descargar", datos, file_name=fn,
                                    key=f"dl_mail_{ci}_{ai}")
                ext = Path(fn).suffix.lower()
                with st.expander("👁️ Ver archivo adjunto"):
                    if ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'):
                        st.image(datos, use_container_width=True)
                    elif ext == '.pdf':
                        b64 = base64.b64encode(datos).decode()
                        st.markdown(
                            f'<iframe src="data:application/pdf;base64,{b64}" '
                            f'width="100%" height="600" style="border:1px solid #d8e5f5;border-radius:8px;"></iframe>',
                            unsafe_allow_html=True,
                        )
                        st.caption("Si no se ve, usá el botón Descargar.")
                    else:
                        st.info("Vista previa no disponible para este tipo de archivo.")
                procesar_comprobante(fn, datos,
                                     key_prefix=f"mail_{ci}_{ai}", expandido=False)


# ─────────────────────────────────────────────────────────────────────────────
# 📄  FACTURAS
# ─────────────────────────────────────────────────────────────────────────────
elif page == "📄 Facturas":
    _page_header("📄", "Facturas", "Historial de facturas cargadas")

    proveedores = db.get_proveedores()
    prov_map    = {"Todos": None} | {p['nombre']: p['id'] for p in proveedores}

    col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
    prov_sel    = col1.selectbox("Proveedor", list(prov_map.keys()))
    fecha_desde = col2.date_input("Desde", value=date(date.today().year, 1, 1))
    fecha_hasta = col3.date_input("Hasta", value=date.today())
    estado_sel  = col4.selectbox("Estado", ["Todas", "⏳ Pendientes", "✅ Pagas"])
    tipo_sel    = col5.selectbox("Tipo", ["Todos", "FC", "ND", "NC"])

    facturas = db.get_facturas(
        proveedor_id=prov_map[prov_sel],
        fecha_desde=fecha_desde.strftime('%Y-%m-%d'),
        fecha_hasta=fecha_hasta.strftime('%Y-%m-%d'),
    )

    if not facturas:
        st.info("No hay facturas para los filtros seleccionados.")
        st.stop()

    df = pd.DataFrame(facturas)
    df['fecha'] = df['fecha_display']

    # Filtro por estado de pago
    if estado_sel == "⏳ Pendientes":
        df = df[df['pagada'] == 0]
    elif estado_sel == "✅ Pagas":
        df = df[df['pagada'] == 1]

    # Filtro por tipo de comprobante
    if 'tipo' not in df.columns:
        df['tipo'] = 'FC'
    df['tipo'] = df['tipo'].fillna('FC')
    if tipo_sel != "Todos":
        df = df[df['tipo'] == tipo_sel]

    if df.empty:
        st.info("No hay facturas para los filtros seleccionados.")
        st.stop()

    # Columna de estado visual
    df = df.reset_index(drop=True)
    df['estado'] = df['pagada'].apply(lambda x: '✅ Pagada' if x else '⏳ Pendiente')
    df['fecha_pago_disp'] = df['fecha_pago_display']

    cols_tabla = ['tipo', 'estado', 'numero', 'fecha', 'proveedor_nombre', 'subtotal',
                  'iva_21', 'iva_105', 'total', 'moneda', 'fecha_pago_disp']
    cfg_tabla = {
        'tipo':             st.column_config.TextColumn('Tipo', width='small', help='FC=Factura · ND=Nota de Débito · NC=Nota de Crédito'),
        'estado':           st.column_config.TextColumn('Estado', width='small'),
        'numero':           'Número',
        'fecha':            'Fecha',
        'proveedor_nombre': 'Proveedor',
        'subtotal': st.column_config.NumberColumn('Subtotal',   format="$%.2f"),
        'iva_21':   st.column_config.NumberColumn('IVA 21%',    format="$%.2f"),
        'iva_105':  st.column_config.NumberColumn('IVA 10.5%',  format="$%.2f"),
        'total':    st.column_config.NumberColumn('Total',      format="$%.2f"),
        'moneda':   st.column_config.TextColumn('Moneda', width='small'),
        'fecha_pago_disp': 'Fecha pago',
    }

    st.caption("👆 Hacé clic en una fila para ver el comprobante original abajo.")

    # Tabla con selección de fila (si la versión de Streamlit lo soporta)
    fila_sel = None
    try:
        event = st.dataframe(
            df[cols_tabla], use_container_width=True, hide_index=True,
            column_config=cfg_tabla, on_select="rerun", selection_mode="single-row",
            key="tabla_facturas",
        )
        rows_sel = list(event.selection.rows)
        if rows_sel:
            fila_sel = df.iloc[rows_sel[0]]
    except TypeError:
        # Versión vieja de Streamlit sin selección → tabla normal
        st.dataframe(df[cols_tabla], use_container_width=True, hide_index=True,
                     column_config=cfg_tabla)

    # ── Visor del comprobante seleccionado ───────────────────────────────────
    if fila_sel is not None:
        st.divider()
        st.markdown(f"#### 📎 Comprobante: {fila_sel['numero']} — {fila_sel['proveedor_nombre']}")
        archivo = fila_sel.get('archivo_path')
        if not archivo or not Path(str(archivo)).exists():
            st.warning(
                "No hay archivo original guardado para este comprobante. "
                "Se guarda automáticamente a partir de ahora; los cargados antes "
                "no tienen copia. Volvé a subirlo si querés verlo."
            )
        else:
            ruta = Path(str(archivo))
            datos = ruta.read_bytes()
            st.download_button("⬇️ Descargar original", datos,
                               file_name=ruta.name, key="dl_comp")
            ext = ruta.suffix.lower()
            if ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'):
                st.image(datos, use_container_width=True)
            elif ext == '.pdf':
                b64 = base64.b64encode(datos).decode()
                st.markdown(
                    f'<iframe src="data:application/pdf;base64,{b64}" '
                    f'width="100%" height="800" style="border:1px solid #d8e5f5;border-radius:8px;"></iframe>',
                    unsafe_allow_html=True,
                )
                st.caption("Si el PDF no se ve, usá el botón de descarga.")

    total_ars = df.loc[df['moneda'] == 'ARS', 'total'].sum()
    total_usd = df.loc[df['moneda'] == 'USD', 'total'].sum()
    st.caption(
        f"{len(facturas)} facturas — "
        f"Total ARS: **${total_ars:,.2f}**"
        + (f"  |  Total USD: **U$S {total_usd:,.2f}**" if total_usd else "")
    )

    # ── Registrar pagos ──────────────────────────────────────────────────────
    st.divider()
    todas_facturas = db.get_facturas(
        proveedor_id=prov_map[prov_sel],
        fecha_desde=fecha_desde.strftime('%Y-%m-%d'),
        fecha_hasta=fecha_hasta.strftime('%Y-%m-%d'),
    )
    pendientes = [f for f in todas_facturas if not f.get('pagada')]
    pagas      = [f for f in todas_facturas if f.get('pagada')]

    with st.expander("💳 Registrar pago"):
        if pendientes:
            st.markdown("**Marcar como pagada**")
            opc_pend = {
                f"{f['numero']}  —  {f['proveedor_nombre']}  —  ${f['total']:,.0f}": f['id']
                for f in pendientes
            }
            sel_pend   = st.selectbox("Factura pendiente", list(opc_pend.keys()), key="sel_pend")
            fecha_pago = st.date_input("Fecha de pago", value=date.today(), key="fecha_pago_inp")
            if st.button("✅ Marcar como pagada", type="primary", key="btn_pagar"):
                db.marcar_pagada(opc_pend[sel_pend], fecha_pago.strftime('%Y-%m-%d'))
                st.success("✅ Factura marcada como pagada.")
                st.rerun()
        else:
            st.success("🎉 ¡Todas las facturas del período están pagas!")

        if pagas:
            st.markdown("---")
            st.markdown("**Deshacer pago** (marcar como pendiente)")
            opc_paga = {
                f"{f['numero']}  —  {f['proveedor_nombre']}  —  pagada {f['fecha_pago_display']}": f['id']
                for f in pagas
            }
            sel_paga = st.selectbox("Factura pagada", list(opc_paga.keys()), key="sel_paga")
            if st.button("↩️ Marcar como pendiente", key="btn_impagar"):
                db.marcar_impaga(opc_paga[sel_paga])
                st.rerun()

    # ── Eliminar factura ─────────────────────────────────────────────────────
    st.divider()
    with st.expander("🗑️ Eliminar una factura"):
        opciones = {
            f"{f['numero']}  —  {f['proveedor_nombre']}  —  {f['fecha_display']}": f['id']
            for f in facturas
        }
        seleccion = st.selectbox("Seleccioná la factura a eliminar", list(opciones.keys()))
        fac_id_del = opciones[seleccion]

        st.warning(f"⚠️ Esto eliminará la factura **{seleccion}** y todos sus ítems. Esta acción no se puede deshacer.")

        col_si, col_no = st.columns([1, 4])
        if col_si.button("🗑️ Sí, eliminar", key=f"del_{fac_id_del}", type="primary"):
            if not hasattr(db, 'delete_factura'):
                st.error("⚠️ El programa no está actualizado. Ejecutá ACTUALIZAR.bat y volvé a intentar.")
            else:
                db.delete_factura(fac_id_del)
                st.success("✅ Factura eliminada correctamente.")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# ✅  CONTROL (conciliación con sistema de gestión vía Excel)
# ─────────────────────────────────────────────────────────────────────────────
elif page == "✅ Control":
    _page_header("✅", "Control con gestión", "Subí el Excel de tu sistema y te digo qué facturas faltan cargar")

    import re as _re

    def _norm_num(x):
        """Normaliza un número de comprobante a solo dígitos (ignora guiones, espacios, letras)."""
        return _re.sub(r'\D', '', str(x or ''))

    st.markdown(
        "Subí un Excel (`.xlsx`) o CSV exportado de tu sistema de gestión. "
        "Tiene que tener una columna con el **número de comprobante** "
        "(y si querés, proveedor, fecha y total para ver el detalle)."
    )

    archivo = st.file_uploader("Archivo de gestión (Excel o CSV)",
                               type=["xlsx", "xls", "csv"], key="ctrl_file")
    if not archivo:
        st.info("Esperando el archivo…")
        st.stop()

    # Leer el archivo
    try:
        nombre_low = archivo.name.lower()
        if nombre_low.endswith('.csv'):
            df_g = pd.read_csv(archivo, sep=None, engine='python', dtype=str)
        elif nombre_low.endswith('.xls'):
            df_g = pd.read_excel(archivo, dtype=str, engine='xlrd')
        else:
            df_g = pd.read_excel(archivo, dtype=str, engine='openpyxl')
    except ImportError:
        st.error(
            "Falta una librería para leer este Excel. En la PC del servidor:\n"
            "1) Cerrá el servidor  2) Ejecutá **ACTUALIZAR.bat**  3) Reabrí el servidor.\n\n"
            "Si sigue fallando, abrí el Excel y guardalo como **.xlsx** (Excel moderno)."
        )
        st.stop()
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")
        st.stop()

    df_g = df_g.fillna('')
    if df_g.empty:
        st.warning("El archivo está vacío.")
        st.stop()

    st.markdown("#### Vista previa del archivo")
    st.dataframe(df_g.head(10), use_container_width=True, hide_index=True)

    # Detectar automáticamente las columnas (keyword más específico primero)
    cols = list(df_g.columns)
    def _guess(cands):
        for k in cands:
            for c in cols:
                if k in str(c).lower():
                    return c
        return None
    col_num_def  = _guess(['numfac', 'numero', 'nrofac', 'nro', 'comprob', 'num', 'fact'])
    col_suc_def  = _guess(['sucursal', 'punto', 'pdv', 'ptovta', 'pto'])
    col_prov_def = _guess(['razon', 'razón', 'prove', 'nombre'])

    st.markdown("#### Indicá las columnas")
    c1, c2, c3 = st.columns(3)
    col_num  = c1.selectbox("NÚMERO de comprobante", cols,
                            index=cols.index(col_num_def) if col_num_def in cols else 0)
    opc = ["(ninguna)"] + cols
    col_suc  = c2.selectbox("SUCURSAL / Punto de venta", opc,
                            index=opc.index(col_suc_def) if col_suc_def in cols else 0)
    col_prov = c3.selectbox("PROVEEDOR (opcional)", opc,
                            index=opc.index(col_prov_def) if col_prov_def in cols else 0)

    if not st.button("🔍 Comparar con lo cargado", type="primary"):
        st.stop()

    usar_suc = col_suc != "(ninguna)"

    def _clave_gestion(row):
        """Clave por VALOR numérico (ignora ceros a la izquierda)."""
        n = _norm_num(row[col_num])
        if not n:
            return None
        if usar_suc:
            s = _norm_num(row[col_suc])
            return (int(s) if s else 0, int(n))
        return (int(n),)

    def _clave_app(numero):
        grupos = _re.findall(r'\d+', str(numero or ''))
        if not grupos:
            return None
        if usar_suc:
            # 2+ grupos → (sucursal, secuencia) ; 1 grupo → (0, seq)
            if len(grupos) >= 2:
                return (int(grupos[0]), int(grupos[-1]))
            return (0, int(grupos[0]))
        return (int(grupos[-1]),)

    # Claves del sistema de gestión (Excel)
    df_g['_clave'] = df_g.apply(_clave_gestion, axis=1)
    df_g = df_g[df_g['_clave'].notna()]
    claves_gestion = set(df_g['_clave'])

    # Claves cargadas en la app
    cargadas = db.get_facturas()
    claves_app = {_clave_app(f['numero']) for f in cargadas}
    claves_app.discard(None)

    # Comparación
    faltan_cargar = df_g[~df_g['_clave'].isin(claves_app)].copy()   # en Excel, no en app
    claves_solo_app = claves_app - claves_gestion                   # en app, no en Excel

    m1, m2, m3 = st.columns(3)
    m1.metric("📋 En tu gestión", f"{len(claves_gestion):,}")
    m2.metric("✅ Ya cargadas", f"{len(claves_gestion) - len(faltan_cargar):,}")
    m3.metric("⚠️ Faltan cargar", f"{len(faltan_cargar):,}")

    st.divider()
    st.markdown("### ⚠️ Facturas que FALTAN cargar en la app")
    if faltan_cargar.empty:
        st.success("🎉 ¡Están todas cargadas! No falta ninguna factura de tu sistema de gestión.")
    else:
        st.caption(f"{len(faltan_cargar)} comprobante(s) están en tu gestión pero no en la app:")
        mostrar = [col_num] + ([col_prov] if col_prov != "(ninguna)" else [])
        # agregar columnas extra útiles si existen
        for extra in cols:
            cl = str(extra).lower()
            if extra not in mostrar and any(k in cl for k in ['fecha', 'total', 'import', 'monto']):
                mostrar.append(extra)
        st.dataframe(faltan_cargar[mostrar], use_container_width=True, hide_index=True)

        bc1, bc2 = st.columns(2)
        bc1.download_button(
            "⬇️ Descargar CSV",
            faltan_cargar[mostrar].to_csv(index=False).encode('utf-8'),
            file_name="facturas_faltantes.csv",
        )
        try:
            pdf_bytes = generar_pdf_tabla(
                faltan_cargar[mostrar], mostrar,
                titulo="Facturas faltantes de cargar",
                subtitulo=f"{len(faltan_cargar)} comprobantes pendientes",
            )
            bc2.download_button(
                "📄 Descargar PDF",
                pdf_bytes,
                file_name="facturas_faltantes.pdf",
                mime="application/pdf",
            )
        except ImportError:
            bc2.warning("Para el PDF: actualizá y reiniciá el servidor (falta la librería fpdf2).")
        except Exception as e:
            bc2.error(f"No se pudo generar el PDF: {e}")

    # Extra: cargadas en la app que NO están en la gestión (posible error de carga)
    if claves_solo_app:
        with st.expander(f"🔎 En la app pero NO en tu gestión ({len(claves_solo_app)})"):
            st.caption("Pueden ser facturas que cargaste de más, o que tu sistema todavía no tiene.")
            extra_rows = [f for f in cargadas if _clave_app(f['numero']) in claves_solo_app]
            df_extra = pd.DataFrame(extra_rows)
            if not df_extra.empty:
                st.dataframe(
                    df_extra[['numero', 'fecha_display', 'proveedor_nombre', 'total', 'moneda']],
                    use_container_width=True, hide_index=True,
                    column_config={
                        'numero': 'Número', 'fecha_display': 'Fecha',
                        'proveedor_nombre': 'Proveedor',
                        'total': st.column_config.NumberColumn('Total', format="%.2f"),
                        'moneda': 'Moneda',
                    })


# ─────────────────────────────────────────────────────────────────────────────
# 📊  CUENTA CORRIENTE
# ─────────────────────────────────────────────────────────────────────────────
elif page == "📊 Cta. Cte.":
    _page_header("📊", "Cuenta Corriente", "Saldo y movimientos por proveedor")

    proveedores = db.get_proveedores()
    if not proveedores:
        st.info("No hay proveedores cargados aún.")
        st.stop()

    # ── Resumen general ──────────────────────────────────────────────────────
    saldos = db.get_saldos_proveedores()
    df_sal = pd.DataFrame(saldos)

    st.markdown("#### Resumen de saldos")

    # Métricas globales — ARS y USD por separado
    deuda_ars = df_sal['saldo_ars'].clip(lower=0).sum()
    deuda_usd = df_sal['saldo_usd'].clip(lower=0).sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📋 Facturado ARS", f"${df_sal['fact_ars'].sum():,.0f}")
    m2.metric("💸 Deuda ARS",     f"${deuda_ars:,.0f}")
    m3.metric("📋 Facturado USD", f"U$S {df_sal['fact_usd'].sum():,.2f}")
    m4.metric("💸 Deuda USD",     f"U$S {deuda_usd:,.2f}")

    def _color_saldo(val):
        if val > 0:
            return 'color: #c0392b; font-weight:600'
        elif val == 0:
            return 'color: #27ae60; font-weight:600'
        return 'color: #2980b9; font-weight:600'

    # Mostrar solo filas con algún movimiento
    df_v = df_sal[(df_sal['fact_ars'] != 0) | (df_sal['fact_usd'] != 0) |
                  (df_sal['pago_ars'] != 0) | (df_sal['pago_usd'] != 0)].copy()
    df_show = df_v[['nombre', 'saldo_ars', 'saldo_usd']].copy()
    df_show.columns = ['Proveedor', 'Saldo ARS', 'Saldo USD']
    _styler = df_show.style
    _apply = _styler.map if hasattr(_styler, 'map') else _styler.applymap
    _styler = _apply(_color_saldo, subset=['Saldo ARS', 'Saldo USD'])
    st.dataframe(
        _styler,
        use_container_width=True,
        hide_index=True,
        column_config={
            'Saldo ARS': st.column_config.NumberColumn(format="$%.2f"),
            'Saldo USD': st.column_config.NumberColumn(format="U$S %.2f"),
        }
    )
    st.caption("🔴 Saldo positivo = deuda pendiente   |   🟢 Saldo cero = al día   |   🔵 Negativo = saldo a favor")

    st.divider()

    # ── Detalle por proveedor ────────────────────────────────────────────────
    st.markdown("#### Movimientos por proveedor")
    prov_map_cc = {p['nombre']: p['id'] for p in proveedores}
    prov_sel_cc = st.selectbox("Proveedor", list(prov_map_cc.keys()), key="cc_prov")
    prov_id_cc  = prov_map_cc[prov_sel_cc]

    # Elegir moneda según las que tenga el proveedor
    monedas_prov = db.get_monedas_proveedor(prov_id_cc)
    if len(monedas_prov) > 1:
        moneda_cc = st.radio("Moneda", monedas_prov, horizontal=True, key="cc_moneda_sel")
    else:
        moneda_cc = monedas_prov[0]

    simbolo = "U$S" if moneda_cc == 'USD' else "$"
    movs, saldo_actual = db.get_cuenta_corriente(prov_id_cc, moneda_cc)

    ca1, ca2, ca3 = st.columns(3)
    total_f_prov = sum(m['debe']  for m in movs)
    total_p_prov = sum(m['haber'] for m in movs)
    ca1.metric(f"Facturado {moneda_cc}", f"{simbolo} {total_f_prov:,.2f}")
    ca2.metric(f"Pagado {moneda_cc}",    f"{simbolo} {total_p_prov:,.2f}")
    ca3.metric(f"Saldo {moneda_cc}",     f"{simbolo} {saldo_actual:,.2f}")

    if movs:
        df_movs = pd.DataFrame(movs)
        df_movs['tipo_icon'] = df_movs['tipo'].map({
            'FACTURA': '🧾 Factura', 'N. DÉBITO': '🟧 N. Débito',
            'N. CRÉDITO': '🟦 N. Crédito', 'PAGO': '💳 Pago',
        }).fillna(df_movs['tipo'])
        st.dataframe(
            df_movs[['fecha_display', 'tipo_icon', 'descripcion', 'debe', 'haber', 'saldo']],
            use_container_width=True,
            hide_index=True,
            column_config={
                'fecha_display': 'Fecha',
                'tipo_icon':     st.column_config.TextColumn('Tipo', width='small'),
                'descripcion':   'Descripción',
                'debe':  st.column_config.NumberColumn(f'Debe ({moneda_cc})',  format=f"{simbolo} %.2f"),
                'haber': st.column_config.NumberColumn(f'Haber ({moneda_cc})', format=f"{simbolo} %.2f"),
                'saldo': st.column_config.NumberColumn(f'Saldo ({moneda_cc})', format=f"{simbolo} %.2f"),
            }
        )
    else:
        st.info("No hay movimientos en esta moneda para este proveedor.")

    # ── Registrar pago ───────────────────────────────────────────────────────
    st.divider()
    with st.expander("💳 Registrar pago a este proveedor"):
        cp1, cp2, cp3, cp4 = st.columns([2, 1, 1, 2])
        monto_pago    = cp1.number_input("Monto", min_value=0.0, step=1000.0, key="cc_monto")
        moneda_pago   = cp2.selectbox("Moneda", ['ARS', 'USD'],
                                      index=(['ARS', 'USD'].index(moneda_cc) if moneda_cc in ('ARS', 'USD') else 0),
                                      key="cc_moneda_pago")
        fecha_pago_cc = cp3.date_input("Fecha", value=date.today(), key="cc_fecha")
        desc_pago     = cp4.text_input("Descripción (opcional)", placeholder="ej: Transferencia banco", key="cc_desc")

        if st.button("💳 Registrar pago", type="primary", key="cc_btn_pago"):
            if monto_pago <= 0:
                st.error("El monto debe ser mayor a cero.")
            else:
                db.insert_pago(
                    prov_id_cc,
                    monto_pago,
                    fecha_pago_cc.strftime('%d/%m/%Y'),
                    desc_pago or 'Pago',
                    moneda_pago,
                )
                sim = "U$S" if moneda_pago == 'USD' else "$"
                st.success(f"✅ Pago de **{sim} {monto_pago:,.2f}** registrado para {prov_sel_cc}.")
                st.rerun()

    # ── Eliminar un pago ─────────────────────────────────────────────────────
    pagos_prov = [m for m in movs if m['tipo'] == 'PAGO']
    if pagos_prov:
        with st.expander("🗑️ Eliminar un pago registrado"):
            opc_pagos = {
                f"{m['fecha_display']}  —  {m['descripcion']}  —  {simbolo} {m['haber']:,.2f}": m['ref_id']
                for m in pagos_prov
            }
            sel_del_pago = st.selectbox("Pago a eliminar", list(opc_pagos.keys()), key="cc_del_pago")
            if st.button("🗑️ Eliminar pago", key="cc_btn_del_pago"):
                db.delete_pago(opc_pagos[sel_del_pago])
                st.success("Pago eliminado.")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 🔍  SKUs
# ─────────────────────────────────────────────────────────────────────────────
elif page == "🔍 SKUs":
    _page_header("🔍", "SKUs", "Búsqueda de códigos y evolución de precios")

    proveedores = db.get_proveedores()
    prov_map    = {"Todos": None} | {p['nombre']: p['id'] for p in proveedores}

    col1, col2 = st.columns([3, 1])
    buscar   = col1.text_input(
        "Buscar por código o descripción (opcional si elegís un proveedor)",
        placeholder="ej: VAMD100CA3  o  VOLTAMETRO  o  087402",
    )
    prov_sel = col2.selectbox("Proveedor", list(prov_map.keys()), key="prov_sku")

    prov_id_sku = prov_map[prov_sel]

    # Permitir buscar sin texto si hay un proveedor elegido → lista todos sus productos
    if not buscar and prov_id_sku is None:
        st.info("Escribí un código/descripción, o elegí un proveedor para ver todos sus productos.")
        st.stop()

    # Más resultados cuando se listan todos los productos de un proveedor
    limite = 500 if not buscar else 100
    resultados = db.search_skus(buscar, prov_id_sku, limit=limite)
    if not resultados:
        st.warning("No se encontraron productos para ese criterio.")
        st.stop()

    if not buscar:
        st.caption(f"Mostrando {len(resultados)} producto(s) de **{prov_sel}** "
                   f"(ordenados por más comprados).")

    df_res = pd.DataFrame(resultados)
    st.dataframe(
        df_res[['sku', 'descripcion', 'proveedor_nombre',
                'veces_comprado', 'total_unidades', 'ultima_compra']],
        use_container_width=True,
        column_config={
            'sku':              'Código',
            'descripcion':      'Descripción',
            'proveedor_nombre': 'Proveedor',
            'veces_comprado':   'Facturas',
            'total_unidades':   st.column_config.NumberColumn('Unidades', format="%.0f"),
            'ultima_compra':    'Última compra',
        },
        hide_index=True,
    )

    st.divider()
    _desc_por_sku = {r['sku']: r['descripcion'] for r in resultados}
    skus_sel = st.multiselect(
        "Elegí uno o varios artículos para ver la evolución de precio:",
        [r['sku'] for r in resultados],
        format_func=lambda s: f"{s}  —  {_desc_por_sku.get(s, '')}",
    )

    if skus_sel:
        # Recolectar el historial de cada SKU elegido
        frames = []
        for sku in skus_sel:
            det = db.get_items_by_sku(sku, prov_id_sku)
            if det:
                dft = pd.DataFrame(det)
                dft['sku'] = sku
                frames.append(dft)

        if not frames:
            st.info("Sin datos de compra para los artículos elegidos.")
            st.stop()

        df_all = pd.concat(frames, ignore_index=True)
        moneda = df_all['moneda'].iloc[0] if 'moneda' in df_all.columns else 'ARS'

        # Gráfico: una línea por artículo
        fig = go.Figure()
        for sku in skus_sel:
            d = df_all[df_all['sku'] == sku].sort_values('fecha')
            if d.empty:
                continue
            etiqueta = f"{sku} — {_desc_por_sku.get(sku, '')[:30]}"
            fig.add_trace(go.Scatter(
                x=d['fecha_display'],
                y=d['precio_neto_unit'],
                mode='lines+markers',
                name=etiqueta,
                marker=dict(size=7),
            ))
        fig.update_layout(
            title="Evolución de precio neto por artículo",
            xaxis_title='Fecha',
            yaxis_title=f'Precio neto unitario ({moneda})',
            hovermode='x unified',
            legend=dict(orientation='h', yanchor='bottom', y=-0.4),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Tabla historial combinada
        cols_show = [c for c in
            ['sku', 'factura_numero', 'fecha_display', 'proveedor_nombre',
             'cantidad', 'precio_unit', 'descuento_pct',
             'precio_neto_unit', 'iva_pct', 'subtotal_siva']
            if c in df_all.columns]
        st.dataframe(
            df_all[cols_show].rename(columns={
                'sku':             'Código',
                'factura_numero':  'Factura',
                'fecha_display':   'Fecha',
                'proveedor_nombre':'Proveedor',
                'cantidad':        'Cant.',
                'precio_unit':     'Precio lista',
                'descuento_pct':   'Dto%',
                'precio_neto_unit':'Precio neto',
                'iva_pct':         'IVA%',
                'subtotal_siva':   'Subtotal s/IVA',
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("👆 Seleccioná artículos arriba para ver y comparar su evolución de precio.")


# ─────────────────────────────────────────────────────────────────────────────
# ⚖️  COMPARAR ENTRE PROVEEDORES
# ─────────────────────────────────────────────────────────────────────────────
elif page == "⚖️ Comparar":
    _page_header("⚖️", "Comparar proveedores", "Compará precios del mismo producto entre distintos proveedores")

    keyword = st.text_input(
        "Descripción del producto",
        placeholder="ej: caja toma  |  disyuntor  |  cable  |  panel LED",
    )

    if not keyword or len(keyword) < 3:
        st.info("Escribí al menos 3 letras para buscar.")
        st.stop()

    resumen, detalle = db.comparar_entre_proveedores(keyword)

    if not resumen:
        st.warning("No se encontraron productos con esa descripción.")
        st.stop()

    # ── Tabla resumen ────────────────────────────────────────────────────────
    st.markdown(f"### Resultados para **\"{keyword}\"**")
    df_res = pd.DataFrame(resumen)

    st.dataframe(
        df_res[[
            'proveedor', 'codigo', 'descripcion',
            'precio_min', 'precio_prom', 'precio_max',
            'total_unidades', 'facturas', 'ultima_compra', 'moneda'
        ]],
        use_container_width=True,
        column_config={
            'proveedor':      'Proveedor',
            'codigo':         'Código',
            'descripcion':    'Descripción',
            'precio_min':     st.column_config.NumberColumn('Precio mín.',  format="%.2f"),
            'precio_prom':    st.column_config.NumberColumn('Precio prom.', format="%.2f"),
            'precio_max':     st.column_config.NumberColumn('Precio máx.',  format="%.2f"),
            'total_unidades': st.column_config.NumberColumn('Unidades',     format="%.0f"),
            'facturas':       'Facturas',
            'ultima_compra':  'Última compra',
            'moneda':         'Moneda',
        },
        hide_index=True,
    )

    if not detalle:
        st.stop()

    df_det = pd.DataFrame(detalle)

    # ── Gráfico: último precio por proveedor (barras) ────────────────────────
    st.divider()
    st.markdown("#### Precio promedio por proveedor")

    fig_bar = px.bar(
        df_res,
        x='proveedor',
        y='precio_prom',
        color='proveedor',
        text='precio_prom',
        labels={'proveedor': 'Proveedor', 'precio_prom': 'Precio neto prom.'},
        title=f'Comparación de precio promedio — "{keyword}"',
    )
    fig_bar.update_traces(texttemplate='%{text:,.2f}', textposition='outside')
    fig_bar.update_layout(showlegend=False)
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── Gráfico: evolución histórica de precios por proveedor ────────────────
    if len(df_det) > 1:
        st.markdown("#### Evolución de precios en el tiempo")

        # Si hay productos con descripciones distintas, agrupar por descripción
        descripciones = df_det['descripcion'].unique()
        if len(descripciones) > 1:
            desc_sel = st.selectbox("Descripción específica:", descripciones)
            df_det = df_det[df_det['descripcion'] == desc_sel]

        fig_evo = px.line(
            df_det,
            x='fecha_display',
            y='precio_neto',
            color='proveedor',
            markers=True,
            labels={
                'fecha_display': 'Fecha',
                'precio_neto':   'Precio neto unitario',
                'proveedor':     'Proveedor',
            },
            title=f'Evolución de precios — "{keyword}"',
        )
        fig_evo.update_layout(hovermode='x unified')
        st.plotly_chart(fig_evo, use_container_width=True)

    # ── Mejor proveedor actual ───────────────────────────────────────────────
    st.divider()
    mejor = df_res.loc[df_res['precio_prom'].idxmin()]
    st.success(
        f"💡 **Proveedor más barato en promedio:** {mejor['proveedor']}  "
        f"— precio prom. **{mejor['precio_prom']:,.2f} {mejor['moneda']}**"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 🏢  PROVEEDORES
# ─────────────────────────────────────────────────────────────────────────────
elif page == "🏢 Proveedores":
    _page_header("🏢", "Proveedores", "Resumen de actividad por proveedor")

    proveedores = db.get_proveedores()
    if not proveedores:
        st.info("No hay proveedores cargados aún.")
        st.stop()

    for prov in proveedores:
        stats = db.get_resumen_proveedor(prov['id'])
        with st.expander(
            f"**{prov['nombre']}**  —  CUIT: {prov['cuit']}  —  "
            f"{stats['n_facturas']} facturas",
            expanded=False,
        ):
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Facturas",       stats['n_facturas'])
            c2.metric("SKUs distintos", stats['n_skus'])
            c3.metric("Total ARS",      f"${(stats['total_ars'] or 0):,.0f}")
            if stats.get('total_usd'):
                c4.metric("Total USD",  f"U$S {stats['total_usd']:,.2f}")
            c5.metric("Período",
                      f"{stats['primera']} → {stats['ultima']}")

            # Evolución mensual de gasto
            meses = db.get_compras_por_mes(prov['id'])
            if meses:
                df_m = pd.DataFrame(meses)
                fig = px.bar(
                    df_m, x='mes', y='total_ars',
                    title=f"Gasto mensual — {prov['nombre']}",
                    labels={'mes': 'Mes', 'total_ars': 'ARS equiv.'},
                )
                fig.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)

            # Top SKUs de este proveedor
            with db.get_conn() as conn:
                top_skus = conn.execute("""
                    SELECT i.sku, i.descripcion,
                           SUM(i.cantidad)    AS total_unid,
                           SUM(i.subtotal_siva) AS total_gasto
                    FROM items i
                    JOIN facturas f ON i.factura_id = f.id
                    WHERE f.proveedor_id = ?
                    GROUP BY i.sku
                    ORDER BY total_gasto DESC LIMIT 15
                """, (prov['id'],)).fetchall()
            if top_skus:
                df_ts = pd.DataFrame(
                    top_skus,
                    columns=['SKU','Descripción','Unidades','Gasto total']
                )
                st.dataframe(df_ts, use_container_width=True, hide_index=True)
