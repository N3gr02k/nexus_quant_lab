"""
NEXUS QUANT LAB — Experimento 5
=================================
adverse_excursion.py

EXP-005: Adverse Excursion Profiling (Optimización de SL/TP)

Hipótesis:
  Si tenemos un Win Rate del 92% (con filtro de volumen), quizás nuestro
  Stop Loss de 1.5x ATR es demasiado ancho. El 92% de los trades ganadores
  probablemente nunca se acercan a ese SL.

Objetivo:
  Medir el Maximum Adverse Excursion (MAE) y Maximum Favorable Excursion (MFE)
  de cada trade para encontrar el SL óptimo que:
    - Protege el capital (no se puede eliminar el SL)
    - Maximiza el Win Rate (no cortar trades que van a ganar)
    - Minimiza la distancia del SL (para arriesgar menos por trade)

Pipeline:
  1. Simular trades del Sniper System con datos sintéticos (con edge de volumen)
  2. Para cada trade, registrar:
     - MAE: Máximo movimiento en contra desde entrada (en ATRs)
     - MFE: Máximo movimiento a favor desde entrada (en ATRs)
  3. Distribución de MAE en trades ganadores: ¿cuánto es el "peor escenario"?
  4. Distribución de MFE en trades perdedores: ¿cuánto llegaron a estar en ganancia?
  5. Encontrar el SL óptimo: percentil 95-99 del MAE de trades ganadores
  6. Validar con Montecarlo: ¿mejora el Sharpe Ratio con SL más ajustado?

Dependencias:
  pip install pandas numpy matplotlib seaborn scipy

Uso:
  python experiments/adverse_excursion.py
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
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


def generate_synthetic_market_data(
    n_candles: int = 5000,
    seed: int = 42,
    volatility: float = 0.0008,
    trend_strength: float = 0.02,
    sniper_wr: float = 0.85,
) -> pd.DataFrame:
    """Genera datos sintéticos con edge de volumen (misma lógica que EXP-004)."""
    logger.info(f"🧪 Generando {n_candles:,} velas sintéticas...")
    np.random.seed(seed)
    
    returns = np.random.normal(0, volatility, n_candles)
    trend = np.sin(np.linspace(0, 4 * np.pi, n_candles)) * trend_strength * volatility * 10
    returns += trend
    
    price = 1.1600
    prices = [price]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    prices = np.array(prices[1:])
    
    opens = prices * (1 + np.random.normal(0, volatility * 0.3, n_candles))
    closes = prices * (1 + np.random.normal(0, volatility * 0.3, n_candles))
    highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, volatility * 0.5, n_candles)))
    lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, volatility * 0.5, n_candles)))
    
    price_ma = pd.Series(prices).rolling(5, min_periods=1).mean()
    micro_trend = price_ma.diff().fillna(0)
    micro_trend = micro_trend / micro_trend.std() if micro_trend.std() > 0 else micro_trend
    micro_trend = micro_trend.clip(-1, 1)
    
    rejection_speed = np.random.normal(0, 1, n_candles)
    wick_ratio = (highs - np.maximum(opens, closes)) / (highs - lows + 1e-10)
    rejection_speed += wick_ratio * 3
    
    vol_delta_base = micro_trend * 0.5 + np.random.normal(0, 0.3, n_candles)
    vol_delta_base = vol_delta_base.clip(-1, 1)
    
    long_signals = micro_trend > 0.3
    short_signals = micro_trend < -0.3
    vol_favorable_long = vol_delta_base > 0
    vol_favorable_short = vol_delta_base < 0
    
    trade_results = np.full(n_candles, np.nan)
    for i in range(n_candles):
        if long_signals[i] or short_signals[i]:
            favorable = vol_favorable_long[i] if long_signals[i] else vol_favorable_short[i]
            win_prob = sniper_wr + (0.08 if favorable else -0.12)
            win_prob = np.clip(win_prob, 0.05, 0.95)
            trade_results[i] = 1 if np.random.random() < win_prob else 0
    
    tick_count = np.random.poisson(2000, n_candles) + 500
    avg_speed = np.abs(returns) / (tick_count + 1) * 1000
    
    buy_fraction = 0.5 + vol_delta_base * 0.4
    buy_fraction = buy_fraction.clip(0.05, 0.95)
    total_volume = 1000 + np.random.exponential(500, n_candles)
    buy_volume = (total_volume * buy_fraction).round().astype(int)
    sell_volume = (total_volume * (1 - buy_fraction)).round().astype(int)
    
    df = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=n_candles, freq="h"),
        "open": opens, "high": highs, "low": lows, "close": closes,
        "buy_volume": buy_volume, "sell_volume": sell_volume,
        "avg_speed": avg_speed, "tick_count": tick_count,
        "volume_delta": vol_delta_base, "rejection_speed": rejection_speed,
        "micro_trend": micro_trend,
        "_signal": long_signals | short_signals,
        "_trade_result": trade_results,
        "_vol_favorable": np.where(
            long_signals, vol_favorable_long,
            np.where(short_signals, vol_favorable_short, np.nan)
        ),
    })
    df.set_index("time", inplace=True)
    
    n_signals = (~np.isnan(trade_results)).sum()
    n_wins = (trade_results == 1).sum()
    actual_wr = n_wins / n_signals * 100 if n_signals > 0 else 0
    logger.info(f"   ✅ {n_candles:,} velas generadas, {n_signals} señales, WR: {actual_wr:.1f}%")
    
    return df


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calcula Average True Range."""
    high, low, close = df["high"], df["low"], df["close"]
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr.fillna(tr.rolling(window=period, min_periods=1).mean())


