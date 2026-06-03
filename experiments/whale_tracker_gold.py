"""
EXP-013-GOLD: Whale Tracker (Calibración Oro) — Firma de Clímax
================================================================
Objetivo: Recalibrar el Whale Tracker para la volatilidad del Oro (GOLD).
El GOLD es un mercado de "clímax" — se mueve por impulsos violentos
donde las instituciones entran "limpiando" rangos enteros en minutos.

A diferencia del EURUSD (danza de absorción lenta), el Oro tiene:
  - Ruido de mechas constante (rejection_speed siempre en 0)
  - Absorción menos "estática" — las ballenas barren rangos rápido
  - Volumen masivo con poca correlación direccional

Ajustes vs EURUSD:
  - Volumen Masivo: 1.5σ → 1.2σ (capturar entrada institucional antes)
  - Velocidad de Rechazo: 2.0 → 1.5σ (el Oro tiene ruido constante)
  - Ratio de Absorción: Z-score 1.0 → 0.8 (absorción menos estática)

Estrategia "The Vacuum" (El Vacío):
  1. La ballena entra y barre todos los niveles con volumen brutal
  2. El precio se detiene (Absorción)
  3. Se crea un "vacío" de liquidez
  4. El precio se desploma o explota en dirección contraria

NOTA: GOLD no tiene rejection_speed del broker (todo ceros).
Usamos avg_speed + micro_trend como proxies de velocidad direccional.
"""

import pandas as pd
import numpy as np
import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# CONFIGURACIÓN CALIBRADA PARA GOLD
# ──────────────────────────────────────────────────────────────
GOLD_WHALE_CONFIG = {
    "vol_std_multiplier": 1.2,          # ↓ Bajado de 1.5 (capturar antes)
    "vol_window": 24,                    # Ventana rolling para std de volumen
    "speed_threshold": 1.5,             # ↓ Bajado de 2.0 (ruido de mechas)
    "absorption_z_threshold": 0.8,      # ↓ Bajado de 1.0 (absorción menos estática)
    "future_lookahead_hours": [3, 6, 12], # Velas hacia adelante para validar
    "min_pip_movement": 0.5,            # Mínimo movimiento en pips
    "min_signals": 10,                  # Mínimo de señales para considerar válido
    "data_dir": "data",
    "output_dir": "data"
}

# Columnas requeridas en el dataset masivo de GOLD
GOLD_REQUIRED_COLUMNS = [
    'open', 'high', 'low', 'close', 'tick_count',
    'avg_speed', 'micro_trend'
]


# ──────────────────────────────────────────────────────────────
# NÚCLEO DE DETECCIÓN — FIRMA DE CLÍMAX
# ──────────────────────────────────────────────────────────────

