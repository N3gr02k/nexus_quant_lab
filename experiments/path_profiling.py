"""
NEXUS QUANT LAB — Experimento 1
================================
path_profiling.py

EXP-001: Path-Profiling (La Ciencia del Rechazo)

Hipótesis:
  La velocidad con la que el precio sale de un Muro HTF predice
  la duración de la reversión.

  Si |rejection_speed| > 3σ → señal de reversión casi certeza física.

Feature clave:
  rejection_speed: Z-score de velocidad de tick (ventana 24H).
  No mide pips, mide desviaciones estándar.

Pipeline:
  1. Carga datos del Lab generados por tick_collector.py
  2. Define el Target: retorno futuro a 3 horas (future_return_3h)
  3. Filtra eventos de alta velocidad (|Z| > 2.0)
  4. Calcula correlación Pearson entre rejection_speed y retorno futuro
  5. Visualiza el Edge con scatter plot + regresión
  6. Veredicto estadístico: ¿Los eventos de alta velocidad se mueven más?

Dependencias:
  pip install pandas numpy matplotlib seaborn scipy

Uso:
  python experiments/path_profiling.py
  python experiments/path_profiling.py --file data/eurusd_lab_data.csv
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
import os
import logging
from pathlib import Path

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Directorio de plots
PLOTS_DIR = Path(__file__).parent.parent / "notebook_research" / "plots"


def analyze_rejection_edge(file_path: str) -> dict:
    """
    Analiza el Edge predictivo de rejection_speed sobre retornos futuros.

    Args:
        file_path: Ruta al CSV generado por tick_collector.full_pipeline()

    Returns:
        Dict con métricas del experimento:
            - n_samples: número de velas H1 analizadas
            - n_high_speed: eventos con |Z| > 2.0
            - correlation: correlación Pearson
            - p_value: significancia estadística
            - edge_pct: % de movimiento extra en alta velocidad
            - verdict: "ÉXITO" o "FALLO"
    """
    logger.info("=" * 60)
    logger.info("🔬 EXP-001: PATH-PROFILING (La Ciencia del Rechazo)")
    logger.info(f"   Archivo: {file_path}")
    logger.info("=" * 60)

    # ─── 1. Cargar datos del Lab ───
    logger.info("📂 Cargando datos del Laboratorio...")
    df = pd.read_csv(file_path, index_col="time", parse_dates=True)
    logger.info(f"   ✅ {len(df):,} velas H1 cargadas")
    logger.info(f"   📅 Período: {df.index.min()} → {df.index.max()}")

    # ─── 2. Definir el Target (Outcome) ───
    # Retorno porcentual en las siguientes 3 velas H1
    # Si rejection_speed es alto y el precio se mueve → hay Edge
    df["future_return_3h"] = df["close"].shift(-3) / df["close"] - 1

    # ─── 3. Filtrar eventos de Alta Velocidad ───
    high_speed_mask = df["rejection_speed"].abs() > 2.0
    high_speed_events = df[high_speed_mask].copy()
    n_high_speed = len(high_speed_events)
    logger.info(f"⚡ Eventos de alta velocidad (|Z| > 2.0): {n_high_speed:,}")

    # ─── 4. Análisis de Correlación ───
    valid = df[["rejection_speed", "future_return_3h"]].dropna()
    correlation, p_value = stats.pearsonr(
        valid["rejection_speed"], valid["future_return_3h"]
    )
    logger.info(f"📈 Correlación Velocidad vs Retorno 3h: {correlation:.4f}")
    logger.info(f"   p-value: {p_value:.6f} {'⭐' if p_value < 0.05 else ''}")

    # ─── 5. Visualización del Edge ───
    os.makedirs(PLOTS_DIR, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # Panel 1: Scatter plot con regresión
    ax1 = axes[0]
    sns.regplot(
        x="rejection_speed",
        y="future_return_3h",
        data=df,
        scatter_kws={"alpha": 0.3, "color": "gray", "s": 10},
        line_kws={"color": "gold", "linewidth": 2},
        ax=ax1,
    )
    ax1.axvline(2.0, color="red", linestyle="--", alpha=0.7, label="Z = +2σ")
    ax1.axvline(-2.0, color="red", linestyle="--", alpha=0.7, label="Z = -2σ")
    ax1.axvline(3.0, color="darkred", linestyle="--", alpha=0.9, label="Z = +3σ")
    ax1.axvline(-3.0, color="darkred", linestyle="--", alpha=0.9, label="Z = -3σ")
    ax1.set_title(
        "EXP-001: Velocidad de Rechazo vs Retorno Futuro (3h)\n"
        f"Correlación: {correlation:.4f} (p={p_value:.4f})",
        fontsize=12,
        fontweight="bold",
    )
    ax1.set_xlabel("Rejection Speed (Z-Score)")
    ax1.set_ylabel("Retorno Futuro 3h (%)")
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=0.15)

    # Panel 2: Boxplot comparativo
    ax2 = axes[1]
    df["speed_band"] = pd.cut(
        df["rejection_speed"],
        bins=[-np.inf, -3, -2, 2, 3, np.inf],
        labels=["< -3σ", "-3σ a -2σ", "Normal", "+2σ a +3σ", "> +3σ"],
    )
    band_stats = df.groupby("speed_band", observed=True)["future_return_3h"].agg(
        ["mean", "std", "count"]
    )
    band_stats["mean"].plot(
        kind="bar",
        ax=ax2,
        color=["darkred", "red", "gray", "green", "darkgreen"],
        edgecolor="black",
        alpha=0.8,
    )
    ax2.set_title(
        "Retorno Promedio por Banda de Velocidad\n"
        f"(n={len(valid):,} velas H1)",
        fontsize=12,
        fontweight="bold",
    )
    ax2.set_xlabel("Banda de Rejection Speed")
    ax2.set_ylabel("Retorno Promedio 3h (%)")
    ax2.axhline(0, color="black", linewidth=0.5)
    ax2.grid(True, alpha=0.15, axis="y")

    plt.tight_layout()
    plot_path = PLOTS_DIR / "exp_001_rejection_edge.png"
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    logger.info(f"🖼️ Gráfico guardado: {plot_path}")
    plt.close()

    # ─── 6. Veredicto Estadístico ───
    normal_mask = df["rejection_speed"].abs() <= 2.0
    avg_return_high_speed = high_speed_events["future_return_3h"].abs().mean()
    avg_return_normal = df[normal_mask]["future_return_3h"].abs().mean()

    if avg_return_normal > 0:
        edge_pct = (avg_return_high_speed / avg_return_normal - 1) * 100
    else:
        edge_pct = 0.0

    # Determinar veredicto
    if p_value < 0.05 and abs(correlation) > 0.1:
        verdict = "✅ ÉXITO"
        verdict_detail = (
            "La velocidad de tick es un predictor estadísticamente significativo "
            "del retorno futuro."
        )
    elif p_value < 0.05:
        verdict = "⚠️ DÉBIL"
        verdict_detail = (
            "Hay significancia estadística pero la correlación es muy baja "
            "para ser útil en trading."
        )
    else:
        verdict = "❌ FALLO"
        verdict_detail = (
            "No se encontró relación significativa entre la velocidad de tick "
            "y el retorno futuro. La hipótesis no se sostiene."
        )

    print("\n" + "=" * 60)
    print("📊 VEREDICTO DEL EXPERIMENTO")
    print("=" * 60)
    print(f"   Muestras analizadas:     {len(valid):,}")
    print(f"   Eventos alta velocidad:  {n_high_speed:,}")
    print(f"   Correlación:             {correlation:.4f}")
    print(f"   p-value:                 {p_value:.6f}")
    print(f"   Edge (% extra mov.):     {edge_pct:+.2f}%")
    print(f"   Veredicto:               {verdict}")
    print(f"   {verdict_detail}")
    print("=" * 60)

    return {
        "n_samples": len(valid),
        "n_high_speed": n_high_speed,
        "correlation": correlation,
        "p_value": p_value,
        "edge_pct": edge_pct,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
    }


# ──────────────────────────────────────────────
# EJECUCIÓN DIRECTA
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="NEXUS QUANT LAB — EXP-001: Path-Profiling"
    )
    parser.add_argument(
        "--file",
        type=str,
        default="data/eurusd_lab_data.csv",
        help="Ruta al CSV generado por tick_collector.py",
    )
    parser.add_argument(
        "--collect-first",
        action="store_true",
        help="Ejecutar tick_collector antes del análisis",
    )

    args = parser.parse_args()

    # Opción: recolectar datos primero
    if args.collect_first:
        logger.info("🔄 Ejecutando recolección de datos primero...")
        from data_factory.tick_collector import TickCollector

        for symbol in ["EURUSD", "GOLD"]:
            collector = TickCollector(symbol)
            df = collector.full_pipeline("2026-05-01")
            if df is not None:
                collector.export_data(df, f"{symbol.lower()}_lab_data.csv")
            collector.disconnect()

    # Ejecutar análisis
    if os.path.exists(args.file):
        results = analyze_rejection_edge(args.file)
    else:
        print(f"❌ No se encuentra el archivo {args.file}")
        print(f"\n💡 Ejecuta primero el tick_collector.py:")
        print(f"   python data_factory/tick_collector.py --symbol EURUSD --from-date 2026-05-01")
        print(f"\n   O usa el flag --collect-first para hacer ambos:")
        print(f"   python experiments/path_profiling.py --collect-first")
