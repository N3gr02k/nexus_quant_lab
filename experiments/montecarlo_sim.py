"""
NEXUS QUANT LAB — Experimento 3
=================================
montecarlo_sim.py

Hipótesis:
  ¿Tus ganancias de hoy son suerte o sistema?

Método:
  Tomar el archivo master_audit.csv con el histórico de trades.
  Desordenar los resultados 10,000 veces para crear miles de
  "curvas de equidad" posibles.

Resultado:
  Sabremos el "Riesgo de Ruina". Si el peor escenario de Montecarlo
  dice que pierdes el 15%, ajustaremos el Risk Engine antes de que
  pase en la realidad.

Dependencias:
  pip install pandas numpy matplotlib seaborn
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Optional, Tuple, List
import logging
import random

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class MontecarloSimulator:
    """
    Simulador de Montecarlo para validar la robustez de un sistema
    de trading mediante la generación de curvas de equidad sintéticas.
    """

    def __init__(self, audit_path: Optional[str] = None):
        """
        Args:
            audit_path: Ruta al archivo master_audit.csv
                        Si es None, busca en el directorio actual
        """
        self.audit_path = audit_path or self._find_audit_file()
        self.results_dir = Path(__file__).parent.parent / "notebook_research"
        self.results_dir.mkdir(exist_ok=True)

        # Datos cargados
        self.trades: Optional[pd.DataFrame] = None
        self.equity_curves: Optional[np.ndarray] = None

    def _find_audit_file(self) -> str:
        """Busca master_audit.csv en ubicaciones comunes."""
        search_paths = [
            Path.cwd() / "master_audit.csv",
            Path(__file__).parent.parent / "master_audit.csv",
            Path.home() / "Desktop" / "master_audit.csv",
            Path.home() / "Documents" / "master_audit.csv",
        ]

        for path in search_paths:
            if path.exists():
                logger.info(f"📁 Archivo audit encontrado: {path}")
                return str(path)

        logger.warning("⚠️ No se encontró master_audit.csv")
        return "master_audit.csv"

    def load_trades(self, filepath: Optional[str] = None) -> pd.DataFrame:
        """
        Carga el archivo de auditoría con los trades históricos.

        Args:
            filepath: Ruta al CSV (usa self.audit_path si no se especifica)

        Returns:
            DataFrame con columnas esperadas:
              - profit: Resultado del trade en pips o USD
              - symbol: Símbolo del activo
              - direction: "buy" o "sell"
              - entry_time: Fecha/hora de entrada
              - exit_time: Fecha/hora de salida
        """
        path = filepath or self.audit_path

        if not Path(path).exists():
            logger.error(f"❌ Archivo no encontrado: {path}")
            logger.info("💡 Crea un CSV con al menos la columna 'profit'")
            # Crear datos sintéticos de ejemplo
            self.trades = self._create_sample_trades()
            return self.trades

        try:
            df = pd.read_csv(path)
            logger.info(f"✅ Cargados {len(df):,} trades desde {path}")

            # Normalizar nombres de columnas
            df.columns = [c.lower().strip() for c in df.columns]

            # Asegurar columna profit
            if "profit" not in df.columns:
                # Buscar alternativas
                for col in ["pnl", "result", "pips", "net"]:
                    if col in df.columns:
                        df.rename(columns={col: "profit"}, inplace=True)
                        break

            if "profit" not in df.columns:
                logger.error("❌ No se encontró columna 'profit' en el CSV")
                return pd.DataFrame()

            self.trades = df
            return df

        except Exception as e:
            logger.error(f"❌ Error cargando {path}: {e}")
            return pd.DataFrame()

    def _create_sample_trades(self, n_trades: int = 500) -> pd.DataFrame:
        """
        Crea datos sintéticos de ejemplo para demostración.

        Genera trades con:
          - 60% de probabilidad de ganar
          - Risk/Reward promedio de 1:1.5
          - Drawdown máximo controlado
        """
        logger.info("🧪 Creando datos sintéticos de ejemplo...")

        np.random.seed(42)
        random.seed(42)

        profits = []
        for _ in range(n_trades):
            if random.random() < 0.6:  # 60% win rate
                profit = round(random.uniform(10, 50), 2)  # Ganancia
            else:
                profit = round(random.uniform(-30, -10), 2)  # Pérdida

            profits.append(profit)

        df = pd.DataFrame({
            "trade_id": range(1, n_trades + 1),
            "profit": profits,
            "symbol": random.choices(
                ["EURUSD", "GBPUSD", "GOLD", "USDJPY"],
                weights=[0.4, 0.25, 0.2, 0.15],
                k=n_trades,
            ),
            "direction": random.choices(["buy", "sell"], k=n_trades),
        })

        logger.info(f"✅ Creados {n_trades} trades sintéticos")
        logger.info(f"   Win Rate: {sum(1 for p in profits if p > 0)/n_trades*100:.1f}%")
        logger.info(f"   Profit Total: {sum(profits):+.2f}")

        return df

    def run_simulation(
        self,
        n_simulations: int = 10_000,
        initial_capital: float = 10_000.0,
        risk_per_trade: float = 0.01,
    ) -> dict:
        """
        Ejecuta la simulación de Montecarlo.

        Desordena los resultados de los trades 10,000 veces para
        crear curvas de equidad sintéticas.

        Args:
            n_simulations: Número de simulaciones (default: 10,000)
            initial_capital: Capital inicial en USD
            risk_per_trade: Riesgo por operación (1% = 0.01)

        Returns:
            Dict con resultados estadísticos
        """
        if self.trades is None or self.trades.empty:
            logger.error("❌ No hay trades cargados")
            return {}

        profits = self.trades["profit"].values
        n_trades = len(profits)

        logger.info("=" * 60)
        logger.info("🎲 SIMULACIÓN DE MONTECARLO")
        logger.info(f"   Trades base: {n_trades:,}")
        logger.info(f"   Simulaciones: {n_simulations:,}")
        logger.info(f"   Capital inicial: ${initial_capital:,.2f}")
        logger.info(f"   Riesgo por trade: {risk_per_trade*100:.1f}%")
        logger.info("=" * 60)

        # Matriz para almacenar todas las curvas de equidad
        # Forma: (n_simulations, n_trades + 1)
        equity_curves = np.zeros((n_simulations, n_trades + 1))
        equity_curves[:, 0] = initial_capital

        # Convertir profits absolutos a retornos porcentuales
        # Si los profits están en USD, interpretar como % del capital
        if np.abs(profits).max() > 1:  # Son USD, no porcentajes
            # Los profits ya representan el resultado de arriesgar risk_per_trade
            # Normalizar: profit / (initial_capital * risk_per_trade) = retorno en %
            returns = profits / (initial_capital * risk_per_trade)
        else:
            returns = profits

        # Ejecutar simulaciones
        for sim in range(n_simulations):
            if (sim + 1) % 1000 == 0:
                logger.info(f"   Progreso: {sim + 1:,}/{n_simulations:,} simulaciones")

            # Sample con reemplazo (cada simulación es única)
            sampled_returns = np.random.choice(returns, size=n_trades, replace=True)

            # Calcular curva de equidad con retornos compuestos
            # sampled_returns ya son % del capital arriesgado
            equity_curve = initial_capital * np.cumprod(1 + sampled_returns * risk_per_trade)
            equity_curves[sim, 1:] = equity_curve

        self.equity_curves = equity_curves

        # Calcular estadísticas
        results = self._compute_statistics(equity_curves, initial_capital)

        return results

    def _compute_statistics(
        self,
        equity_curves: np.ndarray,
        initial_capital: float,
    ) -> dict:
        """
        Calcula estadísticas de las simulaciones de Montecarlo.

        Args:
            equity_curves: Matriz de curvas de equidad
            initial_capital: Capital inicial

        Returns:
            Dict con métricas de riesgo y rendimiento
        """
        final_equities = equity_curves[:, -1]
        max_equities = equity_curves.max(axis=1)
        min_equities = equity_curves.min(axis=1)

        # Drawdown máximo por simulación
        running_max = np.maximum.accumulate(equity_curves, axis=1)
        drawdowns = (equity_curves - running_max) / running_max * 100
        max_drawdowns = drawdowns.min(axis=1)

        # Métricas principales
        results = {
            "n_simulations": len(equity_curves),
            "n_trades": equity_curves.shape[1] - 1,
            "initial_capital": initial_capital,
            # Capital final
            "final_median": np.median(final_equities),
            "final_mean": np.mean(final_equities),
            "final_std": np.std(final_equities),
            "final_best": np.max(final_equities),
            "final_worst": np.min(final_equities),
            "final_q25": np.percentile(final_equities, 25),
            "final_q75": np.percentile(final_equities, 75),
            # Drawdown
            "max_drawdown_mean": np.mean(max_drawdowns),
            "max_drawdown_median": np.median(max_drawdowns),
            "max_drawdown_worst": np.min(max_drawdowns),
            "max_drawdown_q95": np.percentile(max_drawdowns, 5),  # Peor 5%
            # Riesgo de ruina
            "ruin_risk_10pct": np.mean(final_equities < initial_capital * 0.9) * 100,
            "ruin_risk_20pct": np.mean(final_equities < initial_capital * 0.8) * 100,
            "ruin_risk_50pct": np.mean(final_equities < initial_capital * 0.5) * 100,
            # Probabilidad de ganancia
            "profit_probability": np.mean(final_equities > initial_capital) * 100,
            # Sharpe ratio estimado
            "sharpe_ratio": (
                np.mean(final_equities - initial_capital)
                / np.std(final_equities)
                if np.std(final_equities) > 0
                else 0
            ),
        }

        # Mostrar resumen
        self._print_results(results)

        return results

    def _print_results(self, results: dict):
        """Imprime los resultados de la simulación."""
        print("\n" + "=" * 60)
        print("📊 RESULTADOS DE MONTECARLO")
        print("=" * 60)

        print(f"\n💰 CAPITAL FINAL (${results['initial_capital']:,.2f} inicial):")
        print(f"   Mejor caso:  ${results['final_best']:>10,.2f}")
        print(f"   Percentil 75: ${results['final_q75']:>10,.2f}")
        print(f"   Mediana:     ${results['final_median']:>10,.2f}")
        print(f"   Media:       ${results['final_mean']:>10,.2f}")
        print(f"   Percentil 25: ${results['final_q25']:>10,.2f}")
        print(f"   Peor caso:   ${results['final_worst']:>10,.2f}")
        print(f"   Desv. Estándar: ${results['final_std']:>10,.2f}")

        print(f"\n📉 DRAWDOWN MÁXIMO:")
        print(f"   Peor drawdown:  {results['max_drawdown_worst']:>6.2f}%")
        print(f"   Drawdown p95:   {results['max_drawdown_q95']:>6.2f}%")
        print(f"   Drawdown medio: {results['max_drawdown_mean']:>6.2f}%")

        print(f"\n⚠️  RIESGO DE RUINA:")
        print(f"   Perder >10%: {results['ruin_risk_10pct']:>5.1f}%")
        print(f"   Perder >20%: {results['ruin_risk_20pct']:>5.1f}%")
        print(f"   Perder >50%: {results['ruin_risk_50pct']:>5.1f}%")

        print(f"\n📈 MÉTRICAS ADICIONALES:")
        print(f"   Probabilidad de ganancia: {results['profit_probability']:>5.1f}%")
        print(f"   Sharpe Ratio:             {results['sharpe_ratio']:>6.3f}")

        print("=" * 60)

    def plot_results(self, save: bool = True):
        """
        Visualiza los resultados de la simulación de Montecarlo.

        Args:
            save: Si True, guarda la figura
        """
        if self.equity_curves is None:
            logger.error("❌ Ejecuta run_simulation() primero")
            return

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(
            "Análisis de Montecarlo — Validación de Robustez",
            fontsize=14,
            fontweight="bold",
        )

        # 1. Curvas de equidad (mostrar una muestra)
        ax1 = axes[0, 0]
        n_show = min(100, len(self.equity_curves))
        sample_indices = np.random.choice(
            len(self.equity_curves), n_show, replace=False
        )

        for idx in sample_indices:
            ax1.plot(
                self.equity_curves[idx],
                color="steelblue",
                alpha=0.1,
                linewidth=0.5,
            )

        # Curva mediana
        median_curve = np.median(self.equity_curves, axis=0)
        ax1.plot(
            median_curve,
            color="red",
            linewidth=2,
            label="Mediana",
        )

        # Percentiles
        upper = np.percentile(self.equity_curves, 75, axis=0)
        lower = np.percentile(self.equity_curves, 25, axis=0)
        ax1.fill_between(
            range(len(median_curve)),
            lower,
            upper,
            color="red",
            alpha=0.1,
            label="Percentil 25-75",
        )

        ax1.axhline(
            y=self.equity_curves[0, 0],
            color="gray",
            linestyle="--",
            alpha=0.5,
            label="Capital inicial",
        )
        ax1.set_title("Curvas de Equidad (muestra de 100)")
        ax1.set_xlabel("N° de Trade")
        ax1.set_ylabel("Capital ($)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 2. Distribución del capital final
        ax2 = axes[0, 1]
        final_equities = self.equity_curves[:, -1]
        ax2.hist(
            final_equities,
            bins=50,
            color="steelblue",
            edgecolor="white",
            alpha=0.7,
        )
        ax2.axvline(
            self.equity_curves[0, 0],
            color="red",
            linestyle="--",
            linewidth=2,
            label="Capital inicial",
        )
        ax2.axvline(
            np.median(final_equities),
            color="green",
            linestyle="--",
            linewidth=2,
            label=f"Mediana: ${np.median(final_equities):,.0f}",
        )
        ax2.set_title("Distribución del Capital Final")
        ax2.set_xlabel("Capital Final ($)")
        ax2.set_ylabel("Frecuencia")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        # 3. Drawdown máximo
        ax3 = axes[1, 0]
        running_max = np.maximum.accumulate(self.equity_curves, axis=1)
        drawdowns = (self.equity_curves - running_max) / running_max * 100
        max_drawdowns = drawdowns.min(axis=1)

        ax3.hist(
            max_drawdowns,
            bins=50,
            color="coral",
            edgecolor="white",
            alpha=0.7,
        )
        ax3.axvline(
            np.median(max_drawdowns),
            color="red",
            linestyle="--",
            linewidth=2,
            label=f"Mediana: {np.median(max_drawdowns):.1f}%",
        )
        ax3.set_title("Distribución del Drawdown Máximo")
        ax3.set_xlabel("Drawdown Máximo (%)")
        ax3.set_ylabel("Frecuencia")
        ax3.legend()
        ax3.grid(True, alpha=0.3)

        # 4. Riesgo de ruina
        ax4 = axes[1, 1]
        initial = self.equity_curves[0, 0]
        thresholds = [0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50]
        risks = [
            np.mean(final_equities < initial * t) * 100 for t in thresholds
        ]

        bars = ax4.barh(
            [f"{int((1-t)*100)}%" for t in thresholds],
            risks,
            color=plt.cm.RdYlGn_r(
                [r / 100 for r in risks]
            ),
        )
        ax4.set_title("Riesgo de Ruina por Umbral")
        ax4.set_xlabel("Probabilidad de Ruina (%)")
        ax4.set_ylabel("Pérdida desde Capital Inicial")

        # Añadir etiquetas a las barras
        for bar, risk in zip(bars, risks):
            ax4.text(
                bar.get_width() + 0.5,
                bar.get_y() + bar.get_height() / 2,
                f"{risk:.1f}%",
                va="center",
                fontsize=9,
            )

        ax4.grid(True, alpha=0.3, axis="x")

        plt.tight_layout()

        if save:
            filepath = self.results_dir / "montecarlo_simulation.png"
            plt.savefig(filepath, dpi=150, bbox_inches="tight")
            logger.info(f"📸 Gráfico guardado: {filepath}")

        plt.show()

    def get_risk_recommendation(self, results: dict) -> dict:
        """
        Genera recomendaciones de ajuste de riesgo basadas en
        los resultados de Montecarlo.

        Args:
            results: Resultados de run_simulation()

        Returns:
            Dict con recomendaciones
        """
        recommendations = {}

        # Evaluar riesgo de ruina
        ruin_10 = results.get("ruin_risk_10pct", 0)
        ruin_20 = results.get("ruin_risk_20pct", 0)

        if ruin_20 > 10:
            recommendations["action"] = "CRÍTICO"
            recommendations["message"] = (
                f"⚠️ Riesgo de ruina del {ruin_20:.1f}% para pérdida del 20%. "
                "REDUCIR RIESGO INMEDIATAMENTE."
            )
            recommendations["risk_multiplier"] = 0.5
        elif ruin_10 > 15:
            recommendations["action"] = "ALERTA"
            recommendations["message"] = (
                f"⚠️ Riesgo de ruina del {ruin_10:.1f}% para pérdida del 10%. "
                "Considera reducir el riesgo por trade."
            )
            recommendations["risk_multiplier"] = 0.75
        elif results.get("profit_probability", 0) > 80:
            recommendations["action"] = "ÓPTIMO"
            recommendations["message"] = (
                f"✅ Sistema robusto. {results['profit_probability']:.1f}% "
                "de probabilidad de ganancia. Puedes mantener el riesgo actual."
            )
            recommendations["risk_multiplier"] = 1.0
        else:
            recommendations["action"] = "MONITOREO"
            recommendations["message"] = (
                "📊 Sistema en zona de monitoreo. "
                "Aumenta el número de trades para mejor significancia estadística."
            )
            recommendations["risk_multiplier"] = 0.9

        # Drawdown recomendado
        worst_dd = results.get("max_drawdown_worst", 0)
        recommendations["expected_drawdown"] = abs(worst_dd)
        recommendations["stop_trading_at_drawdown"] = abs(worst_dd) * 1.5

        logger.info(f"\n🔧 RECOMENDACIÓN: {recommendations['action']}")
        logger.info(f"   {recommendations['message']}")

        return recommendations


# ──────────────────────────────────────────────
# EJECUCIÓN DIRECTA
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="NEXUS QUANT LAB — Montecarlo Simulation"
    )
    parser.add_argument(
        "--audit-file",
        type=str,
        default=None,
        help="Ruta al archivo master_audit.csv",
    )
    parser.add_argument(
        "--simulations",
        type=int,
        default=10_000,
        help="Número de simulaciones (default: 10,000)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10_000.0,
        help="Capital inicial en USD",
    )
    parser.add_argument(
        "--risk",
        type=float,
        default=0.01,
        help="Riesgo por trade (0.01 = 1%)",
    )
    parser.add_argument("--no-plot", action="store_true")

    args = parser.parse_args()

    # Inicializar simulador
    simulator = MontecarloSimulator(audit_path=args.audit_file)

    # Cargar trades
    trades = simulator.load_trades()
    if trades.empty:
        logger.error("❌ No se pudieron cargar los trades")
        exit(1)

    # Ejecutar simulación
    results = simulator.run_simulation(
        n_simulations=args.simulations,
        initial_capital=args.capital,
        risk_per_trade=args.risk,
    )

    if results:
        # Recomendaciones
        recommendations = simulator.get_risk_recommendation(results)

        # Graficar
        if not args.no_plot:
            simulator.plot_results()

    print("\n✅ Simulación de Montecarlo completada.")
