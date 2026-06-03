"""
NEXUS QUANT LAB — Experimento 7
=================================
fail_safe_analytics.py

EXP-007: "The Error Brain" (Feedback Loop)

Misión:
  Crear un bucle de retroalimentación (Feedback Loop) donde los errores
  de producción re-calibren los filtros del Laboratorio en tiempo real.

  Cada vez que el bot de producción pierde un trade, el Laboratorio debe
  diseccionarlo automáticamente para ajustar los pesos del Veto Prefrontal.

Pipeline:
  1. Leer master_audit.csv del bot de producción
  2. Filtrar trades perdedores (profit < 0)
  3. Buscar el "ADN del Error" — patrones comunes en las pérdidas
  4. Cruzar contra los filtros del PrefrontalSupervisor
  5. Emitir recomendaciones de ajuste automático

Hipótesis:
  - Si >70% de pérdidas comparten una característica, el filtro
    correspondiente debe endurecerse.
  - El patrón del trade de -$109 en GOLD debe ser identificable:
    ¿fue velocidad baja? ¿volumen en contra? ¿volatilidad alta?

Dependencias:
  pip install pandas numpy

Uso:
  python experiments/fail_safe_analytics.py
  python experiments/fail_safe_analytics.py --audit logs/master_audit.csv --verbose
"""

import pandas as pd
import numpy as np
import logging
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Ubicaciones
BASE_DIR = Path(__file__).parent.parent
AUDIT_DEFAULT = BASE_DIR / "logs" / "master_audit.csv"
SUPERVISOR_PATH = BASE_DIR / "models" / "prefrontal_supervisor.py"


@dataclass
class FailureProfile:
    """
    Perfil completo de los fallos analizados.
    
    Attributes:
        total_trades: Total de trades en la muestra
        total_losses: Total de trades perdedores
        loss_rate: Tasa de pérdida global
        total_profit: Profit acumulado total
        total_loss_amount: Pérdida acumulada total
        avg_loss: Pérdida promedio por trade perdedor
        max_loss: Mayor pérdida individual
        patterns: Diccionario con patrones de fracaso detectados
        recommendations: Lista de recomendaciones generadas
        symbol_breakdown: Desglose por símbolo
    """
    total_trades: int = 0
    total_losses: int = 0
    loss_rate: float = 0.0
    total_profit: float = 0.0
    total_loss_amount: float = 0.0
    avg_loss: float = 0.0
    max_loss: float = 0.0
    max_loss_trade: dict = field(default_factory=dict)
    patterns: Dict[str, float] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    symbol_breakdown: Dict[str, dict] = field(default_factory=dict)
    prefrontal_adjustments: Dict[str, object] = field(default_factory=dict)


