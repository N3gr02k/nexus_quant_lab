"""
NEXUS QUANT LAB — Experimento 2: Cross-Asset Correlation
==========================================================
EXP-002: Divergencia Oro/Euro

Hipótesis:
  El mercado es un ecosistema. El Dólar es el centro.
  Si el Oro (activo refugio) empieza a caer con fuerza, suele ser
  porque el Dólar se está fortaleciendo. A veces, esta fuerza se ve
  en el Oro segundos antes que en el Euro.

Método:
  Comparar los movimientos de EURUSD y GOLD usando datos H1
  generados por tick_collector.py. Calcular correlación con lag
  (desplazamiento temporal) para detectar qué activo lidera.

Feature clave:
  rolling_corr: Correlación rodante entre retornos de ambos activos.
  best_lag:     Lag óptimo que maximiza la correlación absoluta.

Dependencias:
  pip install pandas numpy matplotlib
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
from pathlib import Path


def analyze_cross_asset_lead(symbol_a_path: str, symbol_b_path: str):
    """
    Analiza la relación de liderazgo entre dos activos.

    Args:
        symbol_a_path: Ruta al CSV del activo primario (ej: EURUSD)
        symbol_b_path: Ruta al CSV del activo secundario (ej: GOLD)
    """
    print("=" * 60)
    print("🔬 EXP-002: Cross-Asset Correlation (Divergencia Oro/Euro)")
    print("=" * 60)

    # ──────────────────────────────────────────────
    # 1. Cargar datos de ambos activos
    # ──────────────────────────────────────────────
    print(f"\n📂 Cargando datos...")
    print(f"   Activo A: {symbol_a_path}")
    print(f"   Activo B: {symbol_b_path}")

    df_a = pd.read_csv(symbol_a_path, index_col="time", parse_dates=True)
    df_b = pd.read_csv(symbol_b_path, index_col="time", parse_dates=True)

    print(f"   ✅ {len(df_a):,} velas H1 cargadas para Activo A")
    print(f"   ✅ {len(df_b):,} velas H1 cargadas para Activo B")

    # ──────────────────────────────────────────────
    # 2. Sincronizar por tiempo y calcular retornos
    # ──────────────────────────────────────────────
    print(f"\n🔄 Sincronizando series temporales...")

    df = pd.DataFrame(index=df_a.index)
    df["ret_eur"] = df_a["close"].pct_change()
    df["ret_gold"] = df_b["close"].pct_change()

    # Eliminar NaN del primer valor
    df = df.dropna()

    print(f"   ✅ {len(df):,} observaciones sincronizadas")

    # ──────────────────────────────────────────────
    # 3. Calcular Correlación Base
    # ──────────────────────────────────────────────
    base_corr = df["ret_eur"].corr(df["ret_gold"])
    print(f"\n📊 Correlación base (Pearson): {base_corr:.4f}")

    # ──────────────────────────────────────────────
    # 4. Correlación Rodante (Ventana de 24h)
    # ──────────────────────────────────────────────
    print(f"\n📈 Calculando correlación rodante (ventana 24H)...")
    df["rolling_corr"] = (
        df["ret_eur"].rolling(window=24).corr(df["ret_gold"])
    )

    # ──────────────────────────────────────────────
    # 5. BUSCAR EL "ALFA": ¿Quién lidera a quién?
    # ──────────────────────────────────────────────
    # Calculamos la correlación con lag (desplazamiento)
    # Lag positivo → GOLD lidera (GOLD se mueve antes)
    # Lag negativo → EURUSD lidera (EURUSD se mueve antes)
    print(f"\n🔍 Buscando el Lag óptimo (¿quién lidera?)...")

    lags = range(-5, 6)  # de -5 horas a +5 horas
    corrs = [df["ret_eur"].corr(df["ret_gold"].shift(l)) for l in lags]

    best_lag = list(lags)[np.argmax(np.abs(corrs))]
    best_corr = max(corrs, key=abs)

    print(f"\n{'='*60}")
    print(f"🚀 RESULTADO: El mejor Lag es de {best_lag} horas")
    print(f"   Correlación en ese lag: {best_corr:.4f}")
    print(f"   Correlación base (lag 0): {base_corr:.4f}")
    print(f"   Mejora: {(best_corr - base_corr) * 100:.2f}%")
    print(f"{'='*60}")

    # ──────────────────────────────────────────────
    # 6. Veredicto
    # ──────────────────────────────────────────────
    print(f"\n💡 VEREDICTO:")
    if best_lag > 0:
        print(f"   ✅ El ORO tiende a LIDERAR al EURO por {best_lag} hora(s).")
        print(f"   📌 Implicación: Antes de operar EURUSD, revisa qué hizo GOLD hace {best_lag}h.")
    elif best_lag < 0:
        print(f"   ✅ El EURO tiende a LIDERAR al ORO por {abs(best_lag)} hora(s).")
        print(f"   📌 Implicación: El Euro es el indicador adelantado del Oro.")
    else:
        print(f"   ✅ Ambos activos se mueven en perfecta sincronía (lag 0).")
        print(f"   📌 Implicación: No hay ventaja temporal entre ellos.")

    # ──────────────────────────────────────────────
    # 7. Mostrar tabla de correlaciones por lag
    # ──────────────────────────────────────────────
    print(f"\n📋 Tabla de correlaciones por lag:")
    print(f"   {'Lag (h)':<10} {'Correlación':<15} {'|Corr|':<15}")
    print(f"   {'-'*40}")
    for lag, corr in zip(lags, corrs):
        marker = " ◄ MÁXIMO" if lag == best_lag else ""
        print(f"   {lag:<10} {corr:<15.4f} {abs(corr):<15.4f}{marker}")

    # ──────────────────────────────────────────────
    # 8. Visualización
    # ──────────────────────────────────────────────
    print(f"\n📸 Generando visualización...")

    fig, axes = plt.subplots(3, 1, figsize=(14, 12))
    fig.suptitle(
        "EXP-002: Cross-Asset Correlation — EURUSD vs GOLD",
        fontsize=14,
        fontweight="bold",
    )

    # 8a. Precios normalizados
    ax1 = axes[0]
    norm_eur = df_a["close"] / df_a["close"].iloc[0] * 100
    norm_gold = df_b["close"] / df_b["close"].iloc[0] * 100

    ax1.plot(df_a.index, norm_eur, color="blue", alpha=0.7, label="EURUSD", linewidth=0.8)
    ax1.plot(df_b.index, norm_gold, color="gold", alpha=0.7, label="GOLD (XAUUSD)", linewidth=0.8)
    ax1.set_title("Precios Normalizados (Base 100)")
    ax1.set_ylabel("Precio Normalizado")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 8b. Correlación rodante
    ax2 = axes[1]
    ax2.plot(df.index, df["rolling_corr"], color="cyan", linewidth=0.8, label="Correlación EUR/GOLD (24H)")
    ax2.axhline(y=0.7, color="red", linestyle="--", alpha=0.5, label="Alta Correlación (+0.7)")
    ax2.axhline(y=-0.7, color="red", linestyle="--", alpha=0.5, label="Alta Correlación (-0.7)")
    ax2.axhline(y=0, color="gray", linestyle="-", alpha=0.3)
    ax2.set_title("Correlación Rodante (Ventana 24H)")
    ax2.set_ylabel("Correlación de Pearson")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 8c. Correlación por lag
    ax3 = axes[2]
    colors = ["red" if l == best_lag else "steelblue" for l in lags]
    ax3.bar(lags, corrs, color=colors, alpha=0.7, edgecolor="black", linewidth=0.5)
    ax3.axhline(y=base_corr, color="green", linestyle="--", alpha=0.7, label=f"Corr base (lag 0): {base_corr:.3f}")
    ax3.set_title("Correlación Cruzada con Lag (¿Quién lidera?)")
    ax3.set_xlabel("Lag (horas) — Positivo = GOLD lidera")
    ax3.set_ylabel("Correlación de Pearson")
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()

    # Guardar
    plots_dir = Path(__file__).parent.parent / "notebook_research" / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    save_path = plots_dir / "exp_002_cross_asset.png"
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    print(f"   ✅ Gráfico guardado: {save_path}")

    plt.close()

    # ──────────────────────────────────────────────
    # 9. Resumen final
    # ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"📋 RESUMEN EXP-002")
    print(f"{'='*60}")
    print(f"   Correlación base (lag 0):     {base_corr:.4f}")
    print(f"   Mejor lag:                    {best_lag}h")
    print(f"   Correlación en mejor lag:     {best_corr:.4f}")
    print(f"   Observaciones sincronizadas:  {len(df):,}")
    print(f"   Período:                      {df.index.min()} → {df.index.max()}")
    print(f"{'='*60}")

    return {
        "base_correlation": base_corr,
        "best_lag": best_lag,
        "best_correlation": best_corr,
        "lags": list(lags),
        "correlations": corrs,
        "observations": len(df),
    }


def collect_data(symbol: str, from_date: str) -> bool:
    """
    Recolecta datos para un símbolo usando tick_collector.py.

    Args:
        symbol: Símbolo (EURUSD, GOLD)
        from_date: Fecha inicio YYYY-MM-DD

    Returns:
        True si la recolección fue exitosa
    """
    import subprocess
    import sys

    output = f"{symbol.lower()}_lab_data.csv"
    print(f"\n📡 Recolectando datos para {symbol}...")

    result = subprocess.run(
        [
            sys.executable,
            "data_factory/tick_collector.py",
            "--symbol", symbol,
            "--from-date", from_date,
            "--output", output,
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    print(result.stdout)
    if result.stderr:
        print(f"⚠️ Stderr: {result.stderr}")

    return result.returncode == 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="EXP-002: Cross-Asset Correlation (Divergencia Oro/Euro)"
    )
    parser.add_argument(
        "--collect-first",
        action="store_true",
        help="Recolectar datos antes de analizar",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        default="2026-05-01",
        help="Fecha inicio para recolección (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--eur-path",
        type=str,
        default="data/eurusd_lab_data.csv",
        help="Ruta al CSV de EURUSD",
    )
    parser.add_argument(
        "--gold-path",
        type=str,
        default="data/gold_lab_data.csv",
        help="Ruta al CSV de GOLD",
    )

    args = parser.parse_args()

    # Recolectar datos si se solicita
    if args.collect_first:
        print("🔄 Modo recolección activado")
        success_eur = collect_data("EURUSD", args.from_date)
        success_gold = collect_data("GOLD", args.from_date)

        if not (success_eur and success_gold):
            print("\n❌ Error en la recolección de datos.")
            print("   Verifica la conexión con MT5.")
            exit(1)
        print("\n✅ Recolección completada. Procediendo al análisis...\n")

    # Verificar que los archivos existan
    eur_path = args.eur_path
    gold_path = args.gold_path

    if not os.path.exists(eur_path):
        print(f"❌ Archivo no encontrado: {eur_path}")
        print("   Ejecuta: python experiments/cross_asset.py --collect-first")
        exit(1)

    if not os.path.exists(gold_path):
        print(f"❌ Archivo no encontrado: {gold_path}")
        print("   Ejecuta: python experiments/cross_asset.py --collect-first")
        exit(1)

    # Ejecutar análisis
    results = analyze_cross_asset_lead(eur_path, gold_path)
