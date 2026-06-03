"""
EXP-014: Judas Profiling — La Ballena como Filtro de Continuación
==================================================================
Objetivo: Determinar si la huella de la ballena debe usarse como
filtro de continuación (Runner) en lugar de señal de reversión (Sniper).

Hipótesis Corregida:
  Lo que llamamos "Absorción para Reversión" en realidad es
  "Re-acumulación para Continuación". La ballena no frena el precio
  para girarlo, está "rellenando el tanque" para empujarlo con más
  fuerza en la dirección original.

  El Win Rate de reversión del 7.69% en EXP-013 no es un error —
  es una REVELACIÓN. La ballena tiene inercia masiva.

Framework: Sentinel V2 — Rigor de Código Industrial
"""

import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta

# ──────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────────────────────
JUDAS_CONFIG = {
    "data_dir": "data",
    "output_dir": "data",
    "lookaheads": [3, 6, 12, 24],  # Horizonte de validación en horas
    "min_signals": 5,               # Mínimo de señales para análisis válido
    "pip_threshold": 0.5,           # Movimiento mínimo en pips para hit/miss
}

# ──────────────────────────────────────────────────────────────
# NÚCLEO DE ANÁLISIS JUDAS
# ──────────────────────────────────────────────────────────────

def load_whale_data(symbol: str) -> pd.DataFrame:
    """
    Carga el dataset generado por EXP-013 con señales Whale.
    """
    file_path = os.path.join(
        JUDAS_CONFIG['data_dir'],
        f"{symbol.lower()}_whale_data.csv"
    )
    
    if not os.path.exists(file_path):
        print(f"❌ No se encuentra {file_path}.")
        print(f"   Ejecuta whale_tracker.py primero.")
        return None
    
    print(f"📂 Cargando datos Whale: {file_path}")
    df = pd.read_csv(file_path, index_col='time', parse_dates=True)
    print(f"   • Filas: {len(df):,}")
    print(f"   • Señales Whale: {df['whale_signal'].sum()}")
    
    return df


