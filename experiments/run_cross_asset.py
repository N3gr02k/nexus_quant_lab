"""
NEXUS QUANT LAB — EXP-002: Cross-Asset Lead
=============================================
¿El Oro es el profeta del Euro?

Hipótesis:
  El movimiento del Oro (GOLD) precede al del Euro (EURUSD) con un lag
  de 1-2 horas, debido a que el Oro reacciona primero a cambios en
  el sentimiento de riesgo global.

Si se confirma, podemos usar GOLD como leading indicator para EURUSD.
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


def run_experiment_002():
    print("🔬 Ejecutando EXP-002: Correlación con Lag EUR/GOLD...")
    print("=" * 60)

    # Cargar datos
    eur = pd.read_csv(
        "data/eurusd_lab_data.csv",
        index_col="time",
        parse_dates=True,
    )
    gold = pd.read_csv(
        "data/gold_lab_data.csv",
        index_col="time",
        parse_dates=True,
    )

    print(f"\n   EURUSD: {len(eur)} velas H1 ({eur.index.min()} → {eur.index.max()})")
    print(f"   GOLD:   {len(gold)} velas H1 ({gold.index.min()} → {gold.index.max()})")

    # ─── Sincronizar (Inner Join) ───
    # Solo horas donde ambos activos tengan datos
    df = pd.merge(
        eur[["close"]],
        gold[["close"]],
        left_index=True,
        right_index=True,
        suffixes=("_eur", "_gold"),
    )
    print(f"\n   Velas sincronizadas: {len(df)}")

    # ─── Calcular retornos ───
    df["ret_eur"] = df["close_eur"].pct_change()
    df["ret_gold"] = df["close_gold"].pct_change()

    # ─── Probar Lags (¿Gold de hace X horas predice EUR de ahora?) ───
    # Lag positivo = GOLD lidera (GOLD de hace N horas → EUR ahora)
    # Lag negativo = EUR lidera (EUR de hace N horas → GOLD ahora)
    # Lag 0 = sincrónico
    results = {}
    for lag in range(-5, 6):
        corr = df["ret_eur"].corr(df["ret_gold"].shift(lag))
        results[lag] = corr

    print("\n📊 TABLA DE CORRELACIÓN POR LAG:")
    print(f"   {'Lag':>5} {'Correlación':>12} {'Dirección':<25}")
    print(f"   {'─'*42}")
    for lag, corr in sorted(results.items()):
        if lag > 0:
            direction = "🚀 GOLD LIDERA"
        elif lag == 0:
            direction = "🐢 SINCRÓNICO"
        else:
            direction = "⬅️ EUR LIDERA"
        arrow = "↑" if corr > 0 else "↓"
        print(f"   {lag:>+3}h {arrow} {corr:>+10.4f}   {direction}")

    # Encontrar el lag con mayor correlación absoluta
    best_lag = max(results, key=lambda k: abs(results[k]))
    best_corr = results[best_lag]
    print(f"\n🏆 MEJOR LAG: {best_lag:+d}h (Correlación: {best_corr:+.4f})")

    if best_lag > 0:
        print(f"   → El Oro lidera al Euro por {best_lag} hora(s).")
        print(f"   → Podemos usar GOLD como leading indicator para EURUSD.")
    elif best_lag < 0:
        print(f"   → El Euro lidera al Oro por {abs(best_lag)} hora(s).")
        print(f"   → El sentimiento del Dólar se refleja primero en EURUSD.")
    else:
        print(f"   → Los activos se mueven sincrónicamente.")
        print(f"   → No hay relación leading/lagging clara.")

    # ─── Visualización ───
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Gráfico de barras de correlaciones
    lags = list(results.keys())
    corrs = list(results.values())
    colors = ["#2ecc71" if c > 0 else "#e74c3c" for c in corrs]
    axes[0].bar(lags, corrs, color=colors, alpha=0.7, edgecolor="black", linewidth=0.5)
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].axvline(0, color="blue", linestyle="--", alpha=0.5, label="Sincrónico")
    axes[0].set_title("EXP-002: Correlación Cruzada EURUSD vs GOLD", fontsize=12)
    axes[0].set_xlabel("Lag (horas) — Positivo = GOLD lidera")
    axes[0].set_ylabel("Correlación de Pearson")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Scatter del mejor lag
    best_col = f"ret_gold_lag{best_lag:+d}"
    df[best_col] = df["ret_gold"].shift(best_lag)
    axes[1].scatter(
        df[best_col].dropna(),
        df["ret_eur"].dropna(),
        alpha=0.5,
        c="#2ecc71" if best_corr > 0 else "#e74c3c",
        s=30,
    )
    # Línea de regresión
    clean = df[[best_col, "ret_eur"]].dropna()
    if len(clean) > 2:
        z = np.polyfit(clean[best_col], clean["ret_eur"], 1)
        p = np.poly1d(z)
        x_line = np.linspace(clean[best_col].min(), clean[best_col].max(), 100)
        axes[1].plot(x_line, p(x_line), "b--", alpha=0.7, linewidth=1.5)
    axes[1].set_title(
        f"Lag óptimo: {best_lag:+d}h (Corr: {best_corr:+.4f})\n"
        f"GOLD → EURUSD",
        fontsize=12,
    )
    axes[1].set_xlabel(f"Retorno GOLD (lag {best_lag:+d}h)")
    axes[1].set_ylabel("Retorno EURUSD")
    axes[1].axhline(0, color="gray", linestyle="-", alpha=0.3)
    axes[1].axvline(0, color="gray", linestyle="-", alpha=0.3)
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    path = "notebook_research/plots/exp_002_cross_asset.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n🖼️ Gráfico guardado: {path}")

    # ─── Resumen para MEMORIA.md ───
    print("\n" + "=" * 60)
    print("📋 COPIA ESTO A MEMORIA.md:")
    print("=" * 60)
    print(f"""
### [EXP-002] Cross-Asset — RESULTADOS PILOTO
- **Muestras sincronizadas**: {len(df)} velas H1.
- **Lag Ganador**: {best_lag:+d} horas.
- **Correlación Max**: {best_corr:+.4f}.
- **Conclusión**: {'El Oro (GOLD) lidera el movimiento del Euro (EURUSD).' if best_lag > 0 else 'El Euro (EURUSD) lidera al Oro (GOLD).' if best_lag < 0 else 'Los activos se mueven sincrónicamente.'}
""")

    return best_lag, best_corr


if __name__ == "__main__":
    run_experiment_002()
