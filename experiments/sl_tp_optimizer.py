"""
NEXUS QUANT LAB — Experimento 5
=================================
sl_tp_optimizer.py

EXP-005: Optimización de SL/TP (Maximum Adverse Excursion)
===========================================================

Hipótesis:
  Con datos REALES de EURUSD, queremos medir cuánto se mueve el precio
  en contra de un trade del Sniper System antes de girar a favor.
  
  Si el 90% de los trades no retroceden más de X ATR, podemos ajustar
  el SL de 1.5x ATR a X ATR y arriesgar menos por trade.

Pipeline:
  1. Cargar datos reales de eurusd_lab_data.csv
  2. Calcular ATR(14) y dirección de cada vela
  3. Simular trades de reversión (Sniper Logic):
     - Vela verde → SHORT (reversión a la baja)
     - Vela roja → LONG (reversión al alza)
  4. Para cada trade, medir en ventana de 6 horas:
     - MAE: Máximo movimiento en contra (en ATRs)
     - MFE: Máximo movimiento a favor (en ATRs)
  5. Encontrar el SL óptimo basado en percentiles del MAE
  6. Visualizar distribución

Uso:
  python experiments/sl_tp_optimizer.py
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import logging
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PLOTS_DIR = Path(__file__).parent.parent / "notebook_research" / "plots"
RESULTS_DIR = Path(__file__).parent.parent / "notebook_research"


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calcula Average True Range."""
    high, low, close = df["high"], df["low"], df["close"]
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr.fillna(tr.rolling(window=period, min_periods=1).mean())


