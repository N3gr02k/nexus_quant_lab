"""
NEXUS QUANT LAB — EXP-001: Path-Profiling
===========================================
¿La velocidad predice el éxito?

Hipótesis:
  Si rejection_speed > 2σ (velocidad extrema), la siguiente vela H1
  tendrá un rango significativamente mayor que el promedio.

Esto validaría que los rechazos en muros HTF generan explosividad.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
plt.style.use("seaborn-v0_8-darkgrid")
sns.set_palette("husl")
os.makedirs("notebook_research/plots", exist_ok=True)


def run_experiment_001(symbol: str):
    print(f"🔬 Ejecutando EXP-001 para {symbol}...")
    print("=" * 60)

    # Cargar datos
    df = pd.read_csv(
        f"data/{symbol.lower()}_lab_data.csv",
        index_col="time",
        parse_dates=True,
    )
    print(f"   Velas H1 cargadas: {len(df)}")
    print(f"   Período: {df.index.min()} → {df.index.max()}")

    # ─── 1. Definir éxito: Rango de la siguiente vela ───
    df["next_candle_range"] = (df["high"] - df["low"]).shift(-1)

    # ─── 2. Segmentar por Rejection Speed (Z-Score) ───
    df["is_fast"] = df["rejection_speed"].abs() > 2.0

    # Estadísticas
    n_fast = df["is_fast"].sum()
    n_normal = (~df["is_fast"]).sum()
    print(f"\n   Velocidad normal (|Z| ≤ 2): {n_normal} velas")
    print(f"   Velocidad extrema (|Z| > 2): {n_fast} velas ({n_fast/len(df)*100:.1f}%)")

    stats = df.groupby("is_fast")["next_candle_range"].agg(["mean", "std", "count"])
    print(f"\n📊 RESULTADOS ESTADÍSTICOS:")
    print(f"   {'Condición':<30} {'Media':>10} {'Std':>10} {'N':>6}")
    print(f"   {'─'*56}")
    for is_fast, row in stats.iterrows():
        label = "Velocidad Extrema (>2σ)" if is_fast else "Velocidad Normal"
        print(f"   {label:<30} {row['mean']:>10.5f} {row['std']:>10.5f} {int(row['count']):>6}")

    # Edge
    mean_normal = stats.loc[False, "mean"]
    if True in stats.index:
        mean_fast = stats.loc[True, "mean"]
        edge = (mean_fast / mean_normal - 1) * 100
        print(f"\n🚀 EDGE DETECTADO: {edge:+.2f}%")
        if edge > 20:
            print(f"   ✅ Conclusión: La velocidad extrema predice explosividad significativa.")
        elif edge > 10:
            print(f"   ⚠️ Conclusión: Tendencia positiva pero moderada.")
        else:
            print(f"   ❌ Conclusión: Sin edge significativo en esta muestra.")
    else:
        mean_fast = 0
        edge = 0
        print(f"\n⚠️ No hubo velas con velocidad extrema (>2σ) en esta muestra.")
        print(f"   Conclusión: El mercado estuvo en régimen de baja volatilidad.")

    # ─── 3. Visualización ───
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Boxplot
    sns.boxplot(
        x="is_fast",
        y="next_candle_range",
        data=df.dropna(),
        palette=["#6b7b8d", "#f0c040"],
        ax=axes[0],
    )
    axes[0].set_xticklabels(["Velocidad Normal\n(|Z| ≤ 2)", "Velocidad Extrema\n(|Z| > 2)"])
    axes[0].set_title(f"EXP-001: Rango siguiente vela vs Rejection Speed\n{symbol}", fontsize=12)
    axes[0].set_ylabel("Rango H/L de la siguiente vela")
    axes[0].grid(True, alpha=0.3)

    # Scatter: Rejection Speed vs Next Range
    axes[1].scatter(
        df["rejection_speed"],
        df["next_candle_range"],
        alpha=0.5,
        c=np.where(df["is_fast"], "#f0c040", "#6b7b8d"),
        s=30,
    )
    axes[1].axvline(-2, color="red", linestyle="--", alpha=0.5, label="|Z|=2")
    axes[1].axvline(2, color="red", linestyle="--", alpha=0.5)
    axes[1].set_title(f"Correlación: Rejection Speed → Rango siguiente vela\n{symbol}", fontsize=12)
    axes[1].set_xlabel("Rejection Speed (Z-score)")
    axes[1].set_ylabel("Rango H/L siguiente vela")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    path = f"notebook_research/plots/exp_001_{symbol.lower()}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n🖼️ Gráfico guardado: {path}")

    # ─── 4. Resumen para MEMORIA.md ───
    print("\n" + "=" * 60)
    print("📋 COPIA ESTO A MEMORIA.md:")
    print("=" * 60)
    print(f"""
### [EXP-001] Path-Profiling — RESULTADOS PILOTO ({symbol})
- **Muestras**: {len(df)} velas H1 ({n_fast} con velocidad extrema).
- **Rango normal**: {mean_normal:.5f}
- **Rango tras velocidad extrema**: {mean_fast:.5f}
- **Edge**: {edge:+.2f}%
- **Conclusión**: {'La velocidad de tick es un predictor significativo de explosividad.' if edge > 20 else 'El edge es marginal en esta muestra.'}
""")

    return edge


if __name__ == "__main__":
    run_experiment_001("EURUSD")
    print("\n" + "─" * 60)
    run_experiment_001("GOLD")