def analyze_trend_vs_reversal(df: pd.DataFrame, symbol: str) -> dict:
    """
    Compara dos hipótesis enfrentadas:
    
    HIPÓTESIS A (EXP-013 original): La ballena REVIERTE el precio.
      - RS > 0 (empuje arriba) → esperamos caída (ret < 0)
      - RS < 0 (empuje abajo) → esperamos subida (ret > 0)
    
    HIPÓTESIS B (EXP-014 - CORREGIDA): La ballena CONFIRMA la tendencia.
      - RS > 0 (empuje arriba) → esperamos subida (ret > 0)
      - RS < 0 (empuje abajo) → esperamos bajada (ret < 0)
    
    La hipótesis con mayor Win Rate revela la verdadera intención
    de la ballena.
    """
    signals = df[df['whale_signal'] == 1].copy()
    total_signals = len(signals)
    
    if total_signals == 0:
        return {"symbol": symbol, "total_signals": 0, "valid": False}
    
    results = {
        "symbol": symbol,
        "total_signals": total_signals,
        "valid": total_signals >= JUDAS_CONFIG['min_signals'],
        "lookaheads": {}
    }
    
    print(f"\n{'='*60}")
    print(f"🕵️ EXP-014: JUDAS PROFILING — {symbol}")
    print(f"{'='*60}")
    print(f"\n📊 Comparando Hipótesis sobre {total_signals} señales Whale:")
    
    for hours in JUDAS_CONFIG['lookaheads']:
        col_ret = f'ret_{hours}h_pips'
        
        # Si el dataset no tiene esta columna, calcularla
        if col_ret not in signals.columns:
            future_close = df['close'].shift(-hours)
            signals[col_ret] = (future_close - signals['close']) * 10000
        
        # ── HIPÓTESIS A: Reversión ──
        # RS > 0 → esperamos ret < 0 (caída)
        # RS < 0 → esperamos ret > 0 (subida)
        signals['hit_reversal'] = np.where(
            (
                (signals['rejection_speed'] > 0) & 
                (signals[col_ret] < -JUDAS_CONFIG['pip_threshold'])
            ) |
            (
                (signals['rejection_speed'] < 0) & 
                (signals[col_ret] > JUDAS_CONFIG['pip_threshold'])
            ),
            1, 0
        )
        
        # ── HIPÓTESIS B: Continuación (CORREGIDA) ──
        # RS > 0 → esperamos ret > 0 (subida)
        # RS < 0 → esperamos ret < 0 (caída)
        signals['hit_trend'] = np.where(
            (
                (signals['rejection_speed'] > 0) & 
                (signals[col_ret] > JUDAS_CONFIG['pip_threshold'])
            ) |
            (
                (signals['rejection_speed'] < 0) & 
                (signals[col_ret] < -JUDAS_CONFIG['pip_threshold'])
            ),
            1, 0
        )
        
        wr_reversal = signals['hit_reversal'].mean()
        wr_trend = signals['hit_trend'].mean()
        avg_ret = signals[col_ret].mean()
        
        results['lookaheads'][f'{hours}h'] = {
            "wr_reversal": round(wr_reversal, 4),
            "wr_trend": round(wr_trend, 4),
            "avg_return_pips": round(avg_ret, 4),
            "winner": "TREND" if wr_trend > wr_reversal else "REVERSAL",
            "margin": round(abs(wr_trend - wr_reversal), 4)
        }
        
        # Imprimir resultados
        winner = "📈 CONTINUACIÓN (Ballena Confirma)" if wr_trend > wr_reversal else "📉 REVERSIÓN (EXP-013)"
        margin_pct = abs(wr_trend - wr_reversal) * 100
        
        print(f"\n  ⏱  Lookahead {hours}h:")
        print(f"     📉 Reversión WR: {wr_reversal:.2%}")
        print(f"     📈 Tendencia WR: {wr_trend:.2%}")
        print(f"     🏆 Ganadora: {winner} (+{margin_pct:.1f} pts)")
        print(f"     💰 Retorno promedio: {avg_ret:+.2f} pips")
    
    return results


def analyze_volume_delta_alignment(df: pd.DataFrame, symbol: str) -> dict:
    """
    Analiza si la dirección del volume_delta durante la señal Whale
    predice la dirección futura.
    
    Hipótesis: Si el volume_delta está en la misma dirección que
    el rejection_speed, la ballena está COMPRANDO/VENDIENDO activamente.
    Si está en contra, está ABSORBIENDO órdenes de minoristas.
    """
    signals = df[df['whale_signal'] == 1].copy()
    total_signals = len(signals)
    
    if total_signals == 0:
        return {}
    
    # Dirección del volume_delta durante la señal
    signals['vol_delta_direction'] = np.sign(signals['volume_delta'])
    signals['rs_direction'] = np.sign(signals['rejection_speed'])
    
    # ¿Están alineados o en conflicto?
    signals['aligned'] = np.where(
        signals['vol_delta_direction'] == signals['rs_direction'],
        1, 0
    )
    
    aligned_count = signals['aligned'].sum()
    conflict_count = total_signals - aligned_count
    
    # Rendimiento cuando están alineados vs en conflicto
    for hours in JUDAS_CONFIG['lookaheads']:
        col_ret = f'ret_{hours}h_pips'
        if col_ret not in signals.columns:
            continue
        
        aligned_ret = signals[signals['aligned'] == 1][col_ret].mean()
        conflict_ret = signals[signals['aligned'] == 0][col_ret].mean()
        
        print(f"\n  📊 Alineación Volume Delta vs RS ({hours}h):")
        print(f"     ✅ Alineados: {aligned_count} señales → retorno {aligned_ret:+.2f} pips")
        print(f"     ⚔️  Conflicto: {conflict_count} señales → retorno {conflict_ret:+.2f} pips")
    
    return {
        "aligned_count": int(aligned_count),
        "conflict_count": int(conflict_count),
        "aligned_pct": round(aligned_count / total_signals * 100, 2)
    }