def run_mae_mfe_analysis(symbol: str = "EURUSD"):
    """
    Ejecuta el análisis MAE/MFE sobre datos reales.
    
    Simula trades del Sniper System:
      - Vela verde (close > open) → SHORT (reversión)
      - Vela roja (close < open) → LONG (reversión)
    
    Mide en ventana de 6 horas:
      - MAE: Máximo movimiento en contra (en ATRs)
      - MFE: Máximo movimiento a favor (en ATRs)
    """
    logger.info("=" * 70)
    logger.info(f"🔬 EXP-005: OPTIMIZACIÓN SL/TP — {symbol} (DATOS REALES)")
    logger.info("=" * 70)
    
    # 1. Cargar datos reales
    data_path = Path(__file__).parent.parent / "data" / f"{symbol.lower()}_lab_data.csv"
    logger.info(f"📂 Cargando datos reales: {data_path}")
    
    df = pd.read_csv(data_path, index_col="time", parse_dates=True)
    logger.info(f"   ✅ {len(df)} velas H1 cargadas ({df.index[0]} → {df.index[-1]})")
    
    # 2. Calcular ATR y dirección
    df["atr"] = calculate_atr(df)
    df["direction"] = np.where(df["close"] >= df["open"], 1, -1)  # 1=verde, -1=roja
    
    # 3. Simular trades y capturar MAE/MFE
    lookahead = 6  # 6 velas H1 = 6 horas
    mae_list = []
    mfe_list = []
    trade_directions = []
    entry_prices = []
    entry_times = []
    atr_at_entry = []
    
    # Pre-calcular futuros highs/lows para eficiencia
    future_highs = [df["high"].shift(-i) for i in range(1, lookahead + 1)]
    future_lows = [df["low"].shift(-i) for i in range(1, lookahead + 1)]
    
    for i in range(len(df) - lookahead):
        entry = df["close"].iloc[i]
        atr = df["atr"].iloc[i]
        
        if pd.isna(atr) or atr <= 0:
            continue
        
        # Sniper Logic: Reversión contra la dirección de la vela
        # Vela verde (direction=1) → SHORT (esperamos que baje)
        # Vela roja (direction=-1) → LONG (esperamos que suba)
        is_long = df["direction"].iloc[i] == -1  # Vela roja → LONG
        
        window_highs = [h.iloc[i] for h in future_highs]
        window_lows = [l.iloc[i] for l in future_lows]
        
        if is_long:
            max_against = entry - min(window_lows)   # Cuánto bajó antes de subir
            max_favor = max(window_highs) - entry     # Cuánto subió
        else:
            max_against = max(window_highs) - entry   # Cuánto subió antes de bajar
            max_favor = entry - min(window_lows)      # Cuánto bajó
        
        # Normalizar por ATR
        mae_list.append(max_against / atr)
        mfe_list.append(max_favor / atr)
        trade_directions.append("LONG" if is_long else "SHORT")
        entry_prices.append(entry)
        entry_times.append(df.index[i])
        atr_at_entry.append(atr)
    
    mae_arr = np.array(mae_list)
    mfe_arr = np.array(mfe_list)
    
    # 4. Análisis de Eficiencia
    n_trades = len(mae_arr)
    logger.info(f"\n📊 ANÁLISIS DE EXCURSIÓN ADVERSA (MAE) — {n_trades} trades simulados:")
    logger.info(f"   📉 MAE medio: {mae_arr.mean():.3f}x ATR")
    logger.info(f"   📉 MAE mediana: {np.median(mae_arr):.3f}x ATR")
    logger.info(f"   📉 MAE std: {mae_arr.std():.3f}x ATR")
    logger.info(f"   📉 MAE P75: {np.percentile(mae_arr, 75):.3f}x ATR")
    logger.info(f"   📉 MAE P90: {np.percentile(mae_arr, 90):.3f}x ATR")
    logger.info(f"   📉 MAE P95: {np.percentile(mae_arr, 95):.3f}x ATR")
    logger.info(f"   📉 MAE P99: {np.percentile(mae_arr, 99):.3f}x ATR")
    logger.info(f"   📉 MAE Máximo: {mae_arr.max():.3f}x ATR")
    
    logger.info(f"\n📊 ANÁLISIS DE EXCURSIÓN FAVORABLE (MFE):")
    logger.info(f"   📈 MFE medio: {mfe_arr.mean():.3f}x ATR")
    logger.info(f"   📈 MFE mediana: {np.median(mfe_arr):.3f}x ATR")
    logger.info(f"   📈 MFE P90: {np.percentile(mfe_arr, 90):.3f}x ATR")
    
    # 5. Encontrar SL óptimo
    # Buscamos el SL que maximiza: WR - 2 * %ganancias_detenidas
    # Para esto necesitamos saber qué trades serían "ganadores" vs "perdedores"
    # Un trade es "ganador" si MFE > SL (llegó a estar en ganancia suficiente)
    # Un trade es "perdedor" si nunca superó el SL
    
    sl_candidates = np.arange(0.1, 3.0, 0.1)
    sl_analysis = []
    
    for sl_atr in sl_candidates:
        # Trades que habrían sobrevivido (MAE < SL)
        survived = mae_arr < sl_atr
        n_survived = survived.sum()
        
        # De los que sobreviven, cuántos son "ganadores" (MFE > 0)
        # y cuántos "perdedores" (MFE ≈ 0, no se movieron a favor)
        winners = (mae_arr < sl_atr) & (mfe_arr > 0.3)  # MFE mínimo para ser ganador
        losers = (mae_arr < sl_atr) & (mfe_arr <= 0.3)
        
        # Trades que habrían sido detenidos por SL
        stopped = ~survived
        stopped_winners = stopped & (mfe_arr > 0.3)  # Falsos stops (iban a ganar)
        stopped_losers = stopped & (mfe_arr <= 0.3)  # Stops correctos
        
        wr_with_sl = winners.sum() / max(n_survived, 1) * 100
        
        sl_analysis.append({
            "sl_atr": sl_atr,
            "n_survived": n_survived,
            "n_winners": int(winners.sum()),
            "n_losers": int(losers.sum()),
            "n_stopped": int(stopped.sum()),
            "n_false_stops": int(stopped_winners.sum()),
            "n_correct_stops": int(stopped_losers.sum()),
            "wr_survived": wr_with_sl,
            "pct_false_stops": stopped_winners.sum() / max(n_trades, 1) * 100,
            "pct_correct_stops": stopped_losers.sum() / max(n_trades, 1) * 100,
        })
    
    sl_df = pd.DataFrame(sl_analysis)
    
    # Score: maximizar WR minimizando falsos stops
    # Score = WR - 3 * %falsos_stops (penalizamos fuerte los falsos stops)
    sl_df["score"] = sl_df["wr_survived"] - 3 * sl_df["pct_false_stops"]
    best_idx = sl_df["score"].idxmax()
    best_sl = sl_df.loc[best_idx]
    
    # También encontrar el SL que maximiza WR con <5% falsos stops
    safe_sl_df = sl_df[sl_df["pct_false_stops"] < 5]
    if len(safe_sl_df) > 0:
        best_safe_idx = safe_sl_df["wr_survived"].idxmax()
        best_safe_sl = sl_df.loc[best_safe_idx]
    else:
        best_safe_sl = best_sl
    
    # 6. Imprimir veredicto
    print("\n" + "=" * 70)
    print(f"📊 EXP-005: OPTIMIZACIÓN SL/TP — VEREDICTO ({symbol})")
    print("=" * 70)
    
    print(f"\n📈 ESTADÍSTICAS GLOBALES:")
    print(f"   Velas analizadas:     {len(df)}")
    print(f"   Trades simulados:     {n_trades}")
    print(f"   Ventana de análisis:  {lookahead} horas")
    
    print(f"\n📊 DISTRIBUCIÓN DE MAE (Maximum Adverse Excursion):")
    print(f"   MAE medio:            {mae_arr.mean():.3f}x ATR")
    print(f"   MAE mediana:          {np.median(mae_arr):.3f}x ATR")
    print(f"   MAE P75:              {np.percentile(mae_arr, 75):.3f}x ATR")
    print(f"   MAE P90:              {np.percentile(mae_arr, 90):.3f}x ATR")
    print(f"   MAE P95:              {np.percentile(mae_arr, 95):.3f}x ATR")
    print(f"   MAE P99:              {np.percentile(mae_arr, 99):.3f}x ATR")
    print(f"   MAE Máximo:           {mae_arr.max():.3f}x ATR")
    
    print(f"\n🎯 SL ÓPTIMO (Score Máximo):")
    print(f"   SL recomendado:       {best_sl['sl_atr']:.1f}x ATR")
    print(f"   Trades sobreviven:    {best_sl['n_survived']} ({best_sl['n_survived']/n_trades*100:.1f}%)")
    print(f"   WR entre sobreviv.:   {best_sl['wr_survived']:.1f}%")
    print(f"   Falsos stops:         {best_sl['n_false_stops']} ({best_sl['pct_false_stops']:.1f}%)")
    print(f"   Stops correctos:      {best_sl['n_correct_stops']} ({best_sl['pct_correct_stops']:.1f}%)")
    
    print(f"\n🎯 SL SEGURO (<5% Falsos Stops):")
    print(f"   SL recomendado:       {best_safe_sl['sl_atr']:.1f}x ATR")
    print(f"   Trades sobreviven:    {best_safe_sl['n_survived']} ({best_safe_sl['n_survived']/n_trades*100:.1f}%)")
    print(f"   WR entre sobreviv.:   {best_safe_sl['wr_survived']:.1f}%")
    print(f"   Falsos stops:         {best_safe_sl['n_false_stops']} ({best_safe_sl['pct_false_stops']:.1f}%)")
    
    # Comparación con SL actual (1.5 ATR)
    current_sl_row = sl_df[sl_df["sl_atr"] == 1.5]
    if len(current_sl_row) > 0:
        current = current_sl_row.iloc[0]
        print(f"\n💡 COMPARACIÓN CON SL ACTUAL (1.5x ATR):")
        print(f"   SL actual:            1.5x ATR")
        print(f"   WR actual:            {current['wr_survived']:.1f}%")
        print(f"   Falsos stops actual:  {current['pct_false_stops']:.1f}%")
        
        if best_sl["sl_atr"] < 1.5:
            reduction = (1.5 - best_sl["sl_atr"]) / 1.5 * 100
            print(f"\n   🚀 ¡Podemos REDUCIR el SL en {reduction:.0f}%!")
            print(f"      De 1.5x → {best_sl['sl_atr']:.1f}x ATR")
            print(f"      Nuevo riesgo: {best_sl['sl_atr']/1.5*100:.0f}% del riesgo actual")
        elif best_sl["sl_atr"] > 1.5:
            print(f"\n   ⚠️ El SL actual de 1.5x es DEMASIADO AJUSTADO.")
            print(f"      Se recomienda ampliarlo a {best_sl['sl_atr']:.1f}x ATR")
        else:
            print(f"\n   ✅ El SL actual de 1.5x ATR es ÓPTIMO.")
    
    print("\n" + "=" * 70)
    
    # 7. Visualización
    os.makedirs(PLOTS_DIR, exist_ok=True)
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(
        f"EXP-005: Optimización SL/TP — {symbol} (Datos Reales)\n"
        f"{n_trades} trades simulados | Ventana: {lookahead}h | "
        f"MAE P90: {np.percentile(mae_arr, 90):.2f}x ATR",
        fontsize=14,
        fontweight="bold",
    )
    
    # 1. Histograma MAE
    ax1 = axes[0, 0]
    ax1.hist(mae_arr, bins=30, color="#e74c3c", alpha=0.7, edgecolor="white", linewidth=0.5)
    ax1.axvline(1.5, color="blue", linestyle="--", linewidth=2, label="SL Actual (1.5x ATR)")
    ax1.axvline(best_sl["sl_atr"], color="green", linestyle="-", linewidth=2,
                label=f"SL Óptimo ({best_sl['sl_atr']:.1f}x ATR)")
    ax1.axvline(np.percentile(mae_arr, 90), color="orange", linestyle=":", linewidth=1.5,
                label=f"P90 ({np.percentile(mae_arr, 90):.2f}x ATR)")
    ax1.set_title("Distribución de MAE\n(Máxima Excursión Adversa)", fontsize=12, fontweight="bold")
    ax1.set_xlabel("MAE (en ATRs)")
    ax1.set_ylabel("Frecuencia")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.15)
    
    # 2. Histograma MFE
    ax2 = axes[0, 1]
    ax2.hist(mfe_arr, bins=30, color="#2ecc71", alpha=0.7, edgecolor="white", linewidth=0.5)
    ax2.axvline(mfe_arr.mean(), color="darkgreen", linestyle="--", linewidth=2,
                label=f"MFE medio ({mfe_arr.mean():.2f}x ATR)")
    ax2.set_title("Distribución de MFE\n(Máxima Excursión Favorable)", fontsize=12, fontweight="bold")
    ax2.set_xlabel("MFE (en ATRs)")
    ax2.set_ylabel("Frecuencia")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.15)
    
    # 3. MAE vs MFE Scatter
    ax3 = axes[1, 0]
    ax3.scatter(mae_arr, mfe_arr, alpha=0.4, s=8, c="#3498db", edgecolors="none")
    ax3.axhline(0.3, color="red", linestyle="--", alpha=0.5, label="Umbral ganador (MFE=0.3)")
    ax3.axvline(1.5, color="blue", linestyle="--", alpha=0.5, label="SL Actual (1.5x)")
    ax3.axvline(best_sl["sl_atr"], color="green", linestyle="-", alpha=0.5,
                label=f"SL Óptimo ({best_sl['sl_atr']:.1f}x)")
    ax3.set_title("MAE vs MFE por Trade", fontsize=12, fontweight="bold")
    ax3.set_xlabel("MAE (ATRs)")
    ax3.set_ylabel("MFE (ATRs)")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.15)
    
    # 4. Análisis de SL candidatos
    ax4 = axes[1, 1]
    ax4.plot(sl_df["sl_atr"], sl_df["wr_survived"], "b-", linewidth=2, label="WR entre sobrevivientes")
    ax4.plot(sl_df["sl_atr"], sl_df["pct_false_stops"], "r--", linewidth=2, label="% Falsos Stops")
    ax4.plot(sl_df["sl_atr"], sl_df["pct_correct_stops"], "g--", linewidth=2, label="% Stops Correctos")
    ax4.axvline(best_sl["sl_atr"], color="red", linestyle=":", linewidth=2,
                label=f"SL Óptimo: {best_sl['sl_atr']:.1f}x")
    ax4.axvline(1.5, color="blue", linestyle=":", linewidth=1.5, alpha=0.7, label="SL Actual: 1.5x")
    ax4.set_title("Análisis de SL Candidatos", fontsize=12, fontweight="bold")
    ax4.set_xlabel("SL (en ATRs)")
    ax4.set_ylabel("Porcentaje (%)")
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.15)
    
    plt.tight_layout()
    plot_path = PLOTS_DIR / f"exp_005_mae_{symbol.lower()}.png"
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    logger.info(f"🖼️ Gráfico guardado: {plot_path}")
    plt.close()
    
    # Guardar resultados
    os.makedirs(RESULTS_DIR, exist_ok=True)
    results_summary = {
        "symbol": symbol,
        "n_candles": len(df),
        "n_trades": n_trades,
        "lookahead_hours": lookahead,
        "mae_mean": float(mae_arr.mean()),
        "mae_median": float(np.median(mae_arr)),
        "mae_p75": float(np.percentile(mae_arr, 75)),
        "mae_p90": float(np.percentile(mae_arr, 90)),
        "mae_p95": float(np.percentile(mae_arr, 95)),
        "mae_p99": float(np.percentile(mae_arr, 99)),
        "mae_max": float(mae_arr.max()),
        "mfe_mean": float(mfe_arr.mean()),
        "mfe_median": float(np.median(mfe_arr)),
        "best_sl_atr": float(best_sl["sl_atr"]),
        "best_sl_wr": float(best_sl["wr_survived"]),
        "best_sl_false_stops_pct": float(best_sl["pct_false_stops"]),
        "safe_sl_atr": float(best_safe_sl["sl_atr"]),
        "safe_sl_wr": float(best_safe_sl["wr_survived"]),
        "safe_sl_false_stops_pct": float(best_safe_sl["pct_false_stops"]),
    }
    pd.DataFrame([results_summary]).to_csv(RESULTS_DIR / "exp_005_results_real.csv", index=False)
    logger.info(f"📁 Resultados guardados en {RESULTS_DIR}")
    
    return results_summary


if __name__ == "__main__":
    results = run_mae_mfe_analysis("EURUSD")
    
    print("\n" + "=" * 70)
    print("📋 RESUMEN RÁPIDO EXP-005 (DATOS REALES)")
    print("=" * 70)
    print(f"   Símbolo:              {results['symbol']}")
    print(f"   Velas analizadas:     {results['n_candles']}")
    print(f"   Trades simulados:     {results['n_trades']}")
    print(f"   MAE medio:            {results['mae_mean']:.3f}x ATR")
    print(f"   MAE P90:              {results['mae_p90']:.3f}x ATR")
    print(f"   MAE P95:              {results['mae_p95']:.3f}x ATR")
    print(f"   SL óptimo (score):    {results['best_sl_atr']:.1f}x ATR")
    print(f"   SL seguro (<5% falsos): {results['safe_sl_atr']:.1f}x ATR")
    print(f"   WR con SL seguro:     {results['safe_sl_wr']:.1f}%")
    print("=" * 70)
