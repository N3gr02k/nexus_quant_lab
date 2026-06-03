"""
EXP-011: Regime-Aware Sniper — El Cambio de Fusil según el Mercado
===================================================================
No usamos la misma estrategia para todos los mercados.
Identificamos el "Régimen" actual (basado en los clusters del EXP-010)
y seleccionamos la estrategia óptima para ese régimen.

Concepto:
  - Mercado tranquilo (Cluster 3) → Sniper Mode (reversiones, alta precisión)
  - Tendencia bajista (Cluster 1) → Runner Mode (seguir tendencia, TP amplio)
  - Barrido de liquidez (Cluster 2) → Hibernation Mode (no operar)
  - Transición activa (Cluster 0) → Scalper Mode (trades rápidos, TP ajustado)

Pipeline:
  1. Cargar los clusters del EXP-010
  2. Para cada cluster, definir la estrategia óptima
  3. Simular trades condicionales al régimen
  4. Comparar rendimiento vs Sniper ciego
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')


class RegimeSniper:
    """
    El "Cambiador de Fusil" del Laboratorio.
    Detecta el régimen del mercado y selecciona la estrategia adecuada.
    """

    # Mapeo de regímenes a estrategias
    REGIME_STRATEGIES = {
        '⚖️ NEUTRO (Transición)': {
            'mode': 'SNIPER',
            'description': 'Reversiones en soportes/resistencias',
            'tp_atr': 1.0,      # TP conservador (MFE mediana real)
            'sl_atr': 1.5,      # SL estándar
            'max_hold': 3,       # Velas H1 máximas
            'min_confidence': 0.75,  # Confianza mínima del Sniper
            'color': '🟡'
        },
        '📉 TENDENCIA BAJISTA': {
            'mode': 'RUNNER',
            'description': 'Seguir tendencia con trailing stop',
            'tp_atr': 2.5,      # TP amplio (dejar correr)
            'sl_atr': 1.2,      # SL ajustado (menos espacio en contra)
            'max_hold': 8,       # Más velas para dejar correr
            'min_confidence': 0.70,  # Menos exigente en tendencia
            'color': '🔴'
        },
        '📈 TENDENCIA ALCISTA': {
            'mode': 'RUNNER',
            'description': 'Seguir tendencia con trailing stop',
            'tp_atr': 2.5,
            'sl_atr': 1.2,
            'max_hold': 8,
            'min_confidence': 0.70,
            'color': '🟢'
        },
        '🌀 BARRIDO DE LIQUIDEZ': {
            'mode': 'HIBERNATION',
            'description': 'No operar. Esperar 1-2 velas a que pase la tormenta',
            'tp_atr': 0,         # No aplica
            'sl_atr': 0,         # No aplica
            'max_hold': 0,       # No aplica
            'min_confidence': 1.0,  # Nunca operar
            'color': '⚫'
        },
        '🏦 ACUMULACIÓN INSTITUCIONAL': {
            'mode': 'BREAKOUT',
            'description': 'Comprar ruptura con volumen institucional',
            'tp_atr': 2.0,
            'sl_atr': 1.0,      # SL ajustado (la acumulación protege)
            'max_hold': 5,
            'min_confidence': 0.80,
            'color': '🟢'
        },
        '🏦 DISTRIBUCIÓN INSTITUCIONAL': {
            'mode': 'BREAKOUT',
            'description': 'Vender ruptura con volumen institucional',
            'tp_atr': 2.0,
            'sl_atr': 1.0,
            'max_hold': 5,
            'min_confidence': 0.80,
            'color': '🔴'
        },
        '🏦 MANIPULACIÓN (Cacería de Stops)': {
            'mode': 'COUNTER_SNIPER',
            'description': 'Operar en contra de la manipulación',
            'tp_atr': 1.5,
            'sl_atr': 1.8,      # SL más amplio (la manipulación puede extenderse)
            'max_hold': 4,
            'min_confidence': 0.85,
            'color': '🟣'
        },
        '🌫️ RUIDO (Sin dirección)': {
            'mode': 'SCALPER',
            'description': 'Trades rápidos de 1-2 velas, TP ajustado',
            'tp_atr': 0.5,      # TP muy ajustado
            'sl_atr': 0.8,      # SL ajustado
            'max_hold': 2,
            'min_confidence': 0.90,  # Máxima exigencia
            'color': '⚪'
        }
    }

    def __init__(self, clusters_file: str = "notebook_research/shadow_clusters.csv"):
        """
        Carga los clusters del EXP-010.
        """
        print("📂 Cargando clusters del EXP-010...")
        self.clusters = pd.read_csv(clusters_file, index_col=0, parse_dates=True)
        print(f"  ✅ {len(self.clusters)} muestras con clusters cargadas")

    def get_regime(self, timestamp: pd.Timestamp) -> dict:
        """
        Obtiene el régimen del mercado para un timestamp dado.
        Busca el cluster más cercano en el tiempo.
        """
        if timestamp in self.clusters.index:
            cluster_id = int(self.clusters.loc[timestamp, 'cluster'])
        else:
            # Buscar el índice más cercano
            idx = self.clusters.index.get_indexer([timestamp], method='nearest')[0]
            cluster_id = int(self.clusters.iloc[idx]['cluster'])
        
        # Obtener la personalidad del cluster
        # Necesitamos mapear cluster_id a personalidad
        # Esto debería venir del EXP-010, pero por ahora usamos un mapeo fijo
        personality_map = self._get_personality_map()
        personality = personality_map.get(cluster_id, '⚖️ NEUTRO (Transición)')
        
        strategy = self.REGIME_STRATEGIES.get(personality, self.REGIME_STRATEGIES['⚖️ NEUTRO (Transición)'])
        
        return {
            'cluster_id': cluster_id,
            'personality': personality,
            'strategy': strategy
        }

    def _get_personality_map(self) -> dict:
        """
        Mapea IDs de cluster a personalidades basado en el EXP-010.
        Este mapeo debería ser dinámico, pero por ahora es fijo.
        """
        # Basado en los resultados del EXP-010
        return {
            0: '⚖️ NEUTRO (Transición)',
            1: '📉 TENDENCIA BAJISTA',
            2: '🌀 BARRIDO DE LIQUIDEZ',
            3: '⚖️ NEUTRO (Transición)'
        }

    def evaluate_trade(self, sniper_signal: dict, timestamp: pd.Timestamp) -> dict:
        """
        Evalúa una señal del Sniper contra el régimen actual.
        
        Parámetros:
        -----------
        sniper_signal : dict
            {'direction': 'buy'/'sell', 'confidence': 0.85, 'entry': 1.1234, ...}
        timestamp : pd.Timestamp
            Momento de la señal
        
        Retorna:
        --------
        dict con veredicto y configuración de trade
        """
        regime = self.get_regime(timestamp)
        strategy = regime['strategy']
        
        verdict = {
            'timestamp': timestamp,
            'regime': regime['personality'],
            'mode': strategy['mode'],
            'approved': True,
            'reasons': [],
            'tp_atr': strategy['tp_atr'],
            'sl_atr': strategy['sl_atr'],
            'max_hold': strategy['max_hold']
        }
        
        # Regla 1: HIBERNATION — No operar bajo ningún concepto
        if strategy['mode'] == 'HIBERNATION':
            verdict['approved'] = False
            verdict['reasons'].append(f"Régimen {regime['personality']}: Modo HIBERNACIÓN activado")
            return verdict
        
        # Regla 2: Verificar confianza mínima
        if sniper_signal.get('confidence', 0) < strategy['min_confidence']:
            verdict['approved'] = False
            verdict['reasons'].append(
                f"Confianza del Sniper ({sniper_signal.get('confidence', 0):.2f}) "
                f"por debajo del mínimo requerido ({strategy['min_confidence']})"
            )
        
        # Regla 3: En modo RUNNER, solo operar en dirección de la tendencia
        if strategy['mode'] == 'RUNNER':
            if 'BAJISTA' in regime['personality'] and sniper_signal.get('direction') == 'buy':
                verdict['approved'] = False
                verdict['reasons'].append("Tendencia bajista: No comprar")
            elif 'ALCISTA' in regime['personality'] and sniper_signal.get('direction') == 'sell':
                verdict['approved'] = False
                verdict['reasons'].append("Tendencia alcista: No vender")
        
        # Regla 4: En modo COUNTER_SNIPER, operar en contra de la manipulación
        if strategy['mode'] == 'COUNTER_SNIPER':
            # La manipulación suele ser en una dirección, operamos en contra
            verdict['reasons'].append("Modo contra-manipulación: SL amplio para evitar cacería")
        
        return verdict

    def simulate_regime_trading(self, eur_file: str = "data/eurusd_lab_data.csv") -> pd.DataFrame:
        """
        Simula trades condicionales al régimen del mercado.
        Compara: Sniper ciego vs Sniper con Regime-Aware.
        """
        print("\n📊 Simulando trades con Regime-Aware Sniper...")
        
        df = pd.read_csv(eur_file, index_col='time', parse_dates=True)
        
        results = []
        
        for timestamp, row in df.iterrows():
            if timestamp not in self.clusters.index:
                continue
            
            cluster_id = int(self.clusters.loc[timestamp, 'cluster'])
            personality_map = self._get_personality_map()
            personality = personality_map.get(cluster_id, '⚖️ NEUTRO (Transición)')
            strategy = self.REGIME_STRATEGIES.get(personality, self.REGIME_STRATEGIES['⚖️ NEUTRO (Transición)'])
            
            # Simular señal del Sniper (basada en micro_trend + rejection_speed)
            micro_trend = row.get('micro_trend', 0)
            rejection_speed = row.get('rejection_speed', 0)
            tick_count = row.get('tick_count', 0)
            tick_activity = tick_count / df['tick_count'].rolling(24, min_periods=1).mean().loc[timestamp] if tick_count > 0 else 0
            
            # Señal base: combinación ponderada de señales
            # Normalizar micro_trend a [0, 1] basado en su magnitud típica
            trend_strength = min(abs(micro_trend) * 5, 1.0)  # micro_trend típico ~0.2
            speed_strength = min(abs(rejection_speed) * 0.5, 1.0)  # rejection_speed típico ~1.0
            
            # La confianza es máxima cuando ambas señales se alinean
            sniper_confidence = min(trend_strength * 0.6 + speed_strength * 0.4, 1.0)
            
            # Solo generar señal si hay suficiente convicción
            if sniper_confidence < 0.3:
                sniper_confidence = 0.0  # Sin señal
            
            sniper_direction = 'buy' if micro_trend > 0 else 'sell'
            
            # Evaluar contra régimen
            sniper_signal = {
                'direction': sniper_direction,
                'confidence': sniper_confidence
            }
            verdict = self.evaluate_trade(sniper_signal, timestamp)
            
            # Calcular retorno forward (3 velas)
            future_close = df['close'].shift(-3).loc[timestamp]
            current_close = row['close']
            if pd.notna(future_close):
                forward_return = (future_close / current_close - 1)
            else:
                forward_return = 0
            
            # Determinar si el trade habría sido ganador
            if sniper_direction == 'buy':
                trade_win = forward_return > 0
            else:
                trade_win = forward_return < 0
            
            results.append({
                'timestamp': timestamp,
                'cluster': cluster_id,
                'personality': personality,
                'mode': strategy['mode'],
                'sniper_direction': sniper_direction,
                'sniper_confidence': sniper_confidence,
                'approved': verdict['approved'],
                'forward_return': forward_return,
                'trade_win': trade_win,
                'reasons': '; '.join(verdict['reasons'])
            })
        
        results_df = pd.DataFrame(results)
        
        # Calcular métricas
        self._print_simulation_results(results_df)
        
        return results_df

    def _print_simulation_results(self, results: pd.DataFrame):
        """
        Imprime las métricas de la simulación.
        """
        total = len(results)
        approved = results['approved'].sum()
        vetoed = total - approved
        
        # Sniper ciego (todos los trades)
        blind_wins = results['trade_win'].sum()
        blind_wr = blind_wins / total * 100 if total > 0 else 0
        
        # Sniper con Regime-Aware (solo aprobados)
        approved_trades = results[results['approved']]
        regime_wins = approved_trades['trade_win'].sum()
        regime_wr = regime_wins / len(approved_trades) * 100 if len(approved_trades) > 0 else 0
        
        # Trades vetados que habrían sido pérdidas
        vetoed_trades = results[~results['approved']]
        vetoed_losses = (~vetoed_trades['trade_win']).sum()
        vetoed_total = len(vetoed_trades)
        
        print(f"\n{'='*60}")
        print(f"📊 RESULTADOS DE LA SIMULACIÓN REGIME-AWARE")
        print(f"{'='*60}")
        print(f"\n📈 MÉTRICAS GLOBALES:")
        print(f"  Total muestras: {total}")
        print(f"  Trades aprobados: {approved} ({approved/total*100:.1f}%)")
        print(f"  Trades vetados: {vetoed} ({vetoed/total*100:.1f}%)")
        
        print(f"\n🎯 WIN RATE COMPARATIVO:")
        print(f"  Sniper ciego: {blind_wins}/{total} = {blind_wr:.1f}%")
        print(f"  Regime-Aware: {regime_wins}/{len(approved_trades)} = {regime_wr:.1f}%")
        
        if regime_wr > blind_wr:
            print(f"  🏆 MEJORA: +{regime_wr - blind_wr:.1f} puntos porcentuales")
        else:
            print(f"  ⚠️ SIN MEJORA: {regime_wr - blind_wr:.1f} puntos")
        
        print(f"\n🛡️ VETOS QUE EVITARON PÉRDIDAS:")
        print(f"  Pérdidas evitadas: {vetoed_losses}/{vetoed_total} ({vetoed_losses/vetoed_total*100:.1f}% de los vetos)")
        
        # Desglose por régimen
        print(f"\n📋 DESGLOSE POR RÉGIMEN:")
        print(f"  {'Régimen':<30} {'Trades':<8} {'Aprobados':<10} {'WR':<8}")
        print(f"  {'-'*56}")
        for personality in results['personality'].unique():
            mask = results['personality'] == personality
            total_r = mask.sum()
            approved_r = results[mask & results['approved']].shape[0]
            wr_r = results[mask & results['approved']]['trade_win'].mean() * 100 if approved_r > 0 else 0
            print(f"  {personality:<30} {total_r:<8} {approved_r:<10} {wr_r:<8.1f}%")


def main():
    """
    Ejecuta el pipeline completo del Regime-Aware Sniper.
    """
    print("=" * 60)
    print("🔬 EXP-011: REGIME-AWARE SNIPER")
    print("   El Cambio de Fusil según la Personalidad del Mercado")
    print("=" * 60)
    
    # Cargar clusters del EXP-010
    sniper = RegimeSniper()
    
    # Mostrar estrategias por régimen
    print("\n📋 ESTRATEGIAS POR RÉGIMEN:")
    print(f"  {'Régimen':<35} {'Modo':<15} {'TP':<8} {'SL':<8} {'Conf. Mín':<10}")
    print(f"  {'-'*76}")
    for personality, strategy in sniper.REGIME_STRATEGIES.items():
        print(f"  {personality:<35} {strategy['mode']:<15} "
              f"{strategy['tp_atr']:<8.1f} {strategy['sl_atr']:<8.1f} "
              f"{strategy['min_confidence']:<10.2f}")
    
    # Simular trades
    results = sniper.simulate_regime_trading()
    
    # Exportar resultados
    output_file = "notebook_research/regime_sniper_results.csv"
    results.to_csv(output_file)
    print(f"\n💾 Resultados exportados a: {output_file}")
    
    print("\n✅ EXP-011 completado. Regime-Aware Sniper operativo.")
    
    return sniper, results


if __name__ == "__main__":
    main()