def simulate_sniper_trades_with_mae_mfe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Simula trades del Sniper System REAL usando el edge inyectado en los datos.
    
    En lugar de usar SL/TP fijos (que no reflejan el Sniper), usamos el resultado
    real del trade (inyectado en generate_synthetic_market_data) y medimos MAE/MFE
    como la máxima excursión que ocurre ANTES de que el trade se resuelva.
    
    El Sniper System real:
      - Entra cuando hay barrido de muro + rejection_speed > 2σ
      - SL dinámico basado en la estructura del mercado
      - TP basado en el siguiente muro HTF
      - WR real: ~85% (base) + filtro volumen → ~92%
    """
    logger.info("🎯 Simulando Sniper System REAL con registro de MAE/MFE...")
    
    atr = calculate_atr(df)
    df = df.copy()
    df["atr"] = atr
    
    trades = []
    max_lookahead = 48  # 48 velas H1 = 2 días máximos
    
    for i in range(len(df) - 1):
        current = df.iloc[i]
        current_atr = current["atr"]
        
        if pd.isna(current_atr) or current_atr <= 0:
            continue
        
        # Señal de entrada (micro_trend)
        if current["micro_trend"] > 0.3:
            direction = "LONG"
        elif current["micro_trend"] < -0.3:
            direction = "SHORT"
        else:
            continue
        
        # FILTRO DE VOLUMEN (EXP-004): solo entrar si volumen está a favor
        vol_delta = current["volume_delta"]
        vol_favorable = (direction == "LONG" and vol_delta > 0) or \
                        (direction == "SHORT" and vol_delta < 0)
        if not vol_favorable:
            continue  # El filtro Centinela rechaza este trade
        
        entry_price = current["close"]
        
        # SL/TP del Sniper System (1.5x / 1.8x ATR)
        sl_distance = current_atr * 1.5
        tp_distance = current_atr * 1.8
        
        if direction == "LONG":
            sl_price = entry_price - sl_distance
            tp_price = entry_price + tp_distance
        else:
            sl_price = entry_price + sl_distance
            tp_price = entry_price - tp_distance
        
        # --- USAR EL RESULTADO REAL DEL TRADE (edge inyectado) ---
        # El resultado real está en _trade_result (1=WIN, 0=LOSS)
        # Esto refleja el edge real del Sniper con volumen
        trade_result_real = current["_trade_result"]
        if np.isnan(trade_result_real):
            continue  # No había señal real aquí
        
        trade_result = "WIN" if trade_result_real == 1 else "LOSS"
        
        # --- Medir MAE/MFE hasta que el trade se resuelve ---
        # Buscamos cuándo se alcanza SL o TP para saber la duración real
        max_adverse = 0.0
        max_favorable = 0.0
        bars_to_resolution = 0
        resolved_by = "unknown"
        
        for j in range(1, min(max_lookahead + 1, len(df) - i)):
            future = df.iloc[i + j]
            future_high = future["high"]
            future_low = future["low"]
            
            # Calcular excursión en esta vela (en ATRs)
            if direction == "LONG":
                adverse_move = (entry_price - future_low) / current_atr
                favorable_move = (future_high - entry_price) / current_atr
            else:
                adverse_move = (future_high - entry_price) / current_atr
                favorable_move = (entry_price - future_low) / current_atr
            
            max_adverse = max(max_adverse, adverse_move)
            max_favorable = max(max_favorable, favorable_move)
            
            # Verificar si se alcanzó SL o TP
            if direction == "LONG":
                if future_high >= tp_price:
                    bars_to_resolution = j
                    resolved_by = "TP"
                    break
                if future_low <= sl_price:
                    bars_to_resolution = j
                    resolved_by = "SL"
                    break
            else:
                if future_low <= tp_price:
                    bars_to_resolution = j
                    resolved_by = "TP"
                    break
                if future_high >= sl_price:
                    bars_to_resolution = j
                    resolved_by = "SL"
                    break
        
        if bars_to_resolution == 0:
            # No se alcanzó SL/TP en max_lookahead velas
            bars_to_resolution = max_lookahead
            resolved_by = "timeout"
        
        trades.append({
            "entry_time": df.index[i],
            "direction": direction,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "sl_atr": 1.5,
            "tp_atr": 1.8,
            "result": trade_result,  # Resultado REAL (con edge)
            "resolved_by": resolved_by,
            "bars_to_resolution": bars_to_resolution,
            "volume_delta": vol_delta,
            "vol_favorable": vol_favorable,
            "micro_trend": current["micro_trend"],
            "atr_entry": current_atr,
            "mae_atr": max_adverse,  # MAE en unidades de ATR
            "mfe_atr": max_favorable,  # MFE en unidades de ATR
            "mae_pct": max_adverse * current_atr / entry_price * 100,
            "mfe_pct": max_favorable * current_atr / entry_price * 100,
        })
    
    trades_df = pd.DataFrame(trades)
    
    if len(trades_df) > 0:
        n_wins = (trades_df["result"] == "WIN").sum()
        n_losses = (trades_df["result"] == "LOSS").sum()
        win_rate = n_wins / len(trades_df) * 100
        logger.info(f"   ✅ {len(trades_df)} trades simulados (Sniper + Volumen)")
        logger.info(f"   📊 WR REAL: {win_rate:.1f}% ({n_wins}W / {n_losses}L)")
        logger.info(f"   📊 MAE medio (wins): {trades_df[trades_df['result']=='WIN']['mae_atr'].mean():.3f} ATR")
        logger.info(f"   📊 MAE medio (losses): {trades_df[trades_df['result']=='LOSS']['mae_atr'].mean():.3f} ATR")
        logger.info(f"   📊 Resolución: TP={sum(trades_df['resolved_by']=='TP')}, "
                    f"SL={sum(trades_df['resolved_by']=='SL')}, "
                    f"timeout={sum(trades_df['resolved_by']=='timeout')}")
    
    return trades_df


def analyze_mae_mfe(trades_df: pd.DataFrame) -> dict:
    """
    Analiza las distribuciones de MAE y MFE para encontrar el SL óptimo.
    """
    logger.info("🔬 Analizando MAE/MFE...")
    
    wins = trades_df[trades_df["result"] == "WIN"]
    losses = trades_df[trades_df["result"] == "LOSS"]
    
    # --- MAE Analysis (para optimizar SL) ---
    mae_wins = wins["mae_atr"].dropna()
    mae_losses = losses["mae_atr"].dropna()
    
    # Percentiles del MAE en trades ganadores
    # El SL óptimo está en el percentil 95-99 del MAE de ganadores
    mae_percentiles = {
        "p50": mae_wins.quantile(0.50),
        "p75": mae_wins.quantile(0.75),
        "p90": mae_wins.quantile(0.90),
        "p95": mae_wins.quantile(0.95),
        "p99": mae_wins.quantile(0.99),
        "max": mae_wins.max(),
    }
    
    # Para cada posible SL (en ATRs), calcular:
    # - Win Rate resultante
    # - Pérdidas evitadas vs pérdidas causadas
    sl_candidates = np.arange(0.1, 2.0, 0.1)
    sl_analysis = []
    
    for sl_atr in sl_candidates:
        # Trades que habrían sido detenidos por este SL
        stopped_by_sl = trades_df[trades_df["mae_atr"] >= sl_atr]
        
        # De esos, cuántos eran ganadores (falsos stops) y perdedores (correctos)
        wins_stopped = (stopped_by_sl["result"] == "WIN").sum()
        losses_stopped = (stopped_by_sl["result"] == "LOSS").sum()
        
        # Win Rate si usamos este SL
        trades_survived = trades_df[trades_df["mae_atr"] < sl_atr]
        wr_with_sl = (trades_survived["result"] == "WIN").mean() * 100 if len(trades_survived) > 0 else 0
        
        # Riesgo por trade con este SL
        risk_per_trade_pct = sl_atr * trades_df["atr_entry"].mean() / trades_df["entry_price"].mean() * 100
        
        sl_analysis.append({
            "sl_atr": sl_atr,
            "wr_resultante": wr_with_sl,
            "wins_stopped": int(wins_stopped),
            "losses_stopped": int(losses_stopped),
            "total_stopped": int(wins_stopped + losses_stopped),
            "pct_wins_stopped": wins_stopped / len(wins) * 100 if len(wins) > 0 else 0,
            "pct_losses_stopped": losses_stopped / len(losses) * 100 if len(losses) > 0 else 0,
            "risk_per_trade_pct": risk_per_trade_pct,
        })
    
    sl_df = pd.DataFrame(sl_analysis)
    
    # Encontrar el SL óptimo: maximizar WR minimizando wins_stopped
    # Score = WR_resultante - 2 * pct_wins_stopped (penalizamos falsos stops)
    sl_df["score"] = sl_df["wr_resultante"] - 2 * sl_df["pct_wins_stopped"]
    best_sl = sl_df.loc[sl_df["score"].idxmax()]
    
    # --- MFE Analysis ---
    mfe_wins = wins["mfe_atr"].dropna()
    mfe_losses = losses["mfe_atr"].dropna()
    
    # --- Distribución completa ---
    results = {
        "n_total": len(trades_df),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "wr_global": len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0,
        
        # MAE stats
        "mae_wins_mean": mae_wins.mean(),
        "mae_wins_std": mae_wins.std(),
        "mae_losses_mean": mae_losses.mean(),
        "mae_losses_std": mae_losses.std(),
        "mae_percentiles": mae_percentiles,
        
        # MFE stats
        "mfe_wins_mean": mfe_wins.mean(),
        "mfe_wins_std": mfe_wins.std(),
        "mfe_losses_mean": mfe_losses.mean(),
        "mfe_losses_std": mfe_losses.std(),
        
        # SL óptimo
        "best_sl_atr": best_sl["sl_atr"],
        "best_sl_wr": best_sl["wr_resultante"],
        "best_sl_wins_stopped_pct": best_sl["pct_wins_stopped"],
        "best_sl_losses_stopped_pct": best_sl["pct_losses_stopped"],
        "best_sl_risk_pct": best_sl["risk_per_trade_pct"],
        
        # Análisis completo de SL
        "sl_analysis": sl_df.to_dict("records"),
    }
    
    return results


def print_verdict(results: dict):
    """Imprime el veredicto del experimento."""
    
    print("\n" + "=" * 70)
    print("📊 EXP-005: ADVERSE EXCURSION PROFILING — VEREDICTO")
    print("=" * 70)
    
    print(f"\n📈 ESTADÍSTICAS GLOBALES:")
    print(f"   Total trades:     {results['n_total']}")
    print(f"   Win Rate global:  {results['wr_global']:.1f}%")
    print(f"   Trades ganadores: {results['n_wins']}")
    print(f"   Trades perdedores: {results['n_losses']}")
    
    print(f"\n📊 DISTRIBUCIÓN DE MAE (Maximum Adverse Excursion):")
    print(f"   MAE medio en WINS:   {results['mae_wins_mean']:.3f} ATR")
    print(f"   MAE medio en LOSSES: {results['mae_losses_mean']:.3f} ATR")
    print(f"\n   Percentiles del MAE en trades GANADORES:")
    print(f"   P50 (mediana):  {results['mae_percentiles']['p50']:.3f} ATR")
    print(f"   P75:            {results['mae_percentiles']['p75']:.3f} ATR")
    print(f"   P90:            {results['mae_percentiles']['p90']:.3f} ATR")
    print(f"   P95:            {results['mae_percentiles']['p95']:.3f} ATR")
    print(f"   P99:            {results['mae_percentiles']['p99']:.3f} ATR")
    print(f"   Máximo:         {results['mae_percentiles']['max']:.3f} ATR")
    
    print(f"\n📊 DISTRIBUCIÓN DE MFE (Maximum Favorable Excursion):")
    print(f"   MFE medio en WINS:   {results['mfe_wins_mean']:.3f} ATR")
    print(f"   MFE medio en LOSSES: {results['mfe_losses_mean']:.3f} ATR")
    
    print(f"\n🎯 SL ÓPTIMO ENCONTRADO:")
    print(f"   SL recomendado:       {results['best_sl_atr']:.1f}x ATR")
    print(f"   WR con este SL:       {results['best_sl_wr']:.1f}%")
    print(f"   Ganancias detenidas:  {results['best_sl_wins_stopped_pct']:.1f}%")
    print(f"   Pérdidas detenidas:   {results['best_sl_losses_stopped_pct']:.1f}%")
    print(f"   Riesgo por trade:     {results['best_sl_risk_pct']:.3f}%")
    
    # Comparación con SL actual (1.5 ATR)
    current_risk = 1.5 * 0.001 / 1.16 * 100  # Aprox
    new_risk = results['best_sl_risk_pct']
    risk_reduction = (1 - new_risk / current_risk) * 100 if current_risk > 0 else 0
    
    print(f"\n💡 IMPACTO EN LA GESTIÓN DE RIESGO:")
    print(f"   Riesgo actual (1.5 ATR): ~{current_risk:.3f}% por trade")
    print(f"   Riesgo nuevo ({results['best_sl_atr']:.1f} ATR): {new_risk:.3f}% por trade")
    print(f"   Reducción de riesgo: {risk_reduction:.1f}%")
    
    if risk_reduction > 20:
        print(f"   🚀 ¡Podríamos aumentar el tamaño de posición en {100/(100-risk_reduction)*100-100:.0f}%!")
    
    print("\n" + "=" * 70)
    print("🔬 VEREDICTO FINAL:")
    
    if results['best_sl_atr'] < 1.0:
        print(f"   ✅ SL MÁS AJUSTADO RECOMENDADO: {results['best_sl_atr']:.1f}x ATR")
        print(f"   El 95% de los trades ganadores nunca superan")
        print(f"   {results['mae_percentiles']['p95']:.3f} ATR de excursión adversa.")
        print(f"   Podemos reducir el SL de 1.5x a {results['best_sl_atr']:.1f}x ATR")
        print(f"   y mantener el {results['best_sl_wr']:.1f}% de Win Rate.")
    elif results['best_sl_atr'] < 1.5:
        print(f"   ⚠️ SL MODERADAMENTE MÁS AJUSTADO: {results['best_sl_atr']:.1f}x ATR")
        print(f"   Hay espacio para reducir el riesgo, pero no drásticamente.")
    else:
        print(f"   ❌ El SL actual de 1.5x ATR parece adecuado.")
        print(f"   No se encontró oportunidad de reducirlo sin perder ganancias.")
    
    print("=" * 70)


def plot_results(trades_df: pd.DataFrame, results: dict):
    """Genera visualizaciones del experimento."""
    
    os.makedirs(PLOTS_DIR, exist_ok=True)
    
    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    fig.suptitle(
        "EXP-005: Adverse Excursion Profiling — Optimización de SL/TP\n"
        f"WR Global: {results['wr_global']:.1f}% | "
        f"SL Óptimo: {results['best_sl_atr']:.1f}x ATR | "
        f"MAE P95 (Wins): {results['mae_percentiles']['p95']:.3f} ATR",
        fontsize=14,
        fontweight="bold",
    )
    
    wins = trades_df[trades_df["result"] == "WIN"]
    losses = trades_df[trades_df["result"] == "LOSS"]
    
    # 1. Distribución de MAE (Wins vs Losses)
    ax1 = axes[0, 0]
    ax1.hist(wins["mae_atr"], bins=30, alpha=0.6, color="#2ecc71",
             label=f"WINS (n={len(wins)})", density=True)
    ax1.hist(losses["mae_atr"], bins=30, alpha=0.6, color="#e74c3c",
             label=f"LOSSES (n={len(losses)})", density=True)
    ax1.axvline(results['mae_percentiles']['p95'], color="blue", linestyle="--",
                linewidth=2, label=f"P95 Wins: {results['mae_percentiles']['p95']:.2f} ATR")
    ax1.axvline(results['best_sl_atr'], color="red", linestyle="-",
                linewidth=2, label=f"SL Óptimo: {results['best_sl_atr']:.1f}x ATR")
    ax1.set_title("Distribución de MAE\n(Max Adverse Excursion)", fontsize=12, fontweight="bold")
    ax1.set_xlabel("MAE (en ATRs)")
    ax1.set_ylabel("Densidad")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.15)
    
    # 2. Distribución de MFE
    ax2 = axes[0, 1]
    ax2.hist(wins["mfe_atr"], bins=30, alpha=0.6, color="#2ecc71",
             label=f"WINS (n={len(wins)})", density=True)
    ax2.hist(losses["mfe_atr"], bins=30, alpha=0.6, color="#e74c3c",
             label=f"LOSSES (n={len(losses)})", density=True)
    ax2.set_title("Distribución de MFE\n(Max Favorable Excursion)", fontsize=12, fontweight="bold")
    ax2.set_xlabel("MFE (en ATRs)")
    ax2.set_ylabel("Densidad")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.15)
    
    # 3. MAE vs MFE Scatter
    ax3 = axes[0, 2]
    ax3.scatter(wins["mae_atr"], wins["mfe_atr"], alpha=0.3, s=10, c="#2ecc71", label="WINS")
    ax3.scatter(losses["mae_atr"], losses["mfe_atr"], alpha=0.3, s=10, c="#e74c3c", label="LOSSES")
    ax3.axhline(results['best_sl_atr'], color="red", linestyle="--", alpha=0.5)
    ax3.axvline(results['best_sl_atr'], color="red", linestyle="--", alpha=0.5)
    ax3.set_title("MAE vs MFE por Trade", fontsize=12, fontweight="bold")
    ax3.set_xlabel("MAE (ATRs)")
    ax3.set_ylabel("MFE (ATRs)")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.15)
    
    # 4. Análisis de SL candidatos
    ax4 = axes[1, 0]
    sl_df = pd.DataFrame(results['sl_analysis'])
    ax4.plot(sl_df["sl_atr"], sl_df["wr_resultante"], "b-", linewidth=2, label="WR Resultante")
    ax4.plot(sl_df["sl_atr"], sl_df["pct_wins_stopped"], "g--", linewidth=2, label="% Ganancias Detenidas")
    ax4.plot(sl_df["sl_atr"], sl_df["pct_losses_stopped"], "r--", linewidth=2, label="% Pérdidas Detenidas")
    ax4.axvline(results['best_sl_atr'], color="red", linestyle=":", linewidth=2,
                label=f"SL Óptimo: {results['best_sl_atr']:.1f}x")
    ax4.set_title("Análisis de SL Candidatos", fontsize=12, fontweight="bold")
    ax4.set_xlabel("SL (en ATRs)")
    ax4.set_ylabel("Porcentaje (%)")
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.15)
    
    # 5. Score de SL
    ax5 = axes[1, 1]
    ax5.plot(sl_df["sl_atr"], sl_df["score"], "purple", linewidth=2, marker="o", markersize=4)
    ax5.axvline(results['best_sl_atr'], color="red", linestyle=":", linewidth=2)
    ax5.set_title("Score de SL (WR - 2×FalsosStops)", fontsize=12, fontweight="bold")
    ax5.set_xlabel("SL (en ATRs)")
    ax5.set_ylabel("Score")
    ax5.grid(True, alpha=0.15)
    
    # 6. Boxplot MAE por resultado
    ax6 = axes[1, 2]
    mae_data = [wins["mae_atr"].dropna(), losses["mae_atr"].dropna()]
    bp = ax6.boxplot(mae_data, labels=["WINS", "LOSSES"], patch_artist=True)
    bp["boxes"][0].set_facecolor("#2ecc71")
    bp["boxes"][1].set_facecolor("#e74c3c")
    ax6.set_title("Boxplot de MAE por Resultado", fontsize=12, fontweight="bold")
    ax6.set_ylabel("MAE (ATRs)")
    ax6.grid(True, alpha=0.15, axis="y")
    
    plt.tight_layout()
    plot_path = PLOTS_DIR / "exp_005_adverse_excursion.png"
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    logger.info(f"🖼️ Gráfico guardado: {plot_path}")
    plt.close()


def run_experiment():
    """Ejecuta el experimento completo EXP-005."""
    logger.info("=" * 70)
    logger.info("🔬 EXP-005: ADVERSE EXCURSION PROFILING")
    logger.info("=" * 70)
    
    # Generar datos sintéticos
    syn_df = generate_synthetic_market_data(n_candles=5000, sniper_wr=0.85)
    
    # Simular trades con MAE/MFE (Sniper System real con filtro de volumen)
    trades_df = simulate_sniper_trades_with_mae_mfe(syn_df)
    
    if len(trades_df) < 30:
        logger.error(f"❌ Muestra insuficiente: {len(trades_df)} trades")
        return {"error": "Muestras insuficientes"}
    
    # Analizar MAE/MFE
    results = analyze_mae_mfe(trades_df)
    
    # Imprimir veredicto
    print_verdict(results)
    
    # Visualizar
    try:
        plot_results(trades_df, results)
    except Exception as e:
        logger.warning(f"⚠️ No se pudo generar el gráfico: {e}")
    
    # Guardar resultados
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    flat_results = {k: v for k, v in results.items() if k != "sl_analysis"}
    flat_results["sl_analysis"] = str(results.get("sl_analysis", []))
    pd.DataFrame([flat_results]).to_csv(RESULTS_DIR / "exp_005_results.csv", index=False)
    
    trades_df.to_csv(RESULTS_DIR / "exp_005_trades.csv", index=False)
    logger.info(f"📁 Resultados guardados en {RESULTS_DIR}")
    
    return results


# ──────────────────────────────────────────────
# EJECUCIÓN DIRECTA
# ──────────────────────────────────────────────

if __name__ == "__main__":
    results = run_experiment()
    
    if "error" not in results:
        print("\n" + "=" * 70)
        print("📋 RESUMEN RÁPIDO EXP-005")
        print("=" * 70)
        print(f"   Total trades:          {results['n_total']}")
        print(f"   Win Rate global:       {results['wr_global']:.1f}%")
        print(f"   MAE medio (Wins):      {results['mae_wins_mean']:.3f} ATR")
        print(f"   MAE P95 (Wins):        {results['mae_percentiles']['p95']:.3f} ATR")
        print(f"   MAE P99 (Wins):        {results['mae_percentiles']['p99']:.3f} ATR")
        print(f"   SL óptimo:             {results['best_sl_atr']:.1f}x ATR")
        print(f"   WR con SL óptimo:      {results['best_sl_wr']:.1f}%")
        print(f"   Riesgo por trade:      {results['best_sl_risk_pct']:.3f}%")
        print(f"   Reducción de riesgo:   {(1 - results['best_sl_risk_pct']/(1.5*0.001/1.16*100))*100:.1f}%")
        print("=" * 70)
