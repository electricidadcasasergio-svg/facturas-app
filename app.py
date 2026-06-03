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

# Forzar recarga del código desde disco en cada ejecución.
# Streamlit cachea los módulos importados; sin esto, los cambios de
# extractor.py / database.py no se aplican hasta reiniciar el servidor.
importlib.reload(extractor)
importlib.reload(db)

# Versión del programa (subila cada vez que hay cambios para verificar actualizaciones)
APP_VERSION = "2026.06.03-f"

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
    ["🏠 Inicio", "📤 Subir Facturas", "📄 Facturas", "📊 Cta. Cte.", "🔍 SKUs", "⚖️ Comparar", "🏢 Proveedores"],
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

    ITEM_COLS = ['sku', 'descripcion', 'cantidad', 'precio_unit',
                 'descuento_pct', 'precio_neto_unit', 'iva_pct', 'subtotal_siva']

    for f in uploaded:
        # Guardar temporalmente preservando la extensión original
        suffix = Path(f.name).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name

        # Pre-cargar config del proveedor (si ya fue procesado antes)
        try:
            cuit_hint = extractor.quick_get_cuit(tmp_path)
        except AttributeError:
            cuit_hint = None
        proveedor_config = db.get_proveedor_config(cuit_hint) if cuit_hint else None
        nombre_guardado  = (db.get_proveedor_nombre_por_cuit(cuit_hint)
                            if cuit_hint and hasattr(db, 'get_proveedor_nombre_por_cuit')
                            else None)

        with st.spinner(f"Procesando **{f.name}**…"):
            try:
                data = extractor.extract_invoice(tmp_path, config=proveedor_config)
                data['archivo_nombre'] = f.name
                error = None
            except Exception as e:
                data  = None
                error = str(e)
        Path(tmp_path).unlink(missing_ok=True)

        if error:
            st.error(f"❌ **{f.name}**: {error}")
            continue

        items = data.get('items', [])
        TIPO_LABEL = {'FC': 'Factura', 'ND': 'Nota de Débito', 'NC': 'Nota de Crédito'}
        tipo_doc = data.get('tipo', 'FC')
        label = (
            f"✅ {f.name}  —  "
            f"{TIPO_LABEL.get(tipo_doc, 'Factura')}  |  "
            f"{data.get('proveedor_nombre','?')}  |  "
            f"{data.get('numero','?')}  |  "
            f"{data.get('fecha','?')}"
        )

        with st.expander(label, expanded=True):

            # Aviso de tipo de comprobante
            if tipo_doc == 'NC':
                st.info("🟦 **Nota de Crédito** — se RESTARÁ del saldo del proveedor en la cuenta corriente.")
            elif tipo_doc == 'ND':
                st.info("🟧 **Nota de Débito** — se SUMARÁ al saldo del proveedor (igual que una factura).")

            # Aviso: factura de VENTA emitida por Casa Sergio (no es una compra)
            if data.get('es_venta'):
                st.error(
                    "🛑 **Esta parece una factura de VENTA emitida por Casa Sergio**, "
                    "no una compra a un proveedor. Si la guardás, se registrará igual — "
                    "pero normalmente acá cargamos solo **facturas de compra**. "
                    "Revisá antes de guardar."
                )

            # Indicador de proveedor conocido
            if proveedor_config:
                st.success("✅ Proveedor conocido — se usó perfil guardado de facturas anteriores.")

            # ── Campos editables ─────────────────────────────────────────
            st.markdown("#### Datos del encabezado")
            st.caption("Revisá y corregí si algo no se detectó bien.")

            c1, c2 = st.columns(2)
            # Prioridad del nombre del proveedor:
            #  1) si el extractor lo detectó del mapa de CUITs conocidos → es confiable
            #  2) si no, el nombre guardado en la base (corrección previa del usuario)
            #  3) si no, lo que haya detectado el extractor
            if data.get('proveedor_nombre_fiable'):
                nombre_det = data.get('proveedor_nombre', '')
            else:
                nombre_det = nombre_guardado or data.get('proveedor_nombre', '')
            cuit_det    = data.get('proveedor_cuit', '')
            numero_det  = data.get('numero', '')
            fecha_det   = data.get('fecha', date.today().strftime('%d/%m/%Y'))
            moneda_det  = data.get('moneda', 'ARS')
            tc_det      = data.get('tipo_cambio', 1.0)

            prov_nombre = c1.text_input(
                "Proveedor" + (" ⚠️ no detectado" if not nombre_det else ""),
                value=nombre_det, key=f"nombre_{f.name}"
            )
            prov_cuit = c1.text_input(
                "CUIT" + (" ⚠️ no detectado" if not cuit_det else ""),
                value=cuit_det, key=f"cuit_{f.name}"
            )
            fac_numero = c2.text_input(
                "Número de factura" + (" ⚠️ no detectado" if not numero_det else ""),
                value=numero_det, key=f"nro_{f.name}"
            )
            fac_fecha = c2.text_input(
                "Fecha (DD/MM/AAAA)",
                value=fecha_det, key=f"fecha_{f.name}"
            )

            c3, c4 = st.columns(2)
            moneda = c3.selectbox("Moneda", ['ARS', 'USD'],
                                  index=0 if moneda_det == 'ARS' else 1,
                                  key=f"moneda_{f.name}")
            if moneda == 'USD':
                tc = c4.number_input("Tipo de cambio (ARS/USD)",
                                     value=float(tc_det), min_value=1.0,
                                     key=f"tc_{f.name}")
            else:
                tc = 1.0

            # ── Ítems — tabla editable ───────────────────────────────────
            st.markdown("#### Ítems")
            if not items:
                st.warning(
                    "⚠️ No se encontraron ítems automáticamente. "
                    "Podés agregarlos manualmente en la tabla de abajo."
                )

            # Preparar DataFrame con las columnas estándar
            df_items = (
                pd.DataFrame(items).reindex(columns=ITEM_COLS)
                if items
                else pd.DataFrame(columns=ITEM_COLS)
            )
            # Valores por defecto para columnas numéricas
            for col, default in [('cantidad', 1.0), ('precio_unit', 0.0),
                                  ('descuento_pct', 0.0), ('precio_neto_unit', 0.0),
                                  ('iva_pct', 21.0), ('subtotal_siva', 0.0)]:
                df_items[col] = pd.to_numeric(df_items.get(col, default), errors='coerce').fillna(default)
            df_items['sku']         = df_items.get('sku', '').fillna('').astype(str)
            df_items['descripcion'] = df_items.get('descripcion', '').fillna('').astype(str)

            edited_items_df = st.data_editor(
                df_items,
                column_config={
                    'sku':              st.column_config.TextColumn('Código / SKU',   required=True),
                    'descripcion':      st.column_config.TextColumn('Descripción'),
                    'cantidad':         st.column_config.NumberColumn('Cantidad',      format="%.2f"),
                    'precio_unit':      st.column_config.NumberColumn('Precio lista',  format="%.4f"),
                    'descuento_pct':    st.column_config.NumberColumn('Dto %',         format="%.2f"),
                    'precio_neto_unit': st.column_config.NumberColumn('Precio neto',   format="%.4f"),
                    'iva_pct':          st.column_config.NumberColumn('IVA %',         format="%.1f"),
                    'subtotal_siva':    st.column_config.NumberColumn('Subtotal s/IVA', format="%.2f"),
                },
                num_rows="dynamic",
                use_container_width=True,
                key=f"items_{f.name}",
            )
            n_items = len(edited_items_df[edited_items_df['sku'].str.strip() != ''])
            st.caption(f"{n_items} ítem(s)  —  podés agregar/editar/eliminar filas directamente en la tabla.")

            # ── Guardar ──────────────────────────────────────────────────
            if not prov_nombre:
                st.error("Completá el nombre del proveedor antes de guardar.")
            elif not fac_numero:
                st.error("Completá el número de factura antes de guardar.")
            elif st.button("💾 Guardar en base de datos", key=f"save_{f.name}"):
                # Tomar ítems del editor (solo filas con SKU no vacío)
                items_to_save = [
                    row for row in edited_items_df.to_dict('records')
                    if str(row.get('sku', '')).strip()
                ]
                # Asegurar moneda en cada ítem
                for it in items_to_save:
                    it.setdefault('moneda', moneda)

                try:
                    prov_id = db.upsert_proveedor(
                        prov_nombre,
                        prov_cuit or f'sin-cuit-{prov_nombre[:20]}',
                        moneda,
                    )
                    fac_id = db.insert_factura(
                        prov_id,
                        fac_numero,
                        fac_fecha,
                        data.get('subtotal', 0),
                        data.get('iva_21', 0),
                        data.get('iva_105', 0),
                        data.get('percepciones', 0),
                        data.get('total', 0),
                        moneda,
                        tc,
                        f.name,
                        data.get('cae', ''),
                        data.get('tipo', 'FC'),
                    )
                    if fac_id:
                        if items_to_save:
                            db.insert_items(fac_id, items_to_save)

                        # Guardar perfil del proveedor para mejorar futuras extracciones
                        discovered = data.get('_discovered_config', {})
                        if discovered and prov_cuit:
                            db.save_proveedor_config(prov_cuit, discovered)

                        st.success(
                            f"✅ Guardada — **{prov_nombre}** — {len(items_to_save)} ítems."
                            + (" 🧠 Perfil de proveedor aprendido." if discovered and prov_cuit else "")
                        )
                    else:
                        st.warning("⚠️ Esta factura ya estaba cargada (número duplicado).")
                except Exception as e:
                    st.error(f"Error al guardar: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 📄  FACTURAS
# ─────────────────────────────────────────────────────────────────────────────
elif page == "📄 Facturas":
    _page_header("📄", "Facturas", "Historial de facturas cargadas")

    proveedores = db.get_proveedores()
    prov_map    = {"Todos": None} | {p['nombre']: p['id'] for p in proveedores}

    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    prov_sel    = col1.selectbox("Proveedor", list(prov_map.keys()))
    fecha_desde = col2.date_input("Desde", value=date(date.today().year, 1, 1))
    fecha_hasta = col3.date_input("Hasta", value=date.today())
    estado_sel  = col4.selectbox("Estado", ["Todas", "⏳ Pendientes", "✅ Pagas"])

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

    if df.empty:
        st.info("No hay facturas para los filtros seleccionados.")
        st.stop()

    # Columna de estado visual
    df['estado'] = df['pagada'].apply(lambda x: '✅ Pagada' if x else '⏳ Pendiente')
    df['fecha_pago_disp'] = df['fecha_pago_display']

    st.dataframe(
        df[['estado', 'numero', 'fecha', 'proveedor_nombre', 'subtotal',
            'iva_21', 'iva_105', 'total', 'moneda', 'fecha_pago_disp']],
        use_container_width=True,
        column_config={
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
        },
        hide_index=True,
    )

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
        "Buscar por código o descripción",
        placeholder="ej: VAMD100CA3  o  VOLTAMETRO  o  087402",
    )
    prov_sel = col2.selectbox("Proveedor", list(prov_map.keys()), key="prov_sku")

    if not buscar:
        st.info("Escribí un código o descripción para buscar.")
        st.stop()

    resultados = db.search_skus(buscar, prov_map[prov_sel])
    if not resultados:
        st.warning("No se encontraron SKUs con esos términos.")
        st.stop()

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
    sku_sel = st.selectbox(
        "Ver evolución de precio para:",
        [r['sku'] for r in resultados],
        format_func=lambda s: f"{s}  —  "
            + next((r['descripcion'] for r in resultados if r['sku'] == s), ''),
    )

    if sku_sel:
        det = db.get_items_by_sku(sku_sel, prov_map[prov_sel])
        if not det:
            st.info("Sin datos de compra para este SKU.")
            st.stop()

        df_det = pd.DataFrame(det)
        moneda = df_det['moneda'].iloc[0] if 'moneda' in df_det.columns else 'ARS'

        # Gráfico evolución precio neto
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_det['fecha_display'],
            y=df_det['precio_neto_unit'],
            mode='lines+markers',
            name='Precio neto/u',
            line=dict(color='#1558a7', width=2),
            marker=dict(size=7),
        ))
        fig.update_layout(
            title=f"Evolución precio neto — {sku_sel}",
            xaxis_title='Fecha',
            yaxis_title=f'Precio neto unitario ({moneda})',
            hovermode='x unified',
        )
        st.plotly_chart(fig, use_container_width=True)

        # Tabla historial
        cols_show = [c for c in
            ['factura_numero', 'fecha_display', 'proveedor_nombre',
             'cantidad', 'precio_unit', 'descuento_pct',
             'precio_neto_unit', 'iva_pct', 'subtotal_siva']
            if c in df_det.columns]
        st.dataframe(
            df_det[cols_show].rename(columns={
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
