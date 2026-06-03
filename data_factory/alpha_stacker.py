"""
EXP-009: The Alpha Stacker (Refinería de Factores)
==================================================
Fusiona todos los experimentos del Laboratorio en una sola matriz de entrenamiento.
"Stacking" de features de alta frecuencia para crear el Dataset de Inteligencia Pura.

Pipeline:
  1. Carga EURUSD y GOLD
  2. Alineación temporal (merge por timestamp)
  3. Construcción de Factores Alfa (divergencia, velocidad, volumen, régimen)
  4. Generación de target (éxito de reversión en N velas)
  5. Exportación a alpha_master_dataset.csv
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')


class AlphaStacker:
    """
    La Refinería del Laboratorio.
    Toma los CSVs crudos y crea el dataset definitivo para entrenamiento.
    """

    # Columnas que esperamos de los CSVs del Lab
    REQUIRED_COLS = ['open', 'high', 'low', 'close', 'avg_speed', 
                     'tick_count', 'rejection_speed', 'micro_trend']

    def __init__(self, eur_file: str, gold_file: str):
        """
        Inicializa con las rutas a los CSVs de EURUSD y GOLD.
        """
        print("📂 Cargando datos del Laboratorio...")
        self.eur = pd.read_csv(eur_file, index_col='time', parse_dates=True)
        self.gold = pd.read_csv(gold_file, index_col='time', parse_dates=True)
        
        # FIX: Agrupar por timestamp (tomar el último valor de cada hora)
        # Los CSVs tienen duplicados porque la descarga día a día solapa timestamps
        for name, df in [('EURUSD', self.eur), ('GOLD', self.gold)]:
            before = len(df)
            df = df.groupby(df.index).last()
            after = len(df)
            if before != after:
                print(f"  🧹 {name}: {before - after:,} timestamps duplicados colapsados ({after:,} únicos)")
            if name == 'EURUSD':
                self.eur = df
            else:
                self.gold = df
        
        # Validar columnas esenciales
        for col in self.REQUIRED_COLS:
            if col not in self.eur.columns:
                print(f"  ⚠️  Columna '{col}' no encontrada en EURUSD. Se usará NaN.")
            if col not in self.gold.columns:
                print(f"  ⚠️  Columna '{col}' no encontrada en GOLD. Se usará NaN.")

    def build_master_factors(self, lookahead: int = 3, atr_period: int = 14) -> pd.DataFrame:
        """
        Construye la matriz maestra de Factores Alfa (Versión Robusta).

        Parámetros:
        -----------
        lookahead : int
            Velas hacia adelante para definir el target (default: 3)
        atr_period : int
            Período para cálculo de ATR (default: 14)

        Retorna:
        --------
        pd.DataFrame con factores alfa + target
        """
        print("🏗️  Construyendo Factores Alfa (Versión Robusta)...")
        
        # --- 1. ALINEACIÓN TEMPORAL (Outer join para no perder filas del Euro) ---
        df = pd.merge(
            self.eur, self.gold, 
            left_index=True, right_index=True, 
            suffixes=('_eur', '_gold'),
            how='left'
        )
        print(f"  📊 Muestras totales (Euro): {len(df)} velas H1")

        # --- 1b. FIX: Rellenar NaNs del Oro con 0.0 (Neutralidad) ---
        # Así, si el Oro no tiene data, no arruina la fila del Euro
        gold_cols = [c for c in df.columns if '_gold' in c]
        df[gold_cols] = df[gold_cols].fillna(0)
        print(f"  🛠️  Neutral-Padding aplicado a {len(gold_cols)} columnas del Oro")

        # --- 2. CÁLCULO DE ATR (Average True Range) ---
        df['tr_eur'] = self._true_range(df, 'eur')
        df['tr_gold'] = self._true_range(df, 'gold')
        df['atr_eur'] = df['tr_eur'].rolling(atr_period).mean()
        df['atr_gold'] = df['tr_gold'].rolling(atr_period).mean()

        # ============================================================
        # FACTOR 1: DIVERGENCIA (EXP-002)
        # ============================================================
        # Si el Euro sube pero el Oro baja -> Divergencia Bajista para el Euro
        # Si ambos suben -> Convergencia alcista (riesgo on)
        df['alpha_divergence'] = (
            df['close_eur'].pct_change() - df['close_gold'].pct_change()
        ).fillna(0)
        print("  ✅ Factor 1: alpha_divergence (EXP-002)")

        # ============================================================
        # FACTOR 2: MOMENTUM DE VELOCIDAD (EXP-001)
        # ============================================================
        # Z-score de la velocidad de tick del Euro
        # rejection_speed ya viene como desviación de la media
        df['alpha_rejection_z'] = (
            df['rejection_speed_eur'] - df['rejection_speed_eur'].rolling(24).mean()
        ) / df['rejection_speed_eur'].rolling(24).std().replace(0, 1)
        df['alpha_rejection_z'] = df['alpha_rejection_z'].fillna(0)
        
        # También para GOLD (con fillna(0) por si no hay datos)
        df['alpha_rejection_z_gold'] = (
            df['rejection_speed_gold'] - df['rejection_speed_gold'].rolling(24).mean()
        ) / df['rejection_speed_gold'].rolling(24).std().replace(0, 1)
        df['alpha_rejection_z_gold'] = df['alpha_rejection_z_gold'].fillna(0)
        print("  ✅ Factor 2: alpha_rejection_z (EXP-001)")

        # ============================================================
        # FACTOR 3: INTENCIÓN DE MICRO-TREND (EXP-004 adaptado)
        # ============================================================
        # Como buy_volume/sell_volume están en 0, usamos micro_trend como proxy
        # micro_trend > 0 = presión compradora, < 0 = presión vendedora
        df['alpha_micro_trend'] = df['micro_trend_eur'].fillna(0)
        df['alpha_micro_trend_gold'] = df['micro_trend_gold'].fillna(0)
        print("  ✅ Factor 3: alpha_micro_trend (EXP-004 adaptado)")

        # ============================================================
        # FACTOR 4: RÉGIMEN DE VOLATILIDAD (EXP-005)
        # ============================================================
        # Clasificamos el mercado en 3 regímenes basados en ATR
        atr_ratio = df['atr_eur'] / df['atr_eur'].rolling(48).mean()
        df['alpha_regime'] = pd.cut(
            atr_ratio.fillna(1.0),  # Neutral si no hay datos
            bins=[-np.inf, 0.7, 1.3, np.inf],
            labels=['low_vol', 'normal', 'high_vol']
        )
        print("  ✅ Factor 4: alpha_regime (EXP-005)")

        # ============================================================
        # FACTOR 5: PROXIMIDAD A MURO (HTF Structure)
        # ============================================================
        # Calculamos si el precio está cerca de máximos/mínimos recientes
        df['alpha_near_high'] = (
            df['close_eur'] / df['high_eur'].rolling(24).max()
        ).fillna(0)
        df['alpha_near_low'] = (
            df['close_eur'] / df['low_eur'].rolling(24).min()
        ).fillna(0)
        print("  ✅ Factor 5: alpha_near_high / alpha_near_low")

        # ============================================================
        # FACTOR 6: HORA DEL DÍA (EXP-008)
        # ============================================================
        # La hora 19:00 UTC es la "zona de muerte" (Fixing)
        df['hour'] = df.index.hour
        df['alpha_is_fixing_hour'] = (df['hour'] == 19).astype(int)
        df['alpha_is_ny_session'] = (
            (df['hour'] >= 13) & (df['hour'] <= 20)
        ).astype(int)
        print("  ✅ Factor 6: alpha_is_fixing_hour / alpha_is_ny_session (EXP-008)")

        # ============================================================
        # FACTOR 7: MOMENTUM MULTI-TIMEFRAME
        # ============================================================
        # Momentum en múltiples ventanas
        for period in [3, 6, 12]:
            df[f'alpha_mom_{period}h'] = (
                df['close_eur'] / df['close_eur'].shift(period) - 1
            ).fillna(0)
        print("  ✅ Factor 7: alpha_mom_3h/6h/12h")

        # ============================================================
        # TARGET: ÉXITO DE REVERSIÓN
        # ============================================================
        # Definimos el target como: el precio se mueve 1 ATR a favor en `lookahead` velas
        # Para una reversión LONG: close_future > close + 1.0 * atr
        # Para una reversión SHORT: close_future < close - 1.0 * atr
        future_close = df['close_eur'].shift(-lookahead)
        df['target_long'] = (
            future_close > df['close_eur'] + df['atr_eur']
        ).astype(int)
        df['target_short'] = (
            future_close < df['close_eur'] - df['atr_eur']
        ).astype(int)
        # Target combinado: 1 si hay movimiento direccional significativo
        df['target'] = (
            (future_close > df['close_eur'] + df['atr_eur']) |
            (future_close < df['close_eur'] - df['atr_eur'])
        ).astype(int)
        print(f"  ✅ Target generado (lookahead={lookahead}h, 1x ATR)")

        # ============================================================
        # LIMPIEZA FINAL (Robusta: sin dropna para no perder filas)
        # ============================================================
        # Asegurar que no haya NaN residuales en columnas esenciales
        essential_cols = [
            'alpha_divergence', 'alpha_rejection_z', 'alpha_micro_trend',
            'alpha_regime', 'alpha_near_high', 'alpha_near_low',
            'alpha_is_fixing_hour', 'alpha_mom_3h', 'target'
        ]
        # Rellenar cualquier NaN residual con 0
        df[essential_cols] = df[essential_cols].fillna(0)
        
        print(f"\n📊 Resumen del Dataset Alfa:")
        print(f"   Muestras totales: {len(df)}")
        print(f"   Factores: {len([c for c in df.columns if c.startswith('alpha_')])}")
        print(f"   Target balance: {df['target'].value_counts().to_dict()}")
        
        return df

    def _true_range(self, df: pd.DataFrame, suffix: str) -> pd.Series:
        """Calcula el True Range para un símbolo dado."""
        high = df[f'high_{suffix}']
        low = df[f'low_{suffix}']
        close = df[f'close_{suffix}']
        prev_close = close.shift(1)
        
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)
        
        return tr

    def get_feature_importance_report(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Genera un reporte de importancia de factores basado en correlación con el target.
        Útil para identificar qué factores tienen más poder predictivo.
        """
        print("\n📈 Reporte de Importancia de Factores:")
        
        # Seleccionar solo columnas alpha_ y target
        alpha_cols = [c for c in df.columns if c.startswith('alpha_')]
        
        correlations = []
        for col in alpha_cols:
            # Para variables categóricas como alpha_regime
            if df[col].dtype.name == 'category':
                for cat in df[col].cat.categories:
                    mask = (df[col] == cat)
                    corr = df.loc[mask, 'target'].mean() - df['target'].mean()
                    correlations.append({
                        'factor': f'{col}={cat}',
                        'correlation': corr,
                        'samples': mask.sum()
                    })
            else:
                corr = df[col].corr(df['target'])
                correlations.append({
                    'factor': col,
                    'correlation': corr,
                    'samples': len(df)
                })
        
        report = pd.DataFrame(correlations)
        report['abs_corr'] = report['correlation'].abs()
        report = report.sort_values('abs_corr', ascending=False)
        
        print(f"   {'Factor':<35} {'Correlación':<15} {'Muestras':<10}")
        print(f"   {'-'*60}")
        for _, row in report.head(10).iterrows():
            print(f"   {row['factor']:<35} {row['correlation']:<+15.4f} {row['samples']:<10}")
        
        return report