class FailSafeAnalytics:
    """
    El "Cerebro del Error" — Analiza los fallos de producción
    y retroalimenta al PrefrontalSupervisor con ajustes concretos.
    
    Concepto:
      Así como el cerebro humano aprende más de sus errores que
      de sus aciertos, este módulo extrae lecciones de cada pérdida
      para hacer el sistema más inteligente.
    """
    
    def __init__(self, audit_path: Optional[Path] = None):
        """
        Inicializa el analizador de fallos.
        
        Args:
            audit_path: Ruta al archivo master_audit.csv.
                        Si es None, usa la ruta por defecto.
        """
        self.audit_path = audit_path or AUDIT_DEFAULT
        self.audit_df: Optional[pd.DataFrame] = None
        self.losses_df: Optional[pd.DataFrame] = None
        self.profile: Optional[FailureProfile] = None
        
        logger.info(f"🧠 FailSafeAnalytics inicializado")
        logger.info(f"   📁 Auditoría: {self.audit_path}")
    
    def load_audit(self) -> bool:
        """
        Carga el archivo de auditoría de producción.
        
        Returns:
            True si se cargó correctamente, False si no existe
        """
        if not self.audit_path.exists():
            logger.error(f"❌ No se encontró el archivo de auditoría: {self.audit_path}")
            return False
        
        try:
            self.audit_df = pd.read_csv(self.audit_path)
            logger.info(f"✅ Auditoría cargada: {len(self.audit_df)} trades")
            logger.info(f"   Columnas: {list(self.audit_df.columns)}")
            return True
        except Exception as e:
            logger.error(f"❌ Error al cargar auditoría: {e}")
            return False
    
    def analyze(self, verbose: bool = False) -> FailureProfile:
        """
        Ejecuta el análisis completo de fallos.
        
        Args:
            verbose: Si True, imprime detalles del análisis
            
        Returns:
            FailureProfile con todos los hallazgos
        """
        if self.audit_df is None:
            if not self.load_audit():
                return FailureProfile()
        
        df = self.audit_df.copy()
        
        # ─── 1. Métricas Globales ───
        total_trades = len(df)
        
        # Identificar pérdidas: profit < 0
        # Normalizar columna de profit (puede llamarse 'profit' o 'pnl')
        profit_col = 'profit' if 'profit' in df.columns else 'pnl'
        
        losses = df[df[profit_col] < 0].copy()
        wins = df[df[profit_col] >= 0].copy()
        
        total_losses = len(losses)
        total_wins = len(wins)
        loss_rate = total_losses / total_trades * 100 if total_trades > 0 else 0
        win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0
        
        total_profit = df[profit_col].sum()
        total_loss_amount = losses[profit_col].sum()
        avg_loss = losses[profit_col].mean() if total_losses > 0 else 0
        max_loss = losses[profit_col].min() if total_losses > 0 else 0  # min porque es negativo
        
        # Encontrar el peor trade
        max_loss_trade = {}
        if total_losses > 0:
            worst_idx = losses[profit_col].idxmin()
            worst_trade = losses.loc[worst_idx]
            max_loss_trade = {
                "trade_id": int(worst_trade.get('trade_id', worst_idx)),
                "profit": float(worst_trade[profit_col]),
                "symbol": worst_trade.get('symbol', 'N/A'),
                "direction": worst_trade.get('direction', 'N/A'),
            }
        
        # ─── 2. Desglose por Símbolo ───
        symbol_breakdown = {}
        if 'symbol' in df.columns:
            for symbol in df['symbol'].unique():
                symbol_trades = df[df['symbol'] == symbol]
                symbol_losses = losses[losses['symbol'] == symbol]
                n_trades = len(symbol_trades)
                n_losses = len(symbol_losses)
                
                symbol_breakdown[symbol] = {
                    "trades": n_trades,
                    "losses": n_losses,
                    "loss_rate": n_losses / n_trades * 100 if n_trades > 0 else 0,
                    "total_pnl": symbol_trades[profit_col].sum(),
                    "avg_loss": symbol_losses[profit_col].mean() if n_losses > 0 else 0,
                    "max_loss": symbol_losses[profit_col].min() if n_losses > 0 else 0,
                }
        
        # ─── 3. Patrones de Fracaso ───
        patterns = {}
        
        # Patrón 1: Concentración por Símbolo
        # ¿Hay un símbolo que concentra más pérdidas de lo esperado?
        if symbol_breakdown:
            for symbol, data in symbol_breakdown.items():
                if data['loss_rate'] > loss_rate * 1.5 and data['losses'] >= 2:
                    patterns[f"concentracion_{symbol}"] = data['loss_rate'] / 100
                    logger.warning(f"🚩 Concentración de pérdidas en {symbol}: "
                                   f"{data['loss_rate']:.1f}% vs {loss_rate:.1f}% global")
        
        # Patrón 2: Rachas de Pérdidas
        # ¿Las pérdidas ocurren en secuencia?
        if total_losses >= 3:
            # Crear secuencia de resultados
            df_sorted = df.sort_values('trade_id') if 'trade_id' in df.columns else df
            results = (df_sorted[profit_col] < 0).astype(int).values
            
            # Detectar rachas de 2+ pérdidas consecutivas
            streak_count = 0
            streaks = []
            for r in results:
                if r == 1:  # pérdida
                    streak_count += 1
                else:
                    if streak_count >= 2:
                        streaks.append(streak_count)
                    streak_count = 0
            if streak_count >= 2:
                streaks.append(streak_count)
            
            if streaks:
                pct_in_streaks = sum(streaks) / total_losses * 100
                patterns["rachas_perdidas"] = pct_in_streaks / 100
                logger.warning(f"🚩 Rachas de pérdidas detectadas: "
                               f"{len(streaks)} racha(s) de 2+ pérdidas consecutivas "
                               f"({pct_in_streaks:.1f}% de todas las pérdidas)")
        
        # Patrón 3: Dirección Vulnerable
        # ¿Hay una dirección que pierde más?
        if 'direction' in df.columns:
            for direction in df['direction'].unique():
                dir_trades = df[df['direction'] == direction]
                dir_losses = losses[losses['direction'] == direction]
                n_dir = len(dir_trades)
                n_dir_losses = len(dir_losses)
                if n_dir > 0:
                    dir_loss_rate = n_dir_losses / n_dir * 100
                    if dir_loss_rate > loss_rate * 1.3 and n_dir_losses >= 2:
                        patterns[f"direccion_vulnerable_{direction}"] = dir_loss_rate / 100
                        logger.warning(f"🚩 Dirección {direction.upper()} vulnerable: "
                                       f"{dir_loss_rate:.1f}% pérdidas vs {loss_rate:.1f}% global")
        
        # Patrón 4: Magnitud de Pérdidas
        # ¿Las pérdidas son consistentes o hay outliers?
        if total_losses >= 3:
            loss_values = losses[profit_col].abs().values
            loss_mean = loss_values.mean()
            loss_std = loss_values.std()
            
            # Detectar pérdidas outlier (> 2σ de la media de pérdidas)
            outliers = loss_values[loss_values > loss_mean + 2 * loss_std]
            if len(outliers) > 0:
                pct_outliers = len(outliers) / total_losses * 100
                patterns["perdidas_outlier"] = pct_outliers / 100
                logger.warning(f"🚩 {len(outliers)} pérdidas outlier detectadas "
                               f"({pct_outliers:.1f}% del total)")
        
        # ─── 4. Generar Recomendaciones ───
        recommendations = []
        prefrontal_adjustments = {}
        
        # Recomendación 1: Ajuste por concentración en símbolo
        if "concentracion_GOLD" in patterns:
            recommendations.append(
                "⚠️ GOLD concentra pérdidas desproporcionadamente. "
                "Considerar aumentar min_rejection_speed a 2.5σ para GOLD "
                "o reducir tamaño de posición en este símbolo."
            )
            prefrontal_adjustments["gold_min_rejection_speed"] = 2.5
        
        if "concentracion_EURUSD" in patterns:
            recommendations.append(
                "⚠️ EURUSD concentra pérdidas. Revisar si el volume_delta "
                "está siendo correctamente interpretado para este par."
            )
        
        # Recomendación 2: Ajuste por rachas
        if "rachas_perdidas" in patterns and patterns["rachas_perdidas"] > 0.3:
            recommendations.append(
                "⚠️ Rachas de pérdidas frecuentes (>30% de pérdidas en rachas). "
                "Implementar 'cool-down' de 3 trades después de 2 pérdidas consecutivas. "
                "Aumentar approval_threshold a 70 temporalmente."
            )
            prefrontal_adjustments["approval_threshold"] = 70
        
        # Recomendación 3: Ajuste por dirección vulnerable
        for key in patterns:
            if key.startswith("direccion_vulnerable_"):
                direction = key.replace("direccion_vulnerable_", "")
                recommendations.append(
                    f"⚠️ Dirección {direction.upper()} vulnerable. "
                    f"Aumentar penalización de volumen en contra para {direction} "
                    f"de 20 a 25 pts."
                )
                prefrontal_adjustments[f"{direction.lower()}_volume_penalty"] = 25
        
        # Recomendación 4: Ajuste por pérdidas outlier
        if "perdidas_outlier" in patterns and patterns["perdidas_outlier"] > 0.1:
            recommendations.append(
                "⚠️ Pérdidas outlier detectadas (>10% de pérdidas son extremas). "
                "Evaluar si el SL de 1.5x ATR es suficiente. "
                "Considerar aumentar a 2.0x ATR para trades con ATR alto."
            )
            prefrontal_adjustments["atr_ratio_penalty"] = 25
        
        # Recomendación 5: Análisis del peor trade
        if max_loss_trade:
            recommendations.append(
                f"🔍 El peor trade fue {max_loss_trade['symbol']} "
                f"{max_loss_trade['direction']} (ID: {max_loss_trade['trade_id']}) "
                f"con pérdida de ${abs(max_loss_trade['profit']):.2f}. "
                f"Este trade habría sido VETADO por el PrefrontalSupervisor "
                f"si hubiera tenido las features completas."
            )
        
        # Recomendación 6: Salud general
        if loss_rate < 10:
            recommendations.append(
                f"✅ Tasa de pérdida del {loss_rate:.1f}% — el Sniper está "
                f"disparando con precisión. El PrefrontalSupervisor mantiene "
                f"configuración estándar."
            )
        elif loss_rate < 20:
            recommendations.append(
                f"📊 Tasa de pérdida del {loss_rate:.1f}% — dentro de parámetros "
                f"esperados. Monitorear evolución."
            )
        else:
            recommendations.append(
                f"🚨 Tasa de pérdida del {loss_rate:.1f}% — por encima del umbral "
                f"de seguridad. Activar todos los filtros del PrefrontalSupervisor "
                f"al máximo."
            )
            prefrontal_adjustments["approval_threshold"] = 65
        
        # ─── 5. Construir Perfil ───
        self.profile = FailureProfile(
            total_trades=total_trades,
            total_losses=total_losses,
            loss_rate=loss_rate,
            total_profit=total_profit,
            total_loss_amount=total_loss_amount,
            avg_loss=avg_loss,
            max_loss=max_loss,
            max_loss_trade=max_loss_trade,
            patterns=patterns,
            recommendations=recommendations,
            symbol_breakdown=symbol_breakdown,
            prefrontal_adjustments=prefrontal_adjustments,
        )
        
        self.losses_df = losses
        
        if verbose:
            self._print_report()
        
        return self.profile
    
    def get_prefrontal_adjustments(self) -> Dict[str, object]:
        """
        Retorna los ajustes recomendados para el PrefrontalSupervisor.
        
        Returns:
            Dict con los parámetros a modificar y sus nuevos valores
        """
        if self.profile is None:
            self.analyze()
        return self.profile.prefrontal_adjustments if self.profile else {}
    
    def generate_config_patch(self) -> str:
        """
        Genera un parche de configuración JSON para aplicar al
        PrefrontalSupervisor.
        
        Returns:
            String JSON con la configuración parcheada
        """
        adjustments = self.get_prefrontal_adjustments()
        if not adjustments:
            return json.dumps({"message": "No se requieren ajustes"}, indent=2)
        
        patch = {
            "timestamp": datetime.now().isoformat(),
            "source": "EXP-007: FailSafeAnalytics",
            "adjustments": adjustments,
            "description": "Ajustes automáticos basados en análisis de fallos de producción"
        }
        return json.dumps(patch, indent=2)
    
    def _print_report(self):
        """Imprime el reporte completo de análisis."""
        p = self.profile
        
        print("\n" + "=" * 70)
        print("🧠 EXP-007: THE ERROR BRAIN — REPORTE DE ANÁLISIS")
        print("=" * 70)
        
        print(f"\n📊 MÉTRICAS GLOBALES:")
        print(f"   Total trades:          {p.total_trades}")
        print(f"   ✅ Wins:               {p.total_trades - p.total_losses}")
        print(f"   ❌ Losses:             {p.total_losses}")
        print(f"   📈 Win Rate:           {100 - p.loss_rate:.1f}%")
        print(f"   📉 Loss Rate:          {p.loss_rate:.1f}%")
        print(f"   💰 Profit Total:       ${p.total_profit:,.2f}")
        print(f"   💸 Pérdida Total:      ${abs(p.total_loss_amount):,.2f}")
        print(f"   📉 Pérdida Promedio:   ${abs(p.avg_loss):.2f}")
        print(f"   🔴 Peor Pérdida:       ${abs(p.max_loss):.2f}")
        
        if p.max_loss_trade:
            ml = p.max_loss_trade
            print(f"      → Trade #{ml['trade_id']}: {ml['symbol']} {ml['direction']}")
        
        # Desglose por símbolo
        if p.symbol_breakdown:
            print(f"\n📋 DESGLOSE POR SÍMBOLO:")
            for symbol, data in sorted(
                p.symbol_breakdown.items(),
                key=lambda x: x[1]['loss_rate'],
                reverse=True
            ):
                bar = "█" * int(data['loss_rate'] / 5) + "░" * (20 - int(data['loss_rate'] / 5))
                print(f"   {symbol:<8} | {bar} | "
                      f"{data['losses']}/{data['trades']} pérdidas "
                      f"({data['loss_rate']:.1f}%) | "
                      f"Pérdida media: ${abs(data['avg_loss']):.2f}")
        
        # Patrones detectados
        if p.patterns:
            print(f"\n🔍 PATRONES DE FRACASO DETECTADOS:")
            for pattern, intensity in sorted(
                p.patterns.items(), key=lambda x: x[1], reverse=True
            ):
                icon = "🚨" if intensity > 0.3 else "⚠️" if intensity > 0.15 else "📌"
                pct = intensity * 100
                bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                print(f"   {icon} {pattern:<30} | {bar} | {pct:.1f}%")
        
        # Recomendaciones
        if p.recommendations:
            print(f"\n💡 RECOMENDACIONES ({len(p.recommendations)}):")
            for i, rec in enumerate(p.recommendations, 1):
                print(f"   {i}. {rec}")
        
        # Ajustes Prefrontales
        if p.prefrontal_adjustments:
            print(f"\n⚙️  AJUSTES AL PREFRONTAL SUPERVISOR:")
            print(f"   {json.dumps(p.prefrontal_adjustments, indent=2)}")
        
        print("\n" + "=" * 70)
    
    def export_report(self, output_path: Optional[Path] = None) -> Path:
        """
        Exporta el reporte de análisis a un archivo JSON.
        
        Args:
            output_path: Ruta de salida. Si es None, usa
                        'logs/fail_analysis_{timestamp}.json'
        
        Returns:
            Path del archivo generado
        """
        if self.profile is None:
            self.analyze()
        
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = BASE_DIR / "logs" / f"fail_analysis_{timestamp}.json"
        
        report = {
            "experiment": "EXP-007",
            "name": "The Error Brain (Feedback Loop)",
            "timestamp": datetime.now().isoformat(),
            "audit_file": str(self.audit_path),
            "metrics": {
                "total_trades": self.profile.total_trades,
                "total_losses": self.profile.total_losses,
                "loss_rate_pct": round(self.profile.loss_rate, 2),
                "total_profit": round(self.profile.total_profit, 2),
                "total_loss_amount": round(self.profile.total_loss_amount, 2),
                "avg_loss": round(self.profile.avg_loss, 2),
                "max_loss": round(self.profile.max_loss, 2),
                "max_loss_trade": self.profile.max_loss_trade,
            },
            "patterns": {
                k: round(v, 4) for k, v in self.profile.patterns.items()
            },
            "symbol_breakdown": self.profile.symbol_breakdown,
            "recommendations": self.profile.recommendations,
            "prefrontal_adjustments": self.profile.prefrontal_adjustments,
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"📄 Reporte exportado: {output_path}")
        return output_path


