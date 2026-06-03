"""
EXP-013: Whale Tracker — Detección de Absorción Institucional
==============================================================
Objetivo: Detectar "Huellas de Ballena" donde el volumen masivo
no logra mover el precio (Absorción). La divergencia entre
esfuerzo (volumen) y resultado (precio) es la firma del dinero inteligente.

Hipótesis: Las instituciones no pueden entrar al mercado sin
"hacer ruido" en el volumen delta. Este tracker busca el momento
donde una institución está absorbiendo todas las órdenes de los minoristas.

Framework: Sentinel V2 — Rigor de Código Industrial

CORRECCIÓN V2:
  - Deduplicación corregida: usa diff() != 0 para detectar bloques
  - Lógica de ballena invertida: RS>0 + absorción = ACUMULACIÓN (precio sube)
  - RS<0 + absorción = DISTRIBUCIÓN (precio baja)
  - La ballena NO siempre empuja en contra. A veces acumula para subir.
"""

import pandas as pd
import numpy as np
import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# CONFIGURACIÓN INDUSTRIAL
# ──────────────────────────────────────────────────────────────
WHALE_CONFIG = {
    "vol_std_multiplier": 1.5,          # Multiplicador para volumen masivo
    "vol_window": 24,                    # Ventana rolling para std de volumen
    "rejection_speed_threshold": 1.5,   # Mínimo |rejection_speed| para señal
    "absorption_z_threshold": 1.0,      # Mínimo z-score de absorption_ratio
    "future_lookahead_hours": [3, 6, 12], # Velas hacia adelante para validar
    "min_pip_movement": 0.5,            # Mínimo movimiento en pips para contar como hit/miss
    "min_signals": 10,                  # Mínimo de señales para considerar válido
    "data_dir": "data",
    "output_dir": "data"
}

# Columnas requeridas en el dataset masivo
REQUIRED_COLUMNS = [
    'open', 'high', 'low', 'close', 'tick_count',
    'rejection_speed', 'volume_delta'
]

# ──────────────────────────────────────────────────────────────
# NÚCLEO DE DETECCIÓN
# ──────────────────────────────────────────────────────────────

def validate_dataframe(df: pd.DataFrame, symbol: str) -> bool:
    """
    Valida que el DataFrame tenga todas las columnas necesarias
    y que no esté vacío. Retorna True si es válido.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print(f"❌ [{symbol}] Columnas faltantes: {missing}")
        print(f"   Columnas disponibles: {list(df.columns)}")
        return False
    
    if df.empty:
        print(f"❌ [{symbol}] DataFrame vacío")
        return False
    
    print(f"✅ [{symbol}] DataFrame válido: {len(df)} filas")
    return True


def compute_whale_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula las features de detección de ballenas:
    
    A. Volumen Masivo (> 1.5 std sobre la media móvil de 24 velas)
    B. Z-score de Absorción (qué tan inusual es el ratio volumen/rango)
    C. Señal compuesta Whale
    """
    df = df.copy()
    
    # ── A. Volumen Masivo ──
    df['vol_mean'] = df['tick_count'].rolling(WHALE_CONFIG['vol_window']).mean()
    df['vol_std'] = df['tick_count'].rolling(WHALE_CONFIG['vol_window']).std()
    df['is_massive_vol'] = (
        df['tick_count'] > 
        (df['vol_mean'] + WHALE_CONFIG['vol_std_multiplier'] * df['vol_std'])
    )
    
    # ── B. Z-score de Absorción ──
    # En lugar de usar el ratio crudo (que es enorme), usamos z-score
    # para medir qué tan inusual es la relación volumen/rango
    price_range = (df['high'] - df['low']).replace(0, 1e-10)
    df['absorption_ratio'] = df['tick_count'] / price_range
    
    # Z-score del absorption ratio
    abs_mean = df['absorption_ratio'].rolling(WHALE_CONFIG['vol_window']).mean()
    abs_std = df['absorption_ratio'].rolling(WHALE_CONFIG['vol_window']).std().replace(0, 1e-10)
    df['absorption_z'] = (df['absorption_ratio'] - abs_mean) / abs_std
    
    # ── C. Señal Compuesta Whale ──
    df['whale_signal'] = np.where(
        (df['is_massive_vol']) & 
        (df['rejection_speed'].abs() > WHALE_CONFIG['rejection_speed_threshold']) & 
        (df['absorption_z'] > WHALE_CONFIG['absorption_z_threshold']),
        1, 0
    )
    
    return df