def analyze_whale_aftermath(df: pd.DataFrame, symbol: str) -> dict:
    """
    Analiza el comportamiento del precio DESPUÉS de la señal Whale
    en ventanas de tiempo progresivas.
    
    Pregunta: ¿La ballena se va después de la señal o sigue empujando?
    """
    signals = df[df['whale_signal'] == 1].copy()
    total_signals = len(signals)
    
    if total_signals == 0:
        return {}
    
    print(f"\n  ⏳ COMPORTAMIENTO POST-BALLENA:")
    
    aftermath = {}
    for hours in [1, 2, 3, 6, 12, 24]:
        col_ret = f'ret_{hours}h_pips'
        if col_ret not in signals.columns:
            continue
        
        avg_ret = signals[col_ret].mean()
        positive_pct = (signals[col_ret] > 0).mean()
        negative_pct = (signals[col_ret] < 0).mean()
        
        direction = "📈 SUBE" if avg_ret > 0 else "📉 BAJA"
        print(f"     +{hours}h: {avg_ret:+.2f} pips ({direction}, {positive_pct:.0%}↑ / {negative_pct:.0%}↓)")
        
        aftermath[f'{hours}h'] = {
            "avg_return_pips": round(avg_ret, 4),
            "positive_pct": round(positive_pct, 4),
            "negative_pct": round(negative_pct, 4)
        }
    
    return aftermath


def compute_judas_metrics(df: pd.DataFrame, symbol: str) -> dict:
    """
    Calcula las métricas finales del Judas Profiling.
    Determina si la ballena es:
      - 🐋 REVERSIÓN: La señal predice un giro (EXP-013 original)
      - 🚂 CONTINUACIÓN: La señal confirma la tendencia (EXP-014)
      - 🎲 RUIDO: Sin poder predictivo
    """
    trend_results = analyze_trend_vs_reversal(df, symbol)
    volume_analysis = analyze_volume_delta_alignment(df, symbol)
    aftermath = analyze_whale_aftermath(df, symbol)
    
    if not trend_results['valid']:
        return {
            "symbol": symbol,
            "veredict": "INSUFFICIENT_DATA",
            "total_signals": trend_results['total_signals'],
            "valid": False
        }
    
    # Determinar el veredicto basado en el lookahead de 12h (el más confiable)
    lookahead_12h = trend_results['lookaheads'].get('12h', {})
    lookahead_24h = trend_results['lookaheads'].get('24h', {})
    
    wr_trend_12h = lookahead_12h.get('wr_trend', 0)
    wr_reversal_12h = lookahead_12h.get('wr_reversal', 0)
    wr_trend_24h = lookahead_24h.get('wr_trend', 0)
    wr_reversal_24h = lookahead_24h.get('wr_reversal', 0)
    
    # Score compuesto: qué tan dominante es la hipótesis de continuación
    trend_score = (wr_trend_12h - wr_reversal_12h) + (wr_trend_24h - wr_reversal_24h)
    
    if trend_score > 0.2:
        veredict = "CONTINUATION"
        confidence = "ALTA"
    elif trend_score > 0.05:
        veredict = "CONTINUATION"
        confidence = "MODERADA"
    elif trend_score > -0.05:
        veredict = "NOISE"
        confidence = "BAJA"
    else:
        veredict = "REVERSAL"
        confidence = "BAJA"
    
    metrics = {
        "symbol": symbol,
        "total_signals": trend_results['total_signals'],
        "veredict": veredict,
        "confidence": confidence,
        "trend_score": round(trend_score, 4),
        "lookaheads": trend_results['lookaheads'],
        "volume_alignment": volume_analysis,
        "aftermath": aftermath,
        "valid": True
    }
    
    return metrics


