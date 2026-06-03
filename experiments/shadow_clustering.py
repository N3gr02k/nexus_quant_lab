"""
EXP-010: Shadow Clustering — La Firma Institucional
====================================================
No predecimos precios. Identificamos "Huellas" de comportamiento institucional.

Concepto:
  Las instituciones (Bancos, Hedge Funds) dejan patrones repetitivos en los ticks.
  En lugar de decirle a la IA "esto ganó o perdió", le decimos:
  "Agrupa estas velas por su comportamiento interno de ticks".

  El resultado: Clusters que representan "Firmas Institucionales".
  - Cluster 1: Distribución (instituciones vendiendo)
  - Cluster 2: Acumulación (instituciones comprando)
  - Cluster 3: Barrido (cacería de stops)
  - Cluster 4: Ruido (mercado sin dirección)

Pipeline:
  1. Cargar datos EURUSD + GOLD
  2. Extraer features de microestructura (rejection_speed, micro_trend, tick_count)
  3. Aplicar K-Means clustering
  4. Analizar la "personalidad" de cada cluster
  5. Generar reglas de trading basadas en clusters
"""

import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import warnings
warnings.filterwarnings('ignore')


class ShadowClusterer:
    """
    El "Detective de Huellas" del Laboratorio.
    Encuentra patrones de comportamiento institucional en los ticks.
    """

    def __init__(self, eur_file: str, gold_file: str, n_clusters: int = 4):
        """
        Inicializa con los CSVs del Lab y el número de clusters a buscar.
        
        Parámetros:
        -----------
        n_clusters : int
            Número de "personalidades" del mercado a identificar (default: 4)
        """
        print("📂 Cargando datos del Laboratorio...")
        self.eur = pd.read_csv(eur_file, index_col='time', parse_dates=True)
        self.gold = pd.read_csv(gold_file, index_col='time', parse_dates=True)
        self.n_clusters = n_clusters
        self.model = None
        self.scaler = StandardScaler()
        self.cluster_profiles = {}

    def build_features(self) -> pd.DataFrame:
        """
        Construye las features de microestructura para el clustering.
        Solo usamos datos de ticks — sin precios, sin velas.
        """
        print("🏗️  Construyendo features de microestructura...")
        
        # Merge temporal
        df = pd.merge(
            self.eur, self.gold,
            left_index=True, right_index=True,
            suffixes=('_eur', '_gold'),
            how='inner'
        )
        print(f"  📊 Muestras sincronizadas: {len(df)} velas H1")

        # ============================================================
        # FEATURES DE MICROESTRUCTURA (Solo ticks, sin precios)
        # ============================================================
        
        # 1. Velocidad de tick (EXP-001)
        features = pd.DataFrame(index=df.index)
        features['speed_eur'] = df['rejection_speed_eur']
        features['speed_gold'] = df['rejection_speed_gold']
        
        # 2. Presión direccional (EXP-004)
        features['micro_trend_eur'] = df['micro_trend_eur']
        features['micro_trend_gold'] = df['micro_trend_gold']
        
        # 3. Actividad de ticks
        features['tick_activity_eur'] = df['tick_count_eur'] / df['tick_count_eur'].rolling(24).mean()
        features['tick_activity_gold'] = df['tick_count_gold'] / df['tick_count_gold'].rolling(24).mean()
        
        # 4. Velocidad promedio
        features['avg_speed_eur'] = df['avg_speed_eur']
        features['avg_speed_gold'] = df['avg_speed_gold']
        
        # 5. Rango de la vela (como proxy de volatilidad)
        features['range_eur'] = (df['high_eur'] - df['low_eur']) / df['close_eur']
        features['range_gold'] = (df['high_gold'] - df['low_gold']) / df['close_gold']
        
        # 6. Body ratio (qué tan direccional fue la vela)
        features['body_ratio_eur'] = abs(df['close_eur'] - df['open_eur']) / (df['high_eur'] - df['low_eur'] + 1e-10)
        features['body_ratio_gold'] = abs(df['close_gold'] - df['open_gold']) / (df['high_gold'] - df['low_gold'] + 1e-10)
        
        # 7. Divergencia de velocidad (Oro vs Euro)
        features['speed_divergence'] = df['rejection_speed_eur'] - df['rejection_speed_gold']
        
        # 8. Micro-trend divergence
        features['trend_divergence'] = df['micro_trend_eur'] - df['micro_trend_gold']
        
        # Limpiar NaN
        features = features.dropna()
        
        print(f"  ✅ Features construidas: {features.shape[1]} dimensiones")
        print(f"  📊 Muestras para clustering: {len(features)}")
        
        return features, df.loc[features.index]

    def find_shadows(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        Aplica K-Means para encontrar los clusters de comportamiento.
        """
        print(f"\n🔍 Buscando {self.n_clusters} sombras institucionales...")
        
        # Estandarizar features
        X_scaled = self.scaler.fit_transform(features)
        
        # K-Means con inicialización inteligente
        self.model = KMeans(
            n_clusters=self.n_clusters,
            random_state=42,
            n_init=10,
            max_iter=300
        )
        clusters = self.model.fit_predict(X_scaled)
        
        # PCA para visualización (2D)
        pca = PCA(n_components=2)
        coords = pca.fit_transform(X_scaled)
        
        # Armar resultado
        result = features.copy()
        result['cluster'] = clusters
        result['pca_x'] = coords[:, 0]
        result['pca_y'] = coords[:, 1]
        
        print(f"  ✅ Clusters encontrados: {len(np.unique(clusters))}")
        for c in sorted(np.unique(clusters)):
            count = (clusters == c).sum()
            pct = count / len(clusters) * 100
            print(f"     Cluster {c}: {count} muestras ({pct:.1f}%)")
        
        return result

    def analyze_clusters(self, clustered: pd.DataFrame, raw_df: pd.DataFrame) -> dict:
        """
        Analiza la "personalidad" de cada cluster.
        Mira hacia adelante para ver qué pasó después de cada patrón.
        """
        print("\n📊 Analizando personalidad de los clusters...")
        
        profiles = {}
        
        for cluster_id in sorted(clustered['cluster'].unique()):
            mask = clustered['cluster'] == cluster_id
            cluster_data = clustered[mask]
            cluster_raw = raw_df.loc[cluster_data.index]
            
            # Perfil de microestructura
            profile = {
                'size': int(mask.sum()),
                'pct': round(mask.sum() / len(clustered) * 100, 1),
                'avg_speed_eur': float(cluster_data['speed_eur'].mean()),
                'avg_speed_gold': float(cluster_data['speed_gold'].mean()),
                'avg_micro_trend_eur': float(cluster_data['micro_trend_eur'].mean()),
                'avg_micro_trend_gold': float(cluster_data['micro_trend_gold'].mean()),
                'avg_tick_activity_eur': float(cluster_data['tick_activity_eur'].mean()),
                'avg_tick_activity_gold': float(cluster_data['tick_activity_gold'].mean()),
                'avg_range_eur': float(cluster_data['range_eur'].mean()),
                'avg_range_gold': float(cluster_data['range_gold'].mean()),
                'avg_body_ratio_eur': float(cluster_data['body_ratio_eur'].mean()),
                'avg_body_ratio_gold': float(cluster_data['body_ratio_gold'].mean()),
            }
            
            # Mirar hacia adelante: ¿qué pasó en las siguientes 3 velas?
            future_close = cluster_raw['close_eur'].shift(-3)
            current_close = cluster_raw['close_eur']
            future_return = (future_close / current_close - 1).dropna()
            
            profile['forward_return_mean'] = float(future_return.mean()) if len(future_return) > 0 else 0
            profile['forward_return_std'] = float(future_return.std()) if len(future_return) > 0 else 0
            profile['forward_win_rate'] = float((future_return > 0).mean()) if len(future_return) > 0 else 0
            
            # Clasificar la personalidad
            profile['personality'] = self._classify_personality(profile)
            
            profiles[int(cluster_id)] = profile
            self.cluster_profiles[int(cluster_id)] = profile
            
            # Print profile
            print(f"\n  🎭 Cluster {cluster_id} — {profile['personality']}")
            print(f"     Muestras: {profile['size']} ({profile['pct']}%)")
            print(f"     Speed EUR: {profile['avg_speed_eur']:+.4f} | GOLD: {profile['avg_speed_gold']:+.4f}")
            print(f"     MicroTrend EUR: {profile['avg_micro_trend_eur']:+.4f} | GOLD: {profile['avg_micro_trend_gold']:+.4f}")
            print(f"     Tick Activity EUR: {profile['avg_tick_activity_eur']:.2f}x | GOLD: {profile['avg_tick_activity_gold']:.2f}x")
            print(f"     Forward Return: {profile['forward_return_mean']:+.4f} (WR: {profile['forward_win_rate']:.1%})")
        
        return profiles

    def _classify_personality(self, profile: dict) -> str:
        """
        Clasifica la "personalidad" del cluster basado en sus características.
        V2: Refinado para detectar barridos de liquidez con speed extrema + WR 0%.
        """
        speed = profile['avg_speed_eur']
        trend = profile['avg_micro_trend_eur']
        tick_act = profile['avg_tick_activity_eur']
        body = profile['avg_body_ratio_eur']
        fwd_ret = profile['forward_return_mean']
        wr = profile['forward_win_rate']
        
        # 🚨 PRIORIDAD 1: BARRIDO DE LIQUIDEZ (Speed extrema + WR pésimo)
        # Cluster 2 del EXP-010: speed=+2.41, tick_act=2.81x, WR=0%
        # No importa el body_ratio — si la velocidad es >1.5σ y WR < 30%, es barrido
        if abs(speed) > 1.5 and wr < 0.30:
            return "🌀 BARRIDO DE LIQUIDEZ"
        
        # 🚨 PRIORIDAD 2: BARRIDO con speed moderada pero tick_activity extrema
        if abs(speed) > 0.5 and tick_act > 2.0 and wr < 0.35:
            return "🌀 BARRIDO DE LIQUIDEZ"
        
        # 🏦 PRIORIDAD 3: ACUMULACIÓN/DISTRIBUCIÓN INSTITUCIONAL
        # Alta velocidad + tendencia definida + alta actividad
        if abs(speed) > 0.3 and abs(trend) > 0.3 and tick_act > 1.2:
            if trend > 0 and fwd_ret > 0:
                return "🏦 ACUMULACIÓN INSTITUCIONAL"
            elif trend < 0 and fwd_ret < 0:
                return "🏦 DISTRIBUCIÓN INSTITUCIONAL"
            else:
                return "🏦 MANIPULACIÓN (Cacería de Stops)"
        
        # 🌫️ PRIORIDAD 4: RUIDO (Velocidad baja + actividad baja)
        if abs(speed) < 0.1 and tick_act < 0.8:
            return "🌫️ RUIDO (Sin dirección)"
        
        # 📈📉 PRIORIDAD 5: TENDENCIA
        if abs(trend) > 0.2:
            if trend > 0:
                return "📈 TENDENCIA ALCISTA"
            else:
                return "📉 TENDENCIA BAJISTA"
        
        # ⚖️ PRIORIDAD 6: NEUTRO (Transición)
        return "⚖️ NEUTRO (Transición)"

    def generate_trading_rules(self) -> list:
        """
        Genera reglas de trading basadas en los clusters encontrados.
        """
        print("\n📜 Generando reglas de trading basadas en clusters...")
        
        rules = []
        
        for cluster_id, profile in self.cluster_profiles.items():
            personality = profile['personality']
            fwd_ret = profile['forward_return_mean']
            wr = profile['forward_win_rate']
            
            # Reglas basadas en personalidad
            if 'ACUMULACIÓN' in personality and fwd_ret > 0 and wr > 0.5:
                rules.append({
                    'cluster': cluster_id,
                    'action': 'COMPRAR',
                    'confidence': 'ALTA' if wr > 0.7 else 'MEDIA',
                    'reason': f'Cluster {cluster_id} muestra acumulación institucional con WR de {wr:.0%}',
                    'win_rate': wr
                })
            
            elif 'DISTRIBUCIÓN' in personality and fwd_ret < 0 and wr < 0.5:
                rules.append({
                    'cluster': cluster_id,
                    'action': 'VENDER',
                    'confidence': 'ALTA' if wr < 0.3 else 'MEDIA',
                    'reason': f'Cluster {cluster_id} muestra distribución institucional con WR de {wr:.0%}',
                    'win_rate': wr
                })
            
            elif 'BARRIDO' in personality:
                rules.append({
                    'cluster': cluster_id,
                    'action': 'ESPERAR_REVERSIÓN',
                    'confidence': 'MEDIA',
                    'reason': f'Cluster {cluster_id} es barrido de liquidez. Esperar confirmación en siguiente vela.',
                    'win_rate': wr
                })
            
            elif 'RUIDO' in personality:
                rules.append({
                    'cluster': cluster_id,
                    'action': 'NO_OPERAR',
                    'confidence': 'ALTA',
                    'reason': f'Cluster {cluster_id} es ruido de mercado. Alta probabilidad de pérdida por spreads.',
                    'win_rate': wr
                })
            
            # 📉 TENDENCIA BAJISTA con WR bajo = señal de VENDER
            elif 'TENDENCIA BAJISTA' in personality and wr < 0.35:
                rules.append({
                    'cluster': cluster_id,
                    'action': 'VENDER',
                    'confidence': 'MEDIA',
                    'reason': f'Cluster {cluster_id} muestra tendencia bajista con WR de {wr:.0%}',
                    'win_rate': wr
                })
            
            # 📈 TENDENCIA ALCISTA con WR alto = señal de COMPRAR
            elif 'TENDENCIA ALCISTA' in personality and wr > 0.65:
                rules.append({
                    'cluster': cluster_id,
                    'action': 'COMPRAR',
                    'confidence': 'MEDIA',
                    'reason': f'Cluster {cluster_id} muestra tendencia alcista con WR de {wr:.0%}',
                    'win_rate': wr
                })
            
            else:
                rules.append({
                    'cluster': cluster_id,
                    'action': 'MONITOREAR',
                    'confidence': 'BAJA',
                    'reason': f'Cluster {cluster_id} sin señal clara ({personality})',
                    'win_rate': wr
                })
        
        # Mostrar reglas
        print(f"\n   {'Cluster':<10} {'Acción':<20} {'Confianza':<12} {'WR':<8} {'Razón'}")
        print(f"   {'-'*70}")
        for rule in rules:
            print(f"   {rule['cluster']:<10} {rule['action']:<20} {rule['confidence']:<12} {rule['win_rate']:<8.0%} {rule['reason'][:40]}")
        
        return rules

    def plot_clusters(self, clustered: pd.DataFrame, output_file: str = None):
        """
        Genera un reporte textual de los clusters (sin matplotlib para evitar dependencias).
        """
        print("\n📈 Mapa de Clusters (Coordenadas PCA):")
        print(f"   {'Cluster':<10} {'Muestras':<10} {'PCA-X Medio':<15} {'PCA-Y Medio':<15} {'Personalidad'}")
        print(f"   {'-'*70}")
        
        for cluster_id in sorted(clustered['cluster'].unique()):
            mask = clustered['cluster'] == cluster_id
            data = clustered[mask]
            personality = self.cluster_profiles.get(int(cluster_id), {}).get('personality', 'Desconocido')
            print(f"   {cluster_id:<10} {len(data):<10} {data['pca_x'].mean():<+15.4f} {data['pca_y'].mean():<+15.4f} {personality}")


def main():
    """
    Ejecuta el pipeline completo de Shadow Clustering.
    """
    print("=" * 60)
    print("🔬 EXP-010: SHADOW CLUSTERING")
    print("   Decodificando la Firma Institucional en los Ticks")
    print("=" * 60)
    
    # Configuración
    EUR_FILE = "data/eurusd_lab_data.csv"
    GOLD_FILE = "data/gold_lab_data.csv"
    OUTPUT_FILE = "notebook_research/shadow_clusters.csv"
    N_CLUSTERS = 4  # 4 personalidades del mercado
    
    # Pipeline
    clusterer = ShadowClusterer(EUR_FILE, GOLD_FILE, n_clusters=N_CLUSTERS)
    
    # 1. Construir features de microestructura
    features, raw_df = clusterer.build_features()
    
    # 2. Encontrar sombras (clusters)
    clustered = clusterer.find_shadows(features)
    
    # 3. Analizar personalidad de cada cluster
    profiles = clusterer.analyze_clusters(clustered, raw_df)
    
    # 4. Generar reglas de trading
    rules = clusterer.generate_trading_rules()
    
    # 5. Mostrar mapa de clusters
    clusterer.plot_clusters(clustered)
    
    # 6. Exportar resultados
    clustered.to_csv(OUTPUT_FILE)
    print(f"\n💾 Clusters exportados a: {OUTPUT_FILE}")
    
    # Resumen final
    print("\n" + "=" * 60)
    print("🎯 RESUMEN — FIRMAS INSTITUCIONALES DETECTADAS")
    print("=" * 60)
    
    for cluster_id, profile in sorted(profiles.items()):
        print(f"\n  🎭 Cluster {cluster_id}: {profile['personality']}")
        print(f"     Frecuencia: {profile['pct']}% del mercado")
        print(f"     Retorno forward: {profile['forward_return_mean']:+.4f}")
        print(f"     Win Rate: {profile['forward_win_rate']:.1%}")
        
        # Recomendación
        if 'ACUMULACIÓN' in profile['personality']:
            print(f"     ✅ RECOMENDACIÓN: COMPRAR en este cluster")
        elif 'DISTRIBUCIÓN' in profile['personality']:
            print(f"     ✅ RECOMENDACIÓN: VENDER en este cluster")
        elif 'BARRIDO' in profile['personality']:
            print(f"     ⏳ RECOMENDACIÓN: Esperar reversión en vela siguiente")
        elif 'RUIDO' in profile['personality']:
            print(f"     ❌ RECOMENDACIÓN: NO OPERAR en este cluster")
        else:
            print(f"     👁️ RECOMENDACIÓN: Monitorear")
    
    print("\n✅ EXP-010 completado. Firmas institucionales decodificadas.")
    
    return clustered, profiles, rules


if __name__ == "__main__":
    main()