def deduplicate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Elimina señales duplicadas (mismo timestamp).
    El rolling() puede propagar la señal a filas adyacentes.
    Solo mantenemos la primera ocurrencia de cada BLOQUE de señal.
    
    CORRECCIÓN V2: Usamos diff() != 0 para detectar transiciones
    de 0→1 (inicio de bloque) y 1→0 (fin de bloque).
    
    NOTA: Esta función debe llamarse DESPUÉS de compute_whale_features
    pero ANTES de validate_whale_edge para que las métricas se calculen
    solo sobre las señales únicas.
    
    FIX V4: El índice tiene timestamps DUPLICADOS (múltiples filas
    con el mismo timestamp). Usar .loc con un timestamp asigna a TODAS
    las filas con ese timestamp. En su lugar, usamos .iloc con la
    posición numérica exacta de cada primera ocurrencia.
    """
    # Identificar bloques de señales consecutivas
    df['signal_block'] = (df['whale_signal'].diff() != 0).cumsum()
    
    # Los bloques de señal son aquellos donde whale_signal == 1
    signal_blocks = df[df['whale_signal'] == 1].groupby('signal_block')
    
    # Obtener el TIMESTAMP de la primera fila de cada bloque
    first_timestamps = signal_blocks.apply(lambda x: x.index[0])
    
    # Convertir cada timestamp a posición ABSOLUTA en el DataFrame original
    # Usamos df.index.get_loc() que maneja correctamente timestamps duplicados
    # devolviendo un slice. Tomamos el .start del slice.
    first_positions = []
    for ts in first_timestamps.values:
        loc = df.index.get_loc(ts)
        if isinstance(loc, slice):
            first_positions.append(loc.start)
        elif isinstance(loc, int):
            first_positions.append(loc)
    
    # Resetear TODAS las señales a 0
    df['whale_signal'] = 0
    
    # Solo marcar la primera ocurrencia de cada bloque usando iloc
    for pos in first_positions:
        df.iloc[pos, df.columns.get_loc('whale_signal')] = 1
    
    # Limpiar columna auxiliar
    df = df.drop(columns=['signal_block'])
    
    return df


def validate_whale_edge(df: pd.DataFrame) -> pd.DataFrame:
    """
    Valida el Edge de la señal Whale usando MÚLTIPLES lookaheads.
    
    CORRECCIÓN V2 — Lógica institucional REAL:
    
    La ballena tiene DOS modos de operación:
    
    MODO 1: ACUMULACIÓN (RS > 0)
      - La ballena EMPUJA el precio hacia arriba (rejection_speed alta)
      - Crea la ilusión de un breakout alcista
      - Los minoristas COMPRAN pensando que subirá más
      - La ballena ABSORBE esas órdenes de compra
      - RESULTADO: El precio SUBE (la ballena está acumulando)
      - Estrategia: COMPRAR con la ballena
    
    MODO 2: DISTRIBUCIÓN (RS < 0)
      - La ballena EMPUJA el precio hacia abajo (rejection_speed alta negativa)
      - Crea la ilusión de un breakdown bajista
      - Los minoristas VENDEN pensando que caerá más
      - La ballena ABSORBE esas órdenes de venta
      - RESULTADO: El precio BAJA (la ballena está distribuyendo)
      - Estrategia: VENDER con la ballena
    
    En ambos casos, la dirección del movimiento FUTURO es la MISMA
    que la dirección del rejection_speed.
    """
    df = df.copy()
    
    # Calcular retornos en PIPS para cada lookahead
    # EURUSD: 1 pip = 0.0001, GOLD: 1 pip = 0.01
    for hours in WHALE_CONFIG['future_lookahead_hours']:
        lookahead = hours  # En velas H1, hours = número de velas
        col_ret = f'ret_{hours}h_pips'
        col_hit = f'hit_{hours}h'
        col_miss = f'miss_{hours}h'
        
        # Retorno futuro en pips (multiplicamos por 10000 para EURUSD)
        future_close = df['close'].shift(-lookahead)
        df[col_ret] = (future_close - df['close']) * 10000
        
        # Hit: La dirección del rejection_speed CONCUERDA con el movimiento
        # RS > 0 → esperamos que suba (ret > 0)
        # RS < 0 → esperamos que baje (ret < 0)
        df[col_hit] = np.where(
            (
                (df['whale_signal'] == 1) & 
                (df['rejection_speed'] > 0) & 
                (df[col_ret] > WHALE_CONFIG['min_pip_movement'])
            ) |
            (
                (df['whale_signal'] == 1) & 
                (df['rejection_speed'] < 0) & 
                (df[col_ret] < -WHALE_CONFIG['min_pip_movement'])
            ),
            1, 0
        )
        
        # Miss: señal activa pero dirección incorrecta O movimiento insignificante
        df[col_miss] = np.where(
            (df['whale_signal'] == 1) & (df[col_hit] == 0),
            1, 0
        )
    
    # Métrica compuesta: hit si AL MENOS UN lookahead confirma
    hit_cols = [f'hit_{h}h' for h in WHALE_CONFIG['future_lookahead_hours']]
    df['hit'] = df[hit_cols].any(axis=1).astype(int)
    df['miss'] = np.where((df['whale_signal'] == 1) & (df['hit'] == 0), 1, 0)
    
    return df


def compute_whale_metrics(df: pd.DataFrame, symbol: str) -> dict:
    """
    Calcula métricas de rendimiento de la señal Whale.
    """
    signals = df[df['whale_signal'] == 1]
    total_signals = len(signals)
    
    if total_signals == 0:
        return {
            "symbol": symbol,
            "total_signals": 0,
            "win_rate": 0.0,
            "total_hits": 0,
            "total_misses": 0,
            "avg_absorption_z": 0.0,
            "avg_rejection_speed": 0.0,
            "signal_frequency_pct": 0.0,
            "valid": False,
            "lookahead_results": {}
        }
    
    hits = signals['hit'].sum()
    misses = signals['miss'].sum()
    win_rate = hits / total_signals if total_signals > 0 else 0.0
    
    # Métricas por lookahead
    lookahead_results = {}
    for hours in WHALE_CONFIG['future_lookahead_hours']:
        col_ret = f'ret_{hours}h_pips'
        col_hit = f'hit_{hours}h'
        
        h_hits = signals[col_hit].sum()
        h_win_rate = h_hits / total_signals if total_signals > 0 else 0.0
        h_avg_ret = signals[col_ret].mean()
        
        lookahead_results[f'{hours}h'] = {
            "win_rate": round(h_win_rate, 4),
            "hits": int(h_hits),
            "avg_return_pips": round(h_avg_ret, 4)
        }
    
    # Retornos en pips
    hit_returns = signals[signals['hit'] == 1]['ret_3h_pips']
    miss_returns = signals[signals['miss'] == 1]['ret_3h_pips']
    
    metrics = {
        "symbol": symbol,
        "total_signals": total_signals,
        "win_rate": round(win_rate, 4),
        "total_hits": int(hits),
        "total_misses": int(misses),
        "avg_absorption_z": round(signals['absorption_z'].mean(), 2),
        "avg_rejection_speed": round(signals['rejection_speed'].mean(), 4),
        "avg_return_3h_pips": round(signals['ret_3h_pips'].mean(), 4),
        "avg_hit_return_pips": round(hit_returns.mean(), 4) if len(hit_returns) > 0 else 0.0,
        "avg_miss_return_pips": round(miss_returns.mean(), 4) if len(miss_returns) > 0 else 0.0,
        "signal_frequency_pct": round(total_signals / len(df) * 100, 2),
        "valid": total_signals >= WHALE_CONFIG['min_signals'],
        "lookahead_results": lookahead_results
    }
    
    return metrics


def print_whale_report(metrics: dict, df: pd.DataFrame):
    """
    Imprime un reporte formateado de los resultados Whale.
    """
    symbol = metrics['symbol']
    print(f"\n{'='*60}")
    print(f"🐋 EXP-013: WHALE TRACKER — {symbol}")
    print(f"{'='*60}")
    
    if not metrics['valid'] or metrics['total_signals'] == 0:
        print(f"⚠️  No se detectaron suficientes señales de ballena.")
        print(f"   Señales encontradas: {metrics['total_signals']}")
        print(f"   Mínimo requerido: {WHALE_CONFIG['min_signals']}")
        print(f"{'='*60}\n")
        return
    
    print(f"\n📊 ESTADÍSTICAS GLOBALES:")
    print(f"   • Total de velas analizadas: {len(df):,}")
    print(f"   • Señales Whale (únicas): {metrics['total_signals']}")
    print(f"   • Frecuencia de señal: {metrics['signal_frequency_pct']:.2f}%")
    
    print(f"\n🏆 RENDIMIENTO DE LA SEÑAL (compuesto):")
    print(f"   • Win Rate: {metrics['win_rate']:.2%}")
    print(f"   • Hits: {metrics['total_hits']} | Misses: {metrics['total_misses']}")
    print(f"   • Retorno promedio 3h: {metrics['avg_return_3h_pips']:+.2f} pips")
    print(f"   • Retorno HITS:  {metrics['avg_hit_return_pips']:+.2f} pips")
    print(f"   • Retorno MISSES: {metrics['avg_miss_return_pips']:+.2f} pips")
    
    print(f"\n📐 RENDIMIENTO POR LOOKAHEAD:")
    print(f"   {'Horizonte':<12} {'Win Rate':<12} {'Hits':<8} {'Retorno (pips)':<16}")
    print(f"   {'-'*48}")
    for horizon, results in metrics['lookahead_results'].items():
        print(f"   {horizon:<12} {results['win_rate']:.2%}       {results['hits']:<8} {results['avg_return_pips']:+.2f}")
    
    print(f"\n🔬 PERFIL DE LA BALLENA:")
    print(f"   • Z-score de Absorción promedio: {metrics['avg_absorption_z']:+.2f}")
    print(f"   • Rejection Speed promedio: {metrics['avg_rejection_speed']:+.4f}")
    
    # Interpretación
    print(f"\n🧠 INTERPRETACIÓN:")
    wr = metrics['win_rate']
    if wr >= 0.65:
        print(f"   ✅ SEÑAL ROBUSTA — La huella de ballena es confiable.")
        print(f"   🎯 Estrategia: Operar en la DIRECCIÓN del rejection_speed")
        print(f"      cuando se detecte absorción (z-score > 1.0).")
        print(f"      RS>0 → COMPRAR | RS<0 → VENDER")
    elif wr >= 0.55:
        print(f"   ⚠️  SEÑAL MODERADA — Hay edge pero necesita filtros adicionales.")
        print(f"   🔧 Sugerencia: Combinar con regime_sniper o shadow_clustering.")
    elif wr >= 0.45:
        print(f"   ❓ SEÑAL NEUTRAL — La señal no es mejor que aleatorio.")
        print(f"   🔧 Sugerencia: Ajustar thresholds o probar en otro símbolo.")
    else:
        print(f"   ❌ SIN EDGE — La señal es contraproducente.")
        print(f"   🔧 Sugerencia: Revisar la lógica de detección.")
    
    print(f"{'='*60}\n")


def export_whale_data(df: pd.DataFrame, symbol: str):
    """
    Exporta el dataset con señales Whale para consumo de la V8.2.
    
    CORRECCIÓN V2.1: Exporta SOLO las señales únicas (primer timestamp
    de cada bloque de señal), no todas las filas propagadas por el rolling.
    
    FIX V4: Usar iloc con posiciones numéricas en lugar de .loc con timestamps
    (el índice tiene timestamps duplicados).
    """
    output_path = os.path.join(
        WHALE_CONFIG['output_dir'],
        f"{symbol.lower()}_whale_data.csv"
    )
    df.to_csv(output_path)
    print(f"💾 Datos Whale exportados: {output_path}")
    
    # Exportar solo las señales únicas (primer timestamp de cada bloque)
    df_temp = df.copy()
    df_temp['signal_block'] = (df_temp['whale_signal'].diff() != 0).cumsum()
    
    signal_blocks = df_temp[df_temp['whale_signal'] == 1].groupby('signal_block')
    first_timestamps = signal_blocks.apply(lambda x: x.index[0])
    
    # Extraer las filas únicas usando posiciones ABSOLUTAS
    unique_rows = []
    for ts in first_timestamps.values:
        loc = df.index.get_loc(ts)
        if isinstance(loc, slice):
            unique_rows.append(df.iloc[loc.start])
        elif isinstance(loc, int):
            unique_rows.append(df.iloc[loc])
    
    if unique_rows:
        unique_signals = pd.DataFrame(unique_rows)
        signals_path = os.path.join(
            WHALE_CONFIG['output_dir'],
            f"{symbol.lower()}_whale_signals.csv"
        )
        unique_signals.to_csv(signals_path)
        print(f"💾 Señales Whale (únicas): {signals_path} ({len(unique_signals)} señales)")


def export_metrics_json(metrics: dict, symbol: str):
    """
    Exporta las métricas a JSON para consumo por el war room.
    """
    output_path = os.path.join(
        WHALE_CONFIG['output_dir'],
        f"{symbol.lower()}_whale_metrics.json"
    )
    with open(output_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"💾 Métricas Whale exportadas: {output_path}")


# ──────────────────────────────────────────────────────────────
# ORQUESTADOR PRINCIPAL
# ──────────────────────────────────────────────────────────────

def run_whale_tracker(symbol: str) -> dict:
    """
    Ejecuta el pipeline completo de detección de ballenas.
    
    Args:
        symbol: Símbolo a analizar (ej: "EURUSD", "GOLD")
    
    Returns:
        Dict con métricas de rendimiento
    """
    print(f"\n{'#'*60}")
    print(f"🐋 Ejecutando EXP-013: Whale Tracker para {symbol}...")
    print(f"{'#'*60}")
    
    # 1. Cargar datos masivos
    file_path = os.path.join(
        WHALE_CONFIG['data_dir'],
        f"{symbol.lower()}_massive_lab_data.csv"
    )
    
    if not os.path.exists(file_path):
        print(f"❌ No se encuentra {file_path}.")
        print(f"   Ejecuta mass_tick_downloader.py primero para descargar datos masivos.")
        return {"symbol": symbol, "error": "Data file not found", "valid": False}
    
    print(f"📂 Cargando: {file_path}")
    df = pd.read_csv(file_path, index_col='time', parse_dates=True)
    print(f"   • Filas cargadas: {len(df):,}")
    print(f"   • Rango: {df.index[0]} → {df.index[-1]}")
    
    # 2. Validar DataFrame
    if not validate_dataframe(df, symbol):
        return {"symbol": symbol, "error": "Invalid DataFrame", "valid": False}
    
    # 3. Calcular features Whale
    print(f"\n🔬 Calculando features de detección de ballenas...")
    df = compute_whale_features(df)
    
    # 4. Deduplicar señales
    print(f"🧹 Deduplicando señales...")
    df = deduplicate_signals(df)
    
    # 5. Validar el Edge
    print(f"📐 Validando edge de la señal (lookaheads: {WHALE_CONFIG['future_lookahead_hours']}h)...")
    df = validate_whale_edge(df)
    
    # 6. Calcular métricas
    metrics = compute_whale_metrics(df, symbol)
    
    # 7. Reporte
    print_whale_report(metrics, df)
    
    # 8. Exportar resultados
    export_whale_data(df, symbol)
    export_metrics_json(metrics, symbol)
    
    return metrics


def run_batch_analysis(symbols: list = None):
    """
    Ejecuta el Whale Tracker para múltiples símbolos y
    genera un reporte comparativo.
    """
    if symbols is None:
        symbols = ["EURUSD", "GOLD"]
    
    print(f"\n{'='*60}")
    print(f"🐋🐋 WHALE TRACKER — ANÁLISIS MULTI-SÍMBOLO 🐋🐋")
    print(f"{'='*60}")
    
    all_metrics = []
    for symbol in symbols:
        metrics = run_whale_tracker(symbol)
        all_metrics.append(metrics)
    
    # Reporte comparativo
    print(f"\n{'='*60}")
    print(f"📊 REPORTE COMPARATIVO MULTI-SÍMBOLO")
    print(f"{'='*60}")
    
    print(f"\n{'Símbolo':<10} {'Señales':<10} {'Win Rate':<12} {'Frecuencia':<12} {'Abs Z':<10}")
    print(f"{'-'*54}")
    
    for m in all_metrics:
        if m.get('valid'):
            print(f"{m['symbol']:<10} {m['total_signals']:<10} {m['win_rate']:.2%}       {m['signal_frequency_pct']:.2f}%       {m['avg_absorption_z']:<+10.2f}")
        else:
            print(f"{m['symbol']:<10} {'N/A':<10} {'N/A':<12} {'N/A':<12} {'N/A':<10}")
    
    print(f"\n{'='*60}\n")
    
    return all_metrics


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="EXP-013: Whale Tracker — Detección de Absorción Institucional"
    )
    parser.add_argument(
        "--symbols", "-s",
        nargs="+",
        default=["EURUSD", "GOLD"],
        help="Símbolos a analizar (default: EURUSD GOLD)"
    )
    parser.add_argument(
        "--batch", "-b",
        action="store_true",
        help="Ejecutar análisis multi-símbolo con reporte comparativo"
    )
    
    args = parser.parse_args()
    
    if args.batch:
        run_batch_analysis(args.symbols)
    else:
        for symbol in args.symbols:
            run_whale_tracker(symbol)
