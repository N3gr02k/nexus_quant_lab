"""
🚀 EXP-017: LAB LIVE ORCHESTRATOR — Simulacro de Guerra
=========================================================
Misión: Unificar toda la inteligencia del Nexus Quant Lab en un solo flujo
que simula un entorno de producción en vivo.

Pipeline Completo:
  1. Cargar datos más recientes del AlphaStacker
  2. PASO A — Personality Check (SentinelV2Engine): ¿Estado de Mercado?
  3. PASO B — Alpha Brain V2 (XGBoost): ¿Confianza del Cerebro?
  4. PASO C — Sentinel Council V2 (Vetos): ¿Veto del Consejo?
  5. Reporte unificado de señales para EURUSD y GOLD

Output:
  - Consola con diagnóstico completo del mercado
  - data/lab_live_signals.csv → Señales generadas por el pipeline

Autor: Nexus Quant Lab
Fecha: 2026-06-01
"""

import sys
import os
import pandas as pd
import numpy as np
import json
import joblib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple, Optional, List

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Añadir directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from production.sentinel_v2_engine import SentinelV2Engine
from models.sentinel_council import SentinelCouncilV2


class LabLiveOrchestrator:
    """
    Orquestador de Inteligencia V2 — Simulacro de Guerra.
    
    Une las 3 capas del sistema en un solo flujo de decisión:
      - Personalidad (SentinelV2Engine)
      - Predicción (AlphaBrainV2)
      - Vetos (SentinelCouncilV2)
    """

    def __init__(self):
        self.brains = {}       # Modelos XGBoost por símbolo
        self.features_map = {} # Lista de features por símbolo
        self.personality = SentinelV2Engine()
        self.council = SentinelCouncilV2()
        self._loaded = False

    def load_all(self) -> bool:
        """
        Carga todos los modelos del sistema.
        
        Returns:
            True si todo se cargó correctamente
        """
        logger.info("=" * 60)
        logger.info("🧠 LAB LIVE ORCHESTRATOR — CARGANDO INTELIGENCIA V2")
        logger.info("=" * 60)

        # 1. Cargar Cerebros V2 (XGBoost)
        for symbol in ["EURUSD", "GOLD"]:
            model_path = f"models/{symbol.lower()}_alpha_brain_v2.pkl"
            features_path = f"models/{symbol.lower()}_alpha_features_v2.json"

            if not os.path.exists(model_path):
                logger.error(f"❌ Cerebro {symbol} no encontrado: {model_path}")
                logger.error("   Ejecuta: python models/train_alpha_sniper_v2.py")
                return False

            self.brains[symbol] = joblib.load(model_path)
            logger.info(f"   ✅ Cerebro {symbol} cargado")

            if os.path.exists(features_path):
                with open(features_path, "r") as f:
                    data = json.load(f)
                self.features_map[symbol] = data["features"]
                logger.info(f"   ✅ Features {symbol}: {len(data['features'])} factores")

        # 2. Cargar Personalidad (SentinelV2Engine)
        logger.info("\n🔍 Cargando Personalidad del Mercado...")
        if not self.personality.load_models():
            logger.warning("   ⚠️  Personalidad no disponible — se omitirá capa de estado")

        # 3. Inicializar Consejo (SentinelCouncilV2)
        logger.info("\n🛡️ Inicializando Consejo de Centinelas...")
        # El consejo ya se inicializó en __init__

        self._loaded = True
        logger.info("\n✅ SISTEMA LISTO — Inteligencia V2 Operativa")
        return True

    def _get_latest_alpha_features(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Obtiene las features alfa más recientes del AlphaStacker.
        
        Args:
            symbol: "EURUSD" o "GOLD"
            
        Returns:
            DataFrame con las últimas filas de features, o None si no hay datos
        """
        master_path = "data/alpha_master_dataset.csv"
        if not os.path.exists(master_path):
            logger.error(f"❌ Dataset maestro no encontrado: {master_path}")
            logger.error("   Ejecuta: python data_factory/alpha_stacker.py")
            return None

        df = pd.read_csv(master_path, index_col='time', parse_dates=True)

        # Codificar alpha_regime si está presente
        if 'alpha_regime' in df.columns:
            regime_map = {'normal': 0, 'high_vol': 1, 'low_vol': 2}
            df['alpha_regime'] = df['alpha_regime'].map(regime_map).fillna(0)

        # Para GOLD, filtrar filas con datos
        if symbol == "GOLD":
            gold_features = [c for c in df.columns if 'gold' in c and c.startswith('alpha_')]
            mask = (df[gold_features].abs().sum(axis=1) > 0)
            df = df[mask].copy()

        # Seleccionar solo las features que necesita el cerebro
        features_list = self.features_map.get(symbol, [])
        available = [f for f in features_list if f in df.columns]
        missing = [f for f in features_list if f not in df.columns]

        if missing:
            logger.warning(f"   ⚠️  Features faltantes para {symbol}: {missing}")
            for f in missing:
                df[f] = 0.0

        X = df[features_list].copy()

        # Limpiar infinitos y NaNs
        X = X.replace([np.inf, -np.inf], np.nan)
        X = X.fillna(X.mean()).fillna(0)

        logger.info(f"   📊 {symbol}: {len(X)} filas de features listas")
        return X

    def _get_personality_features(self, row: pd.Series) -> Dict[str, float]:
        """
        Convierte una fila del dataset en el diccionario de features
        que espera el SentinelV2Engine.
        
        Args:
            row: Fila del DataFrame con columnas alpha_*
            
        Returns:
            Diccionario con features para el engine de personalidad
        """
        # Mapear de columnas del dataset a features del engine
        # El engine espera one-hot para regime, no label-encoded
        regime_val = row.get('alpha_regime', 0)
        
        features = {
            'alpha_divergence': float(row.get('alpha_divergence', 0)),
            'alpha_rejection_z': float(row.get('alpha_rejection_z', 0)),
            'alpha_rejection_z_gold': float(row.get('alpha_rejection_z_gold', 0)),
            'alpha_micro_trend': float(row.get('alpha_micro_trend', 0)),
            'alpha_micro_trend_gold': float(row.get('alpha_micro_trend_gold', 0)),
            'alpha_near_high': float(row.get('alpha_near_high', 0)),
            'alpha_near_low': float(row.get('alpha_near_low', 0)),
            'alpha_is_fixing_hour': float(row.get('alpha_is_fixing_hour', 0)),
            'alpha_is_ny_session': float(row.get('alpha_is_ny_session', 0)),
            'alpha_mom_3h': float(row.get('alpha_mom_3h', 0)),
            'alpha_mom_6h': float(row.get('alpha_mom_6h', 0)),
            'alpha_mom_12h': float(row.get('alpha_mom_12h', 0)),
            # One-hot encoding para regime
            'alpha_regime_high_vol': 1.0 if regime_val == 1 else 0.0,
            'alpha_regime_low_vol': 1.0 if regime_val == 2 else 0.0,
            'alpha_regime_normal': 1.0 if regime_val == 0 else 0.0,
        }
        return features

    def _get_whale_features(self, row: pd.Series, symbol: str) -> Dict:
        """
        Extrae features de ballena de una fila para el Consejo.
        
        Args:
            row: Fila del DataFrame
            symbol: "EURUSD" o "GOLD"
            
        Returns:
            Dict con tick_vol_std, rejection_speed, absorption_z
        """
        suffix = '_eur' if symbol == 'EURUSD' else '_gold'
        
        # Calcular tick_vol_std aproximado desde los datos disponibles
        tick_count = float(row.get(f'tick_count{suffix}', 0))
        
        # rejection_speed directo
        rejection_speed = float(row.get(f'rejection_speed{suffix}', 0))
        
        # absorption_z aproximado
        price_range = float(row.get(f'high{suffix}', 0)) - float(row.get(f'low{suffix}', 0))
        if price_range <= 0:
            price_range = 1e-10
        absorption_ratio = tick_count / price_range
        
        return {
            'tick_vol_std': tick_count / 1000,  # Normalización aproximada
            'rejection_speed': rejection_speed,
            'absorption_z': absorption_ratio / 100,  # Normalización aproximada
        }

    def scan_market(self, symbol: str, n_latest: int = 10) -> List[Dict]:
        """
        Escanea el mercado con toda la inteligencia V2.
        
        Pipeline:
          1. Obtener features alfa más recientes
          2. Para cada fila:
             a. Personality Check → Estado de mercado
             b. Alpha Brain → Predicción de movimiento
             c. Whale Check → Detección de ballenas
             d. Council → Veredicto final
          3. Compilar reporte
        
        Args:
            symbol: "EURUSD" o "GOLD"
            n_latest: Número de filas más recientes a escanear
            
        Returns:
            Lista de dicts con resultados del escaneo
        """
        if not self._loaded:
            logger.error("❌ Sistema no cargado. Ejecuta load_all() primero.")
            return []

        logger.info(f"\n{'='*60}")
        logger.info(f"🔬 ESCANEANDO MERCADO — {symbol}")
        logger.info(f"{'='*60}")

        # 1. Obtener features
        X = self._get_latest_alpha_features(symbol)
        if X is None or len(X) == 0:
            logger.error(f"❌ No hay datos para {symbol}")
            return []

        # Tomar las últimas n filas
        X_latest = X.tail(n_latest)
        logger.info(f"   📡 Escaneando últimas {len(X_latest)} velas...")

        # 2. Cargar dataset completo para features adicionales
        master_df = pd.read_csv("data/alpha_master_dataset.csv", index_col='time', parse_dates=True)

        results = []
        for idx, (timestamp, row) in enumerate(X_latest.iterrows()):
            logger.info(f"\n   ─── Vela {idx+1}/{len(X_latest)}: {timestamp} ───")

            # Obtener fila completa del master
            if timestamp in master_df.index:
                full_row = master_df.loc[timestamp]
            else:
                full_row = row

            # ──────────────────────────────────────────
            # PASO A: Personality Check
            # ──────────────────────────────────────────
            personality_features = self._get_personality_features(row)
            state, veto, reason, details = self.personality.evaluate(personality_features)
            
            state_emoji = "🔴" if state == 2 else "🟢"
            logger.info(f"   {state_emoji} [PASO A] Estado: {state} | {reason}")

            # ──────────────────────────────────────────
            # PASO B: Alpha Brain Prediction
            # ──────────────────────────────────────────
            brain = self.brains.get(symbol)
            if brain is not None:
                # Preparar features en el orden exacto que espera el modelo
                features_list = self.features_map.get(symbol, [])
                X_pred = pd.DataFrame([row[features_list].values], columns=features_list)
                
                proba = brain.predict_proba(X_pred)[0, 1]
                pred = brain.predict(X_pred)[0]
                
                confidence = proba if pred == 1 else 1 - proba
                
                pred_emoji = "🟢" if pred == 1 else "🔴"
                logger.info(f"   {pred_emoji} [PASO B] Predicción: {'MOVIMIENTO' if pred == 1 else 'SIN MOVIMIENTO'} (confianza: {confidence:.2%})")
                logger.info(f"      Probabilidad alfa: {proba:.4f}")
            else:
                proba = 0.5
                pred = 0
                confidence = 0.5
                logger.warning(f"   ⚠️  [PASO B] Cerebro no disponible para {symbol}")

            # ──────────────────────────────────────────
            # PASO C: Whale Check + Council Verdict
            # ──────────────────────────────────────────
            whale_features = self._get_whale_features(full_row, symbol)
            
            verdict = self.council.verify_order(
                symbol=symbol,
                proba=confidence,
                rejection_speed=whale_features['rejection_speed'],
                volume_delta=whale_features['tick_vol_std'],
                regime="NEUTRO",  # Simplificado para el escaneo
                tick_vol_std=whale_features['tick_vol_std'],
                absorption_z=whale_features['absorption_z'],
            )

            verdict_emoji = "✅" if verdict.approved else "❌"
            boost_text = f" + BOOST {verdict.boost_amount:.0%}" if verdict.boost else ""
            logger.info(f"   {verdict_emoji} [PASO C] Consejo: {'APROBADO' if verdict.approved else 'VETADO'}{boost_text}")
            logger.info(f"      Razón: {verdict.reason}")

            # ──────────────────────────────────────────
            # COMPILAR RESULTADO
            # ──────────────────────────────────────────
            result = {
                'timestamp': timestamp,
                'symbol': symbol,
                'market_state': state,
                'state_description': reason,
                'state_veto': veto,
                'alpha_probability': round(proba, 4),
                'alpha_prediction': int(pred),
                'alpha_confidence': round(confidence, 4),
                'whale_detected': verdict.details.get('whale_detected', False),
                'council_approved': verdict.approved,
                'council_reason': verdict.reason,
                'council_boost': verdict.boost,
                'council_boost_amount': verdict.boost_amount,
                'final_signal': 1 if (pred == 1 and verdict.approved and not veto) else 0,
            }
            results.append(result)

        # Reporte resumen
        self._print_summary(symbol, results)
        return results

    def _print_summary(self, symbol: str, results: List[Dict]):
        """
        Imprime un resumen del escaneo.
        """
        if not results:
            return

        df = pd.DataFrame(results)
        n_total = len(df)
        n_signals = df['final_signal'].sum()
        n_approved = df['council_approved'].sum()
        n_vetoed = n_total - n_approved
        n_boosted = df['council_boost'].sum()
        n_blackhole = df['state_veto'].sum()

        logger.info(f"\n{'='*60}")
        logger.info(f"📊 RESUMEN — {symbol}")
        logger.info(f"{'='*60}")
        logger.info(f"   Velas escaneadas:          {n_total}")
        logger.info(f"   Señales generadas:         {n_signals}")
        logger.info(f"   Aprobadas por Consejo:     {n_approved}")
        logger.info(f"   Vetadas por Consejo:       {n_vetoed}")
        logger.info(f"   Boost por Ballena (GOLD):  {n_boosted}")
        logger.info(f"   Black Holes detectados:    {n_blackhole}")
        logger.info(f"   Tasa de señal:             {n_signals/n_total:.1%}" if n_total > 0 else "   Tasa de señal: N/A")

        if n_signals > 0:
            avg_conf = df[df['final_signal'] == 1]['alpha_confidence'].mean()
            logger.info(f"   Confianza promedio:        {avg_conf:.2%}")

    def run_full_scan(self, n_latest: int = 20) -> Dict[str, List[Dict]]:
        """
        Ejecuta escaneo completo para EURUSD y GOLD.
        
        Args:
            n_latest: Número de velas a escanear por símbolo
            
        Returns:
            Dict con resultados por símbolo
        """
        logger.info("\n" + "=" * 60)
        logger.info("🚀 EXP-017: LAB LIVE ORCHESTRATOR — SIMULACRO DE GUERRA")
        logger.info("=" * 60)
        logger.info(f"📡 Escaneando últimas {n_latest} velas de cada activo...")
        logger.info(f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")

        if not self._loaded:
            if not self.load_all():
                logger.error("❌ No se pudo cargar el sistema. Abortando.")
                return {}

        all_results = {}

        for symbol in ["EURUSD", "GOLD"]:
            results = self.scan_market(symbol, n_latest)
            all_results[symbol] = results

        # Guardar resultados a CSV
        self._save_results(all_results)

        # Resumen final
        self._print_final_summary(all_results)
        return all_results

    def _save_results(self, all_results: Dict[str, List[Dict]]):
        """
        Guarda los resultados del escaneo a CSV.
        """
        all_dfs = []
        for symbol, results in all_results.items():
            if results:
                df = pd.DataFrame(results)
                all_dfs.append(df)

        if all_dfs:
            combined = pd.concat(all_dfs, ignore_index=True)
            output_path = "data/lab_live_signals.csv"
            combined.to_csv(output_path, index=False)
            logger.info(f"\n💾 Resultados guardados: {output_path}")
            logger.info(f"   Total señales: {combined['final_signal'].sum()}/{len(combined)}")

    def _print_final_summary(self, all_results: Dict[str, List[Dict]]):
        """
        Imprime el resumen final del simulacro.
        """
        logger.info("\n" + "=" * 60)
        logger.info("🏁 RESUMEN FINAL — SIMULACRO DE GUERRA COMPLETADO")
        logger.info("=" * 60)

        for symbol, results in all_results.items():
            if not results:
                continue
            df = pd.DataFrame(results)
            n_signals = df['final_signal'].sum()
            n_boosted = df['council_boost'].sum()
            n_blackhole = df['state_veto'].sum()

            logger.info(f"\n   {symbol}:")
            logger.info(f"      📡 Velas: {len(df)}")
            logger.info(f"      🎯 Señales: {n_signals}")
            logger.info(f"      🐋 Boosts: {n_boosted}")
            logger.info(f"      ⚫ Black Holes: {n_blackhole}")

        logger.info(f"\n{'='*60}")
        logger.info("✅ EXP-017 COMPLETADO — Sistema listo para producción V8.2")
        logger.info(f"{'='*60}")


def main():
    """
    Punto de entrada principal.
    """
    orchestrator = LabLiveOrchestrator()
    
    # Cargar todo el sistema
    if not orchestrator.load_all():
        logger.error("❌ Error fatal cargando el sistema. Abortando.")
        sys.exit(1)

    # Escanear mercado
    results = orchestrator.run_full_scan(n_latest=20)

    # Mostrar señales más recientes
    for symbol, signals in results.items():
        if signals:
            latest = signals[-1]
            print(f"\n   🎯 Última señal {symbol}:")
            print(f"      Hora: {latest['timestamp']}")
            print(f"      Estado: {latest['state_description']}")
            print(f"      Confianza Alfa: {latest['alpha_confidence']:.2%}")
            print(f"      Consejo: {'APROBADO' if latest['council_approved'] else 'VETADO'}")
            if latest['council_boost']:
                print(f"      🐋 BOOST ACTIVO: +{latest['council_boost_amount']:.0%}")
            print(f"      Señal Final: {'🟢 COMPRAR' if latest['final_signal'] == 1 else '🔴 ESPERAR'}")


if __name__ == "__main__":
    main()