def print_judas_report(metrics: dict):
    """
    Imprime el reporte final del Judas Profiling.
    """
    symbol = metrics['symbol']
    
    print(f"\n{'='*60}")
    print(f"🕵️ EXP-014: JUDAS PROFILING — VEREDICTO FINAL")
    print(f"{'='*60}")
    
    if not metrics.get('valid'):
        print(f"\n⚠️  Datos insuficientes para {symbol}.")
        print(f"{'='*60}\n")
        return
    
    print(f"\n🐋 Símbolo: {symbol}")
    print(f"📊 Señales Whale analizadas: {metrics['total_signals']}")
    
    # Veredicto
    veredict = metrics['veredict']
    confidence = metrics['confidence']
    
    if veredict == "CONTINUATION":
        if confidence == "ALTA":
            print(f"\n🏆 VEREDICTO: 🚂 LA BALLENA CONFIRMA LA TENDENCIA (Confianza: ALTA)")
            print(f"   La hipótesis de CONTINUACIÓN domina sobre la reversión.")
            print(f"   Score de tendencia: {metrics['trend_score']:+.2f}")
        else:
            print(f"\n🏆 VEREDICTO: 🚂 LA BALLENA CONFIRMA LA TENDENCIA (Confianza: MODERADA)")
            print(f"   Hay evidencia de continuación pero necesita más datos.")
            print(f"   Score de tendencia: {metrics['trend_score']:+.2f}")
    elif veredict == "REVERSAL":
        print(f"\n🏆 VEREDICTO: 📉 LA BALLENA REVIERTE EL PRECIO")
        print(f"   La hipótesis original del EXP-013 es correcta.")
        print(f"   Score de tendencia: {metrics['trend_score']:+.2f}")
    else:
        print(f"\n🏆 VEREDICTO: 🎲 RUIDO — Sin poder predictivo claro")
        print(f"   La ballena no tiene dirección preferente.")
        print(f"   Score de tendencia: {metrics['trend_score']:+.2f}")
    
    # Tabla comparativa
    print(f"\n📋 COMPARATIVA POR LOOKAHEAD:")
    print(f"   {'Horizonte':<12} {'Reversión WR':<14} {'Tendencia WR':<14} {'Ganadora':<20} {'Retorno':<12}")
    print(f"   {'-'*72}")
    
    for hours, results in metrics['lookaheads'].items():
        winner_label = "📈 TREND" if results['winner'] == 'TREND' else "📉 REV"
        print(f"   {hours:<12} {results['wr_reversal']:.2%}         {results['wr_trend']:.2%}         {winner_label:<20} {results['avg_return_pips']:+.2f} pips")
    
    # Alineación de volumen
    vol = metrics.get('volume_alignment', {})
    if vol:
        print(f"\n📊 ALINEACIÓN VOLUME DELTA:")
        print(f"   • RS y VolDelta alineados: {vol.get('aligned_pct', 0):.1f}% de las señales")
        print(f"   • En conflicto: {100 - vol.get('aligned_pct', 0):.1f}%")
    
    # Aftermath
    aftermath = metrics.get('aftermath', {})
    if aftermath:
        print(f"\n⏳ COMPORTAMIENTO POST-BALLENA:")
        for hours, data in aftermath.items():
            direction = "📈" if data['avg_return_pips'] > 0 else "📉"
            print(f"   {direction} +{hours}: {data['avg_return_pips']:+.2f} pips ({data['positive_pct']:.0%}↑ / {data['negative_pct']:.0%}↓)")
    
    # Recomendación para V8.2
    print(f"\n🎯 RECOMENDACIÓN PARA V8.2 (WHALE SENTINEL):")
    
    if veredict == "CONTINUATION":
        print(f"   ✅ Integrar WhaleTracker como CAPA 7: WHALE VETO")
        print(f"   📐 Regla: Si WhaleSignal detecta absorción, NO operar en contra")
        print(f"   🚂 Estrategia: Usar la señal como confirmación de RUNNER")
        print(f"   ⚠️  Si el Sniper quiere vender pero hay absorción compradora → VETO")
    elif veredict == "REVERSAL":
        print(f"   ✅ Integrar WhaleTracker como señal de SNIPER")
        print(f"   📐 Regla: Si WhaleSignal detecta absorción, operar REVERSIÓN")
        print(f"   🎯 Estrategia: Usar la señal como entrada de reversión")
    else:
        print(f"   ⚠️  No integrar WhaleTracker como capa de veto aún")
        print(f"   🔧 Se necesita más datos o calibrar thresholds")
    
    print(f"{'='*60}\n")