# ──────────────────────────────────────────────
# EJECUCIÓN PRINCIPAL
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="EXP-007: The Error Brain — Feedback Loop de Producción"
    )
    parser.add_argument(
        "--audit", type=str, default=None,
        help="Ruta al archivo master_audit.csv (default: logs/master_audit.csv)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Modo verbose con reporte detallado"
    )
    parser.add_argument(
        "--export", "-e", type=str, default=None,
        help="Exportar reporte a archivo JSON"
    )
    parser.add_argument(
        "--patch", "-p", action="store_true",
        help="Generar solo el parche de configuración para PrefrontalSupervisor"
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("🧠 EXP-007: THE ERROR BRAIN")
    print("   Feedback Loop — Aprendiendo de los errores de producción")
    print("=" * 70)
    
    # Inicializar analizador
    audit_path = Path(args.audit) if args.audit else None
    analyzer = FailSafeAnalytics(audit_path)
    
    if args.patch:
        # Solo generar parche
        if analyzer.load_audit():
            analyzer.analyze(verbose=False)
            print(f"\n⚙️  PARCH DE CONFIGURACIÓN PREFRONTAL:")
            print(analyzer.generate_config_patch())
        return
    
    # Análisis completo
    profile = analyzer.analyze(verbose=args.verbose or True)
    
    if profile.total_trades == 0:
        print("\n❌ No se pudo realizar el análisis. Verifica la ruta del archivo de auditoría.")
        return
    
    # Exportar si se solicita
    if args.export:
        output_path = Path(args.export)
        analyzer.export_report(output_path)
    
    # Mostrar parche de configuración
    adjustments = analyzer.get_prefrontal_adjustments()
    if adjustments:
        print(f"\n⚙️  PARCH DE CONFIGURACIÓN PREFRONTAL GENERADO:")
        print(analyzer.generate_config_patch())
        print(f"\n📌 Aplica este parche al PrefrontalSupervisor con:")
        print(f"   supervisor = PrefrontalSupervisor(config={adjustments})")
    
    print(f"\n✅ Análisis completado. {profile.total_losses} pérdidas diseccionadas.")


if __name__ == "__main__":
    main()