def validate_dataframe(df: pd.DataFrame) -> bool:
    """
    Valida que el DataFrame tenga todas las columnas necesarias
    y que no esté vacío. Retorna True si es válido.
    """
    missing = [c for c in GOLD_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print(f"❌ [GOLD] Columnas faltantes: {missing}")
        print(f"   Columnas disponibles: {list(df.columns)}")
        return False
    
    if df.empty:
        print(f"❌ [GOLD] DataFrame vacío")
        return False
    
    print(f"✅ [GOLD] DataFrame válido: {len(df)} filas")
    return True


def compute_gold_whale_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula las features de detección de ballenas CALIBRADAS para GOLD.
    
    DIFERENCIA CRÍTICA CON EURUSD:
    GOLD no tiene rejection_speed del broker (todo ceros).
    En su lugar, usamos:
      A. avg_speed → proxy de velocidad de tick
      B. micro_trend → proxy de direccionalidad
      C. price_delta (close - open) → dirección real del precio
    
    La "Firma de Clímax" del Oro:
      - Volumen Masivo temprano (1.2σ)
      - Velocidad de tick inusualmente alta (avg_speed z-score)
      - Absorción: mucho tick_count para poco price_range
    """
    df = df.copy()
    
    # ── A. Volumen Masivo (1.2 sigma) ──
    df['vol_mean'] = df['tick_count'].rolling(GOLD_WHALE_CONFIG['vol_window']).mean()
    df['vol_std'] = df['tick_count'].rolling(GOLD_WHALE_CONFIG['vol_window']).std()
    df['is_massive_vol'] = (
        df['tick_count'] > 
        (df['vol_mean'] + GOLD_WHALE_CONFIG['vol_std_multiplier'] * df['vol_std'])
    )
    
    # ── B. Velocidad de Tick (proxy de rejection_speed) ──
    # En GOLD, avg_speed alto = actividad institucional intensa
    df['speed_mean'] = df['avg_speed'].rolling(GOLD_WHALE_CONFIG['vol_window']).mean()
    df['speed_std'] = df['avg_speed'].rolling(GOLD_WHALE_CONFIG['vol_window']).std().replace(0, 1e-10)
    df['speed_z'] = (df['avg_speed'] - df['speed_mean']) / df['speed_std']
    
    # Direccionalidad compuesta: micro_trend + price_delta
    # micro_trend: positivo = presión compradora, negativo = vendedora
    # price_delta: positivo = vela alcista, negativo = bajista
    df['price_delta'] = df['close'] - df['open']
    
    # Firmamos la velocidad con la dirección del micro_trend
    # Si micro_trend es positivo y price_delta positivo → velocidad ALCISTA
    # Si micro_trend es negativo y price_delta negativo → velocidad BAJISTA
    df['directional_speed'] = np.where(
        (df['micro_trend'] > 0) & (df['price_delta'] > 0),
        df['speed_z'],  # Velocidad alcista positiva
        np.where(
            (df['micro_trend'] < 0) & (df['price_delta'] < 0),
            -df['speed_z'],  # Velocidad bajista negativa
            df['speed_z'] * 0.5  # Dirección mixta → señal más débil
        )
    )
    
    # ── C. Ratio de Absorción (Esfuerzo vs Resultado) ──
    # En GOLD, velas sin rango pero con mucho tick = ballenas puras
    price_range = (df['high'] - df['low']).replace(0, 1e-10)
    df['absorption_ratio'] = df['tick_count'] / price_range
    
    abs_mean = df['absorption_ratio'].rolling(GOLD_WHALE_CONFIG['vol_window']).mean()
    abs_std = df['absorption_ratio'].rolling(GOLD_WHALE_CONFIG['vol_window']).std().replace(0, 1e-10)
    df['absorption_z'] = (df['absorption_ratio'] - abs_mean) / abs_std
    
    # ── D. Gatillo Titan (Calibrado para GOLD) ──
    # Señal compuesta: Volumen masivo + Velocidad alta + Absorción inusual
    df['whale_signal'] = np.where(
        (df['is_massive_vol']) & 
        (df['directional_speed'].abs() > GOLD_WHALE_CONFIG['speed_threshold']) & 
        (df['absorption_z'] > GOLD_WHALE_CONFIG['absorption_z_threshold']),
        1, 0
    )
    
    return df


def deduplicate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Elimina señales duplicadas (mismo timestamp).
    El rolling() puede propagar la señal a filas adyacentes.
    Solo mantenemos la primera ocurrencia de cada BLOQUE de señal.
    """
    # Identificar bloques de señales consecutivas
    df['signal_block'] = (df['whale_signal'].diff() != 0).cumsum()
    
    # Los bloques de señal son aquellos donde whale_signal == 1
    signal_blocks = df[df['whale_signal'] == 1].groupby('signal_block')
    
    # Obtener el TIMESTAMP de la primera fila de cada bloque
    first_timestamps = signal_blocks.apply(lambda x: x.index[0])
    
    # Convertir cada timestamp a posición ABSOLUTA en el DataFrame original
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
    Valida el Edge de la señal Whale para GOLD.
    
    LÓGICA DE REVERSIÓN (TITAN LOGIC):
    La ballena en GOLD opera con "The Vacuum":
      - Entra con volumen masivo en una dirección
      - Absorbe toda la liquidez disponible
      - El precio se detiene (absorción)
      - Se crea un vacío → el precio revierte
    
    MODO 1: TECHO (directional_speed > 0)
      - La ballena empuja el precio hacia arriba
      - Absorbe órdenes de compra de minoristas
      - El precio se detiene y REVIERTE a la baja
      - Estrategia: VENDER en la señal
    
    MODO 2: SUELO (directional_speed < 0)
      - La ballena empuja el precio hacia abajo
      - Absorbe órdenes de venta de minoristas
      - El precio se detiene y REVIERTE al alza
      - Estrategia: COMPRAR en la señal
    """
    df = df.copy()
    
    # Calcular retornos en PIPS para cada lookahead
    # GOLD: 1 pip = 0.01 (en precio de ~4600, 1 pip ≈ 0.01)
    for hours in GOLD_WHALE_CONFIG['future_lookahead_hours']:
        lookahead = hours  # En velas H1, hours = número de velas
        col_ret = f'ret_{hours}h_pips'
        col_hit = f'hit_{hours}h'
        col_miss = f'miss_{hours}h'
        
        # Retorno futuro en pips (GOLD: multiplicamos por 100 para convertir a pips)
        future_close = df['close'].shift(-lookahead)
        df[col_ret] = (future_close - df['close']) * 100  # 1 pip GOLD ≈ 0.01
        
        # Hit: La dirección del directional_speed CONCUERDA con la REVERSIÓN
        # directional_speed > 0 → esperamos que BAJE (reversión de techo)
        # directional_speed < 0 → esperamos que SUBE (reversión de suelo)
        df[col_hit] = np.where(
            (
                (df['whale_signal'] == 1) & 
                (df['directional_speed'] > 0) & 
                (df[col_ret] < -GOLD_WHALE_CONFIG['min_pip_movement'])
            ) |
            (
                (df['whale_signal'] == 1) & 
                (df['directional_speed'] < 0) & 
                (df[col_ret] > GOLD_WHALE_CONFIG['min_pip_movement'])
            ),
            1, 0
        )
        
        # Miss: señal activa pero dirección incorrecta O movimiento insignificante
        df[col_miss] = np.where(
            (df['whale_signal'] == 1) & (df[col_hit] == 0),
            1, 0
        )
    
    # Métrica compuesta: hit si AL MENOS UN lookahead confirma
    hit_cols = [f'hit_{h}h' for h in GOLD_WHALE_CONFIG['future_lookahead_hours']]
    df['hit'] = df[hit_cols].any(axis=1).astype(int)
    df['miss'] = np.where((df['whale_signal'] == 1) & (df['hit'] == 0), 1, 0)
    
    return df


def compute_whale_metrics(df: pd.DataFrame) -> dict:
    """
    Calcula métricas de rendimiento de la señal Whale para GOLD.
    """
    signals = df[df['whale_signal'] == 1]
    total_signals = len(signals)
    
    if total_signals == 0:
        return {
            "symbol": "GOLD",
            "total_signals": 0,
            "win_rate": 0.0,
            "total_hits": 0,
            "total_misses": 0,
            "avg_absorption_z": 0.0,
            "avg_directional_speed": 0.0,
            "signal_frequency_pct": 0.0,
            "valid": False,
            "lookahead_results": {}
        }
    
    hits = signals['hit'].sum()
    misses = signals['miss'].sum()
    win_rate = hits / total_signals if total_signals > 0 else 0.0
    
    # Métricas por lookahead
    lookahead_results = {}
    for hours in GOLD_WHALE_CONFIG['future_lookahead_hours']:
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
        "symbol": "GOLD",
        "total_signals": total_signals,
        "win_rate": round(win_rate, 4),
        "total_hits": int(hits),
        "total_misses": int(misses),
        "avg_absorption_z": round(signals['absorption_z'].mean(), 2),
        "avg_directional_speed": round(signals['directional_speed'].mean(), 4),
        "avg_return_3h_pips": round(signals['ret_3h_pips'].mean(), 4),
        "avg_hit_return_pips": round(hit_returns.mean(), 4) if len(hit_returns) > 0 else 0.0,
        "avg_miss_return_pips": round(miss_returns.mean(), 4) if len(miss_returns) > 0 else 0.0,
        "signal_frequency_pct": round(total_signals / len(df) * 100, 2),
        "valid": total_signals >= GOLD_WHALE_CONFIG['min_signals'],
        "lookahead_results": lookahead_results
    }
    
    return metrics


def print_whale_report(metrics: dict, df: pd.DataFrame):
    """
    Imprime un reporte formateado de los resultados Whale para GOLD.
    """
    print(f"\n{'='*60}")
    print(f"🐋 EXP-013-GOLD: WHALE TRACKER — GOLD (Firma de Clímax)")
    print(f"{'='*60}")
    
    if not metrics['valid'] or metrics['total_signals'] == 0:
        print(f"⚠️  No se detectaron suficientes señales de ballena en GOLD.")
        print(f"   Señales encontradas: {metrics['total_signals']}")
        print(f"   Mínimo requerido: {GOLD_WHALE_CONFIG['min_signals']}")
        print(f"\n🔬 DIAGNÓSTICO:")
        print(f"   • Umbral Volumen: {GOLD_WHALE_CONFIG['vol_std_multiplier']}σ")
        print(f"   • Umbral Velocidad: {GOLD_WHALE_CONFIG['speed_threshold']}σ")
        print(f"   • Umbral Absorción Z: {GOLD_WHALE_CONFIG['absorption_z_threshold']}")
        print(f"\n💡 Sugerencia: Si hay 0 señales, el mercado de GOLD puede haber")
        print(f"   estado en un régimen de baja volatilidad en este período.")
        print(f"{'='*60}\n")
        return
    
    print(f"\n📊 ESTADÍSTICAS GLOBALES:")
    print(f"   • Total de velas analizadas: {len(df):,}")
    print(f"   • Señales Whale (únicas): {metrics['total_signals']}")
    print(f"   • Frecuencia de señal: {metrics['signal_frequency_pct']:.2f}%")
    
    print(f"\n🏆 RENDIMIENTO DE LA SEÑAL (Reversión — Titan Logic):")
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
    
    print(f"\n🔬 PERFIL DE LA BALLENA (GOLD):")
    print(f"   • Z-score de Absorción promedio: {metrics['avg_absorption_z']:+.2f}")
    print(f"   • Directional Speed promedio: {metrics['avg_directional_speed']:+.4f}")
    
    # Interpretación
    print(f"\n🧠 INTERPRETACIÓN (Firma de Clímax):")
    wr = metrics['win_rate']
    if wr >= 0.65:
        print(f"   ✅ SEÑAL ROBUSTA — La huella de ballena en GOLD es confiable.")
        print(f"   🎯 Estrategia: Operar la REVERSIÓN del directional_speed")
        print(f"      DS>0 → VENDER (techo de ballena)")
        print(f"      DS<0 → COMPRAR (suelo de ballena)")
        print(f"   🏆 'The Vacuum' confirmado: la ballena crea el vacío y revierte.")
    elif wr >= 0.55:
        print(f"   ⚠️  SEÑAL MODERADA — Hay edge pero necesita filtros adicionales.")
        print(f"   🔧 Sugerencia: Combinar con regime_sniper o shadow_clustering.")
    elif wr >= 0.45:
        print(f"   ❓ SEÑAL NEUTRAL — La señal no es mejor que aleatorio.")
        print(f"   🔧 Sugerencia: Ajustar thresholds o probar con más datos.")
    else:
        print(f"   ❌ SIN EDGE — La señal es contraproducente.")
        print(f"   🔧 Sugerencia: Revisar la lógica de detección o proxies usados.")
    
    print(f"\n📋 COMPARATIVA vs EURUSD:")
    print(f"   • EURUSD usa rejection_speed (del broker)")
    print(f"   • GOLD usa directional_speed (avg_speed + micro_trend)")
    print(f"   • Thresholds GOLD: Vol {GOLD_WHALE_CONFIG['vol_std_multiplier']}σ, "
          f"Speed {GOLD_WHALE_CONFIG['speed_threshold']}σ, "
          f"Abs {GOLD_WHALE_CONFIG['absorption_z_threshold']}σ")
    
    print(f"{'='*60}\n")


def export_whale_data(df: pd.DataFrame):
    """
    Exporta el dataset con señales Whale para GOLD.
    """
    output_path = os.path.join(
        GOLD_WHALE_CONFIG['output_dir'],
        "gold_whale_data_calibrated.csv"
    )
    df.to_csv(output_path)
    print(f"💾 Datos Whale GOLD exportados: {output_path}")
    
    # Exportar solo las señales únicas
    df_temp = df.copy()
    df_temp['signal_block'] = (df_temp['whale_signal'].diff() != 0).cumsum()
    
    signal_blocks = df_temp[df_temp['whale_signal'] == 1].groupby('signal_block')
    first_timestamps = signal_blocks.apply(lambda x: x.index[0])
    
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
            GOLD_WHALE_CONFIG['output_dir'],
            "gold_whale_signals_calibrated.csv"
        )
        unique_signals.to_csv(signals_path)
        print(f"💾 Señales Whale GOLD (únicas): {signals_path} ({len(unique_signals)} señales)")


def export_metrics_json(metrics: dict):
    """
    Exporta las métricas a JSON para consumo por el war room.
    """
    output_path = os.path.join(
        GOLD_WHALE_CONFIG['output_dir'],
        "gold_whale_metrics_calibrated.json"
    )
    with open(output_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"💾 Métricas Whale GOLD exportadas: {output_path}")


# ──────────────────────────────────────────────────────────────
# ORQUESTADOR PRINCIPAL
# ──────────────────────────────────────────────────────────────

def run_gold_whale_tracker() -> dict:
    """
    Ejecuta el pipeline completo de detección de ballenas para GOLD.
    
    Pipeline:
      1. Carga datos masivos de GOLD
      2. Valida DataFrame
      3. Calcula features calibradas (Firma de Clímax)
      4. Deduplica señales
      5. Valida el Edge (Titan Logic — Reversión)
      6. Calcula métricas
      7. Reporte
      8. Exporta resultados
    """
    print(f"\n{'#'*60}")
    print(f"🐋 Ejecutando EXP-013-GOLD: Whale Tracker (Firma de Clímax)...")
    print(f"{'#'*60}")
    
    # 1. Cargar datos masivos de GOLD
    file_path = os.path.join(
        GOLD_WHALE_CONFIG['data_dir'],
        "gold_massive_lab_data.csv"
    )
    
    if not os.path.exists(file_path):
        print(f"❌ No se encuentra {file_path}.")
        print(f"   Ejecuta mass_tick_downloader.py primero para descargar datos masivos.")
        return {"symbol": "GOLD", "error": "Data file not found", "valid": False}
    
    print(f"📂 Cargando: {file_path}")
    df = pd.read_csv(file_path, index_col='time', parse_dates=True)
    print(f"   • Filas cargadas: {len(df):,}")
    print(f"   • Rango: {df.index[0]} → {df.index[-1]}")
    
    # 2. Validar DataFrame
    if not validate_dataframe(df):
        return {"symbol": "GOLD", "error": "Invalid DataFrame", "valid": False}
    
    # 3. Calcular features Whale (Firma de Clímax)
    print(f"\n🔬 Calculando features de Firma de Clímax para GOLD...")
    print(f"   • Volumen Masivo: >{GOLD_WHALE_CONFIG['vol_std_multiplier']}σ")
    print(f"   • Velocidad Direccional: >{GOLD_WHALE_CONFIG['speed_threshold']}σ")
    print(f"   • Absorción Z: >{GOLD_WHALE_CONFIG['absorption_z_threshold']}")
    df = compute_gold_whale_features(df)
    
    # 4. Deduplicar señales
    print(f"🧹 Deduplicando señales...")
    df = deduplicate_signals(df)
    
    # 5. Validar el Edge (Titan Logic — Reversión)
    print(f"📐 Validando edge de reversión (Titan Logic)...")
    print(f"   • Lookaheads: {GOLD_WHALE_CONFIG['future_lookahead_hours']}h")
    print(f"   • Lógica: DS>0→VENDER (techo) | DS<0→COMPRAR (suelo)")
    df = validate_whale_edge(df)
    
    # 6. Calcular métricas
    metrics = compute_whale_metrics(df)
    
    # 7. Reporte
    print_whale_report(metrics, df)
    
    # 8. Exportar resultados
    export_whale_data(df)
    export_metrics_json(metrics)
    
    return metrics


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"🐋🐋 WHALE TRACKER GOLD — CALIBRACIÓN DE CLÍMAX 🐋🐋")
    print(f"{'='*60}")
    print(f"\n📋 Configuración:")
    print(f"   • Volumen Masivo: {GOLD_WHALE_CONFIG['vol_std_multiplier']}σ (vs 1.5σ EURUSD)")
    print(f"   • Velocidad: {GOLD_WHALE_CONFIG['speed_threshold']}σ (vs 2.0σ EURUSD)")
    print(f"   • Absorción Z: {GOLD_WHALE_CONFIG['absorption_z_threshold']} (vs 1.0 EURUSD)")
    print(f"   • Proxy Speed: avg_speed + micro_trend (GOLD no tiene rejection_speed)")
    print(f"   • Lógica: Reversión (Titan Logic — 'The Vacuum')")
    
    metrics = run_gold_whale_tracker()
    
    print(f"\n{'='*60}")
    print(f"🏁 EXP-013-GOLD COMPLETADO")
    print(f"{'='*60}")