def export_judas_results(metrics: dict, symbol: str):
    """
    Exporta los resultados del Judas Profiling a JSON.
    """
    output_path = os.path.join(
        JUDAS_CONFIG['output_dir'],
        f"{symbol.lower()}_judas_metrics.json"
    )
    with open(output_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"💾 Métricas Judas exportadas: {output_path}")


# ──────────────────────────────────────────────────────────────
# ORQUESTADOR PRINCIPAL
# ──────────────────────────────────────────────────────────────

def run_judas_profiling(symbol: str) -> dict:
    """
    Ejecuta el pipeline completo de Judas Profiling.
    
    Args:
        symbol: Símbolo a analizar (ej: "EURUSD", "GOLD")
    
    Returns:
        Dict con métricas y veredicto
    """
    print(f"\n{'#'*60}")
    print(f"🕵️ Ejecutando EXP-014: Judas Profiling para {symbol}...")
    print(f"{'#'*60}")
    
    # 1. Cargar datos Whale del EXP-013
    df = load_whale_data(symbol)
    if df is None:
        return {"symbol": symbol, "error": "Whale data not found", "valid": False}
    
    # 2. Calcular retornos para lookaheads que no existan
    for hours in JUDAS_CONFIG['lookaheads']:
        col_ret = f'ret_{hours}h_pips'
        if col_ret not in df.columns:
            future_close = df['close'].shift(-hours)
            df[col_ret] = (future_close - df['close']) * 10000
    
    # 3. Análisis Judas completo
    metrics = compute_judas_metrics(df, symbol)
    
    # 4. Reporte
    print_judas_report(metrics)
    
    # 5. Exportar
    export_judas_results(metrics, symbol)
    
    return metrics


def run_batch_judas(symbols: list = None):
    """
    Ejecuta Judas Profiling para múltiples símbolos.
    """
    if symbols is None:
        symbols = ["EURUSD", "GOLD"]
    
    print(f"\n{'='*60}")
    print(f"🕵️🕵️ JUDAS PROFILING — ANÁLISIS MULTI-SÍMBOLO 🕵️🕵️")
    print(f"{'='*60}")
    
    all_metrics = []
    for symbol in symbols:
        metrics = run_judas_profiling(symbol)
        all_metrics.append(metrics)
    
    # Reporte comparativo
    print(f"\n{'='*60}")
    print(f"📊 VEREDICTO COMPARATIVO")
    print(f"{'='*60}")
    
    print(f"\n{'Símbolo':<10} {'Señales':<10} {'Veredicto':<20} {'Confianza':<12} {'Score':<10}")
    print(f"{'-'*62}")
    
    for m in all_metrics:
        if m.get('valid'):
            v = m['veredict']
            label = "🚂 CONTINUACIÓN" if v == "CONTINUATION" else ("📉 REVERSIÓN" if v == "REVERSAL" else "🎲 RUIDO")
            print(f"{m['symbol']:<10} {m['total_signals']:<10} {label:<20} {m['confidence']:<12} {m['trend_score']:<+10.2f}")
        else:
            print(f"{m['symbol']:<10} {'N/A':<10} {'SIN DATOS':<20} {'N/A':<12} {'N/A':<10}")
    
    print(f"\n{'='*60}\n")
    
    return all_metrics


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="EXP-014: Judas Profiling — La Ballena como Filtro de Continuación"
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
        run_batch_judas(args.symbols)
    else:
        for symbol in args.symbols:
            run_judas_profiling(symbol)