def main():
    """
    Ejecuta el pipeline completo del Alpha Stacker.
    """
    print("=" * 60)
    print("🔬 EXP-009: THE ALPHA STACKER")
    print("   Refinería de Factores Alfa del Laboratorio")
    print("=" * 60)
    
    # Configuración — Archivos Masivos (Fase 4: Data Muscle)
    EUR_FILE = "data/eurusd_massive_lab_data.csv"
    GOLD_FILE = "data/gold_massive_lab_data.csv"
    OUTPUT_FILE = "data/alpha_master_dataset.csv"
    LOOKAHEAD = 3  # Velas hacia adelante para el target
    
    # Pipeline
    stacker = AlphaStacker(EUR_FILE, GOLD_FILE)
    master_df = stacker.build_master_factors(lookahead=LOOKAHEAD)
    
    # Reporte de importancia
    importance = stacker.get_feature_importance_report(master_df)
    
    # Exportación
    master_df.to_csv(OUTPUT_FILE)
    print(f"\n💾 Dataset Alfa exportado a: {OUTPUT_FILE}")
    print(f"   Shape: {master_df.shape[0]} filas x {master_df.shape[1]} columnas")
    
    # Resumen de factores
    alpha_cols = [c for c in master_df.columns if c.startswith('alpha_')]
    print(f"\n📋 Factores Alfa generados ({len(alpha_cols)}):")
    for i, col in enumerate(alpha_cols, 1):
        print(f"   {i:2d}. {col}")
    
    print("\n✅ EXP-009 completado. Dataset listo para entrenamiento V2.")
    
    return master_df, importance


if __name__ == "__main__":
    main()
