"""
NEXUS QUANT LAB — V5.3 MASTER "WAR ROOM" Visualizer
=====================================================
war_map_generator_v2.py

GENERADOR DE MAPAS DE GUERRA V5.3 — BLINDAJE TOTAL

Capas visuales:
  1. Velas H1 en vivo (desde MT5) — Zoom 35 velas
  2. Zona de Oro (OTE — Optimal Trade Entry 61.8%-79.0%) con GLOW
  3. Muros Púrpuras (HTF Liquidity — D1 High/Low) a la IZQUIERDA
  4. Niveles Fibonacci (618, 705, 790) con etiquetas fondo ORO a la DERECHA
  5. Símbolos $ de LuxAlgo (Sweep de liquidez)
  6. Bid/Ask en vivo con etiquetas a 5 decimales
  7. Detección dinámica de días (OPEN DAY) — NUNCA FALLA
  8. Killzones (08:00-12:00) para cada día visible
  9. Smart Labels con anticolisión (1.5 pips de margen)

Integración:
  from production.war_map_generator_v2 import generate_war_map
  generate_war_map(df=df, proba=0.82, direction=1, ...)

Autor: Nexus Quant Lab
Fecha: 2026-06-02 (V5.3 — Master Blindaje)
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import numpy as np
import plotly.graph_objects as go

logger = logging.getLogger("WarMapGenerator")


def _calculate_ote_zone(df: pd.DataFrame) -> tuple:
    """
    Calcula la Zona de Oro (OTE) basada en el rango de las últimas 24 velas.

    OTE = Optimal Trade Entry (61.8% - 79.0% del rango)

    Returns:
        tuple: (fib_618, fib_705, fib_790, major_high, major_low)
    """
    if df is None or len(df) < 2:
        return (0, 0, 0, 0, 0)

    recent = df.tail(24)
    major_high = recent['high'].max()
    major_low = recent['low'].min()
    diff = major_high - major_low

    if diff == 0:
        return (0, 0, 0, 0, 0)

    fib_618 = major_low + (diff * 0.618)
    fib_705 = major_low + (diff * 0.705)
    fib_790 = major_low + (diff * 0.790)

    return (fib_618, fib_705, fib_790, major_high, major_low)


def _detect_swing_points(df: pd.DataFrame) -> tuple:
    """
    Detecta Swing Highs y Swing Lows en la estructura de mercado.

    Returns:
        tuple: (swing_highs, swing_lows) listas de (index, price)
    """
    if df is None or len(df) < 5:
        return ([], [])

    swing_highs = []
    swing_lows = []

    for i in range(3, len(df) - 3):
        if all(df['high'].iloc[i] > df['high'].iloc[i-j] for j in range(1, 4)) and \
           all(df['high'].iloc[i] > df['high'].iloc[i+j] for j in range(1, 4)):
            swing_highs.append((df.index[i], df['high'].iloc[i]))

        if all(df['low'].iloc[i] < df['low'].iloc[i-j] for j in range(1, 4)) and \
           all(df['low'].iloc[i] < df['low'].iloc[i+j] for j in range(1, 4)):
            swing_lows.append((df.index[i], df['low'].iloc[i]))

    return (swing_highs, swing_lows)


def _detect_sweeps(df: pd.DataFrame, swing_highs: list, swing_lows: list) -> list:
    """Detecta Sweeps de liquidez (LuxAlgo $)."""
    sweeps = []
    if len(df) < 5:
        return sweeps

    for idx, price in swing_highs:
        idx_loc = df.index.get_loc(idx) if idx in df.index else -1
        if idx_loc < 0 or idx_loc >= len(df) - 1:
            continue
        for j in range(1, min(4, len(df) - idx_loc)):
            candle = df.iloc[idx_loc + j]
            if candle['high'] > price and candle['close'] < price:
                sweeps.append({'index': candle.name, 'price': price, 'type': 'SELL'})
                break

    for idx, price in swing_lows:
        idx_loc = df.index.get_loc(idx) if idx in df.index else -1
        if idx_loc < 0 or idx_loc >= len(df) - 1:
            continue
        for j in range(1, min(4, len(df) - idx_loc)):
            candle = df.iloc[idx_loc + j]
            if candle['low'] < price and candle['close'] > price:
                sweeps.append({'index': candle.name, 'price': price, 'type': 'BUY'})
                break

    return sweeps


def generate_war_map(
    df: pd.DataFrame,
    proba: float = 0.0,
    direction: int = 0,
    sweep: int = 0,
    atr: float = 0.0,
    sw_high: float = 0.0,
    sw_low: float = 0.0,
    d1_high: float = 0.0,
    d1_low: float = 0.0,
    bid: float = 0.0,
    ask: float = 0.0,
    symbol: str = "EURUSD",
    verdict: str = "INIT",
    reason: str = "",
    output_path: str = "logs/war_map.html",
):
    """
    WAR ROOM MASTER V5.3: Blindaje total de capas y detección dinámica de tiempo.
    Integra OTE, LuxAlgo, HTF, Bid/Ask, Sesiones, OPEN DAY y Killzones.

    V5.3 — MASTER BLINDAJE:
      - Detección dinámica de días (OPEN DAY) — NUNCA FALLA
      - Killzones (08:00-12:00) para cada día visible
      - Smart Labels con anticolisión (1.5 pips de margen)
      - Zoom de 35 velas con 10h de espacio a la derecha
      - Título STRATUM MASTER V8.4
    """
    # --- Cambio 1: Validación de entrada y conversión robusta ---
    if df is None or df.empty:
        logger.warning(f"⚠️ No hay datos para {symbol}. Saltando generación.")
        return

    df_plot = df.copy()

    # Asegurar que la columna 'time' sea datetime y el índice
    if 'time' in df_plot.columns:
        df_plot['time'] = pd.to_datetime(df_plot['time'])
        df_plot.set_index('time', inplace=True)
    elif not isinstance(df_plot.index, pd.DatetimeIndex):
        try:
            # Intentar convertir el índice actual (si es string o timestamp unix)
            df_plot.index = pd.to_datetime(df_plot.index)
        except:
            print("⚠️ Índice no convertible a tiempo. Usando modo secuencial.")

    # Zoom de 35 velas para máxima claridad
    df_plot = df_plot.tail(35).copy()

    # ─── 2. CALCULAR CAPAS ───
    fib_618, fib_705, fib_790, major_high, major_low = _calculate_ote_zone(df)
    swing_highs, swing_lows = _detect_swing_points(df)
    sweeps = _detect_sweeps(df, swing_highs, swing_lows)

    use_d1_high = d1_high if d1_high > 0 else (df['high'].max() if len(df) > 0 else 0)
    use_d1_low = d1_low if d1_low > 0 else (df['low'].min() if len(df) > 0 else 0)

    # ─── 3. CONFIGURAR TÍTULO ───
    verdict_icon = {"APROBADO": "✅", "VETADO": "🛡️", "INIT": "⚪"}
    icon = verdict_icon.get(verdict, "⚪")
    direction_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "NEUTRO"
    proba_str = f"{proba*100:.1f}%" if proba > 0 else "—"

    title_text = (
        f"<b>STRATUM MASTER V8.4 — {symbol}</b><br>"
        f"<span style='font-size:14px'>"
        f"IA: {proba_str} | Dirección: {direction_str} | "
        f"{icon} CONSEJO: <b>{verdict}</b>"
        f"{' | Razón: ' + reason if reason else ''}"
        f"</span>"
    )

    # ─── 4. CREAR FIGURA ───
    fig = go.Figure()

    # ─── 5. GESTOR DE ETIQUETAS ANTICOLISIÓN (SMART LABELS) ───
    used_heights = []

    def add_level(y, color, text, style="dash", width=1, side="right"):
        """Añade línea horizontal + etiqueta con gestión de colisiones (1.5 pips)."""
        if not y or np.isnan(y) or y < 0.5:
            return

        # Evitar que los textos se pisen (Desplazamiento vertical)
        final_yshift = 0
        for h in used_heights:
            if abs(y - h) < (y * 0.00015):  # ~1.5 pips en EURUSD
                final_yshift += 20
        used_heights.append(y)

        x_pos = 1.01 if side == "right" else -0.01
        is_gold = "gold" in str(color).lower() or "255, 215, 0" in str(color)
        font_color = "black" if is_gold else "white"

        fig.add_hline(
            y=float(y),
            line_color=color,
            line_dash=style,
            line_width=width,
            opacity=0.8
        )
        fig.add_annotation(
            x=x_pos, y=y,
            xref="paper", yref="y",
            text=f"<b>{text}: {y:.5f}</b>",
            showarrow=False,
            xanchor="left" if side == "right" else "right",
            yshift=final_yshift,
            font=dict(
                color=font_color,
                size=11,
                weight="bold"
            ),
            bgcolor=color,
            opacity=1.0,
            borderpad=4
        )

    # ─── 6. CAPAS DE TIEMPO (DETECCIÓN DINÁMICA DE DÍAS) ───
    # Helper seguro para formatear fechas sin importar el tipo de índice
    def _safe_date_str(idx_val, fmt='%d %b'):
        """Convierte cualquier tipo de índice a string de fecha sin crash."""
        if isinstance(idx_val, (datetime, pd.Timestamp)):
            return idx_val.strftime(fmt)
        try:
            # Intentar convertir numérico (timestamp Unix) a datetime
            ts = pd.to_datetime(idx_val, unit='s')
            return ts.strftime(fmt)
        except (ValueError, TypeError, OSError):
            pass
        try:
            # Intentar convertir string a datetime
            ts = pd.to_datetime(str(idx_val))
            return ts.strftime(fmt)
        except (ValueError, TypeError):
            pass
        # Fallback: devolver el valor como string
        return str(idx_val)

    def _safe_date_iso(idx_val):
        """Convierte cualquier tipo de índice a string ISO YYYY-MM-DD sin crash."""
        if isinstance(idx_val, (datetime, pd.Timestamp)):
            return idx_val.strftime('%Y-%m-%d')
        try:
            ts = pd.to_datetime(idx_val, unit='s')
            return ts.strftime('%Y-%m-%d')
        except (ValueError, TypeError, OSError):
            pass
        try:
            ts = pd.to_datetime(str(idx_val))
            return ts.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass
        return str(idx_val)

    df_plot['day_label'] = df_plot.index.date if hasattr(df_plot.index, 'date') else df_plot.index.map(lambda x: _safe_date_iso(x)[:10])
    day_changes = df_plot[df_plot['day_label'] != df_plot['day_label'].shift(1)]

    for _, row in day_changes.iterrows():
        # Línea vertical de inicio de día
        fig.add_vline(x=row.name, line_dash="dash", line_color="cyan", opacity=0.4)
        fig.add_annotation(
            x=row.name, y=1.02, yref="paper",
            text=f"📊 OPEN {_safe_date_str(row.name)}",
            showarrow=False, font=dict(color="cyan", size=10, weight="bold"),
            bgcolor="rgba(0,0,0,0.6)"
        )

    # Dibujar Killzones para cada día visible
    for day in df_plot['day_label'].unique():
        day_str = _safe_date_iso(day) if not isinstance(day, str) else day
        fig.add_vrect(
            x0=f"{day_str} 08:00:00", x1=f"{day_str} 12:00:00",
            fillcolor="rgba(255, 255, 255, 0.05)", layer="below", line_width=0
        )

    # ─── 7. VELAS H1 ───
    fig.add_trace(go.Candlestick(
        x=df_plot.index,
        open=df_plot['open'],
        high=df_plot['high'],
        low=df_plot['low'],
        close=df_plot['close'],
        name=f"{symbol} H1",
        increasing_line_color='#00FF00',
        decreasing_line_color='#FF3131',
    ))

    # ─── 8. SÍMBOLOS $ LUXALGO ───
    for i in range(2, len(df_plot) - 2):
        if df_plot['high'].iloc[i] > max(
            df_plot['high'].iloc[i-1], df_plot['high'].iloc[i-2],
            df_plot['high'].iloc[i+1], df_plot['high'].iloc[i+2]
        ):
            fig.add_annotation(
                x=df_plot.index[i], y=df_plot['high'].iloc[i],
                text="$", showarrow=False, yshift=10,
                font=dict(color="#FF00FF", size=9)
            )
        if df_plot['low'].iloc[i] < min(
            df_plot['low'].iloc[i-1], df_plot['low'].iloc[i-2],
            df_plot['low'].iloc[i+1], df_plot['low'].iloc[i+2]
        ):
            fig.add_annotation(
                x=df_plot.index[i], y=df_plot['low'].iloc[i],
                text="$", showarrow=False, yshift=-10,
                font=dict(color="#00FFFF", size=9)
            )

    # ─── 9. NIVELES HTF E INTRADÍA ───
    add_level(use_d1_high, "#BF00FF", "HTF HIGH", side="left", width=2, style="solid")
    add_level(use_d1_low, "#BF00FF", "HTF LOW", side="left", width=2, style="solid")

    major_h = df['high'].tail(24).max() if len(df) >= 24 else df['high'].max()
    major_l = df['low'].tail(24).min() if len(df) >= 24 else df['low'].min()
    add_level(major_h, "rgba(255, 49, 49, 0.6)", "24H HOD")
    add_level(major_l, "rgba(57, 255, 20, 0.6)", "24H LOD")

    # ─── 10. ZONA DORADA OTE (FIBONACCI) ───
    if fib_618 > 0 and fib_790 > 0:
        diff = major_h - major_l
        # Rectángulo de Oro
        fig.add_hrect(
            y0=fib_790, y1=fib_618,
            fillcolor="rgba(255, 215, 0, 0.05)",
            line_width=0,
            layer="below"
        )
        # Los 3 niveles Fibonacci
        add_level(fib_618, "gold", "FIB 0.618", style="dot", width=1)
        add_level(fib_705, "gold", "OTE 0.705", style="solid", width=2)
        add_level(fib_790, "gold", "FIB 0.790", style="dot", width=1)

    # ─── 11. BID / ASK ───
    if bid > 0:
        add_level(bid, "rgba(255, 255, 255, 0.4)", "BID", style="solid", width=1)
    if ask > 0:
        add_level(ask, "#FF3131", "ASK", style="solid", width=1)

    # ─── 12. LAYOUT Y ESCALA ───
    last_close = float(df_plot['close'].iloc[-1])

    # Bloqueo de escala para evitar aplanamiento
    valid_y = [
        y for y in [
            df_plot['low'].min(), df_plot['high'].max(),
            use_d1_high, use_d1_low, major_h, major_l, bid, ask
        ]
        if y and y > 0 and abs(y - last_close) < (last_close * 0.1)
    ]

    if valid_y:
        y_min = min(valid_y) * 0.9992
        y_max = max(valid_y) * 1.0008
    else:
        y_min = df_plot['low'].min() * 0.9992
        y_max = df_plot['high'].max() * 1.0008

    # --- Cambio 2: Rango dinámico del eje X ---
    is_datetime = isinstance(df_plot.index, pd.DatetimeIndex)

    if is_datetime:
        x_start = df_plot.index[0]
        x_end = df_plot.index[-1] + pd.Timedelta(hours=10)  # Margen para etiquetas
    else:
        x_start = df_plot.index[0]
        x_end = df_plot.index[-1] + 10  # Margen numérico simple

    fig.update_layout(
        title={
            'text': title_text,
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 22, 'color': 'gold', 'family': 'Courier New, monospace'},
        },
        template='plotly_dark',
        paper_bgcolor='black',
        plot_bgcolor='black',
        xaxis_rangeslider_visible=False,
        height=850,
        margin=dict(r=160, l=160, t=80, b=50),
        xaxis=dict(
            range=[x_start, x_end],
            gridcolor="#1a1a1a",
        ),
        yaxis=dict(
            side="right",
            range=[y_min, y_max],
            gridcolor="#1a1a1a",
        ),
        hovermode='x unified',
    )

    # ─── 13. GUARDAR CON AUTO-REFRESH ───
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    html_str = fig.to_html(include_plotlyjs='cdn', full_html=True)
    html_str = html_str.replace(
        '<head>',
        '<head><meta http-equiv="refresh" content="30">'
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_str)

    logger.info(f"🗺️ V5.3 Mapa de Guerra generado: {output_path}")
    return output_path


# ──────────────────────────────────────────────
# DEMO: GENERAR MAPA DE GUERRA V5.3
# ──────────────────────────────────────────────

def run_demo():
    """
    Genera un Mapa de Guerra V5.3 de demostración con datos sintéticos.
    Incluye múltiples días para probar la detección dinámica de OPEN DAY.
    """
    print("\n" + "=" * 70)
    print("🗺️ V5.3 DEMO: WAR MAP GENERATOR — 'MASTER BLINDAJE'")
    print("   Generando mapa de guerra con detección dinámica de días...")
    print("=" * 70)

    np.random.seed(42)
    n_candles = 100
    base_price = 1.0800

    # Generar fechas que abarquen varios días para probar OPEN DAY
    dates = pd.date_range(
        start=datetime.now(timezone.utc) - pd.Timedelta(hours=n_candles),
        end=datetime.now(timezone.utc),
        periods=n_candles,
    )

    prices = [base_price]
    for i in range(1, n_candles):
        change = np.random.normal(0, 0.0005)
        prices.append(prices[-1] + change)

    df_demo = pd.DataFrame({
        'time': dates,
        'open': prices,
        'high': [p + abs(np.random.normal(0, 0.0003)) for p in prices],
        'low': [p - abs(np.random.normal(0, 0.0003)) for p in prices],
        'close': [p + np.random.normal(0, 0.0002) for p in prices],
        'tick_volume': np.random.randint(100, 1000, n_candles),
    })

    for i in range(len(df_demo)):
        df_demo.loc[i, 'high'] = max(df_demo.loc[i, 'high'], df_demo.loc[i, 'open'], df_demo.loc[i, 'close'])
        df_demo.loc[i, 'low'] = min(df_demo.loc[i, 'low'], df_demo.loc[i, 'open'], df_demo.loc[i, 'close'])

    generate_war_map(
        df=df_demo,
        proba=0.82,
        direction=1,
        sweep=1,
        atr=0.0012,
        sw_high=1.0825,
        sw_low=1.0780,
        d1_high=1.0850,
        d1_low=1.0750,
        bid=1.0805,
        ask=1.0808,
        symbol="EURUSD",
        verdict="APROBADO",
        reason="Consejo unánime: Tendencia + Volumen",
        output_path="logs/war_map_demo.html",
    )

    print(f"\n✅ Mapa de Guerra V5.3 generado: logs/war_map_demo.html")
    print(f"   📊 Velas: {n_candles} (Zoom 35)")
    print(f"   🧠 IA: 82.0% LONG")
    print(f"   ✅ Consejo: APROBADO")
    print(f"   📅 Detección dinámica de días: ACTIVADA")
    print(f"   🎯 Killzones (08:00-12:00): ACTIVADAS")
    print(f"   🏷️ Smart Labels (1.5 pips): ACTIVADAS")

    return df_demo


if __name__ == "__main__":
    run_demo()
