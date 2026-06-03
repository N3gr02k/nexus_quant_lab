"""
EXP-010 V2: Shadow Clustering Masivo — La Firma Institucional con Big Data
===========================================================================
Ahora con 41,342 muestras, no buscamos 4 clusters genéricos.
Buscamos los 3 ESTADOS DE LIQUIDEZ que realmente gobiernan el EURUSD.

Pipeline:
  1. Cargar alpha_master_dataset.csv (41,342 filas x 47 columnas)
  2. Extraer solo las features alpha (13 factores)
  3. PCA para reducir a 3 dimensiones (capturar 80% varianza)
  4. K-Means con 3 clusters: ACUMULACIÓN, DISTRIBUCIÓN, TENDENCIA
  5. Calcular Win Rate real de cada estado contra el target
  6. Guardar el "Mapa de Navegación" para la V8.0
"""

import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import joblib
import warnings
warnings.filterwarnings('ignore')
from datetime import datetime


class ShadowClustererV2:
    """
    La versión Big Data del Detective de Huellas.
    Con 41K muestras, encuentra los estados de liquidez con significancia estadística.
    """

    def __init__(self, file_path: str, n_clusters: int = 3):
        print("=" * 65)
        print("🎭 EXP-010 V2: SHADOW CLUSTERING MASIVO")
        print("   Buscando los 3 Estados de Liquidez del EURUSD")
        print("=" * 65)
        print(f"\n📂 Cargando dataset: {file_path}")
        
        self.df = pd.read_csv(file_path, index_col='time', parse_dates=True)
        self.n_clusters = n_clusters
        self.n_samples = len(self.df)
        print(f"   ✅ {self.n_samples:,} muestras cargadas")
        
        self.scaler = StandardScaler()
        self.pca = None
        self.kmeans = None
        self.feature_names = []
        self.state_profiles = {}

    def extract_alpha_features(self) -> pd.DataFrame:
        """
        Extrae solo las columnas alpha_* del dataset maestro.
        Estas son las 13 esencias destiladas de los EXP-001 al 008.
        
        NOTA: Ahora con el fix del Stacker (Neutral-Padding), 
        ninguna columna debería tener 100% NaN.
        """
        print("\n🔬 Extrayendo factores alfa...")
        
        # Columnas que contienen 'alpha' en el nombre
        alpha_cols = [c for c in self.df.columns if 'alpha' in c]
        
        # Excluir columnas que son 100% NaN (columna fantasma)
        valid_cols = []
        excluded = []
        for col in alpha_cols:
            if self.df[col].isna().sum() == len(self.df):
                excluded.append(col)
            else:
                valid_cols.append(col)
        
        self.feature_names = valid_cols
        
        print(f"   📊 Factores alfa encontrados: {len(alpha_cols)}")
        for col in alpha_cols:
            status = "❌ EXCLUIDA (100% NaN)" if col in excluded else "✅"
            print(f"      {status} {col}")
        
        if excluded:
            print(f"\n   🧹 Columnas excluidas por ser 100% NaN: {excluded}")
        
        X = self.df[valid_cols].copy()
        
        # FIX: One-hot encoding de alpha_regime (categórica)
        if 'alpha_regime' in X.columns:
            regime_dummies = pd.get_dummies(X['alpha_regime'], prefix='alpha_regime')
            X = pd.concat([X.drop(columns=['alpha_regime']), regime_dummies], axis=1)
            print(f"   🔄 One-hot encoding de alpha_regime: {list(regime_dummies.columns)}")
        
        # Actualizar feature_names para reflejar las columnas reales (incluyendo dummies)
        self.feature_names = list(X.columns)
        
        # Limpiar infinitos y NaN residuales
        X = X.replace([np.inf, -np.inf], np.nan)
        before = len(X)
        X = X.dropna()
        after = len(X)
        
        if before != after:
            print(f"   🧹 Limpieza: {before - after} filas con NaN/inf residuales eliminadas")
        
        print(f"\n   ✅ Features listas: {X.shape[1]} dimensiones, {len(X):,} muestras")
        return X

    def reduce_dimensions(self, X: pd.DataFrame) -> np.ndarray:
        """
        PCA para reducir dimensiones capturando el 80% de la varianza.
        Encuentra las 3 dimensiones que realmente importan.
        """
        print("\n📉 Reduciendo dimensiones con PCA (80% varianza)...")
        
        # Estandarizar
        X_scaled = self.scaler.fit_transform(X)
        
        # PCA con 80% de varianza
        self.pca = PCA(n_components=0.8)
        X_pca = self.pca.fit_transform(X_scaled)
        
        print(f"   📐 Dimensiones originales: {X.shape[1]}")
        print(f"   📐 Dimensiones reducidas: {X_pca.shape[1]}")
        print(f"   📊 Varianza explicada: {self.pca.explained_variance_ratio_.sum():.1%}")
        
        # Mostrar componentes principales
        print("\n   🧬 Componentes Principales:")
        for i, comp in enumerate(self.pca.components_):
            top_idx = np.argsort(np.abs(comp))[-3:][::-1]
            top_features = [f"{self.feature_names[j]}: {comp[j]:+.4f}" for j in top_idx]
            print(f"      PC{i+1}: {', '.join(top_features)}")
        
        return X_pca

    def find_states(self, X_pca: np.ndarray) -> np.ndarray:
        """
        K-Means para encontrar los 3 estados de liquidez del mercado.
        """
        print(f"\n🔍 Buscando {self.n_clusters} estados de liquidez...")
        
        self.kmeans = KMeans(
            n_clusters=self.n_clusters,
            random_state=42,
            n_init=10,
            max_iter=300,
            verbose=0
        )
        
        states = self.kmeans.fit_predict(X_pca)
        
        # Estadísticas de los clusters
        print(f"\n   📊 Distribución de Estados:")
        for state in sorted(np.unique(states)):
            count = (states == state).sum()
            pct = count / len(states) * 100
            print(f"      Estado {state}: {count:>8,} muestras ({pct:>5.1f}%)")
        
        return states

    def analyze_states(self, states: np.ndarray):
        """
        Analiza el Win Rate real de cada estado contra el target del dataset.
        """
        print("\n📊 ANALIZANDO EFECTIVIDAD POR ESTADO DE MERCADO...")
        print("=" * 65)
        
        df = self.df.loc[self.df.index[:len(states)]].copy()
        df['market_state'] = states
        
        # Target analysis
        if 'target' in df.columns:
            target_col = 'target'
        elif 'target_long' in df.columns:
            target_col = 'target_long'
        else:
            print("   ⚠️ No se encontró columna target. Usando forward return...")
            target_col = None
        
        results = []
        
        for state in sorted(np.unique(states)):
            mask = df['market_state'] == state
            state_df = df[mask]
            
            profile = {
                'state': int(state),
                'samples': int(mask.sum()),
                'pct': round(mask.sum() / len(df) * 100, 2),
            }
            
            # Win Rate si tenemos target
            if target_col and target_col in df.columns:
                wr = state_df[target_col].mean()
                profile['win_rate'] = round(wr * 100, 2)
                
                # Distribución de targets
                wins = int(state_df[target_col].sum())
                losses = int((1 - state_df[target_col]).sum())
                profile['wins'] = wins
                profile['losses'] = losses
                
                print(f"\n   🎭 Estado {state}:")
                print(f"      📊 Muestras: {profile['samples']:>8,} ({profile['pct']:>5.1f}%)")
                print(f"      🏆 Win Rate: {profile['win_rate']:>5.1f}%")
                print(f"      ✅ Wins: {wins:,} | ❌ Losses: {losses:,}")
                
                # Clasificar el estado
                if wr > 0.015:  # >1.5% de movimientos significativos
                    profile['classification'] = '🟢 ALTA PROBABILIDAD'
                    print(f"      🟢 CLASIFICACIÓN: ALTA PROBABILIDAD — Operar con confianza")
                elif wr > 0.008:  # >0.8% (cerca del promedio)
                    profile['classification'] = '🟡 PROBABILIDAD MEDIA'
                    print(f"      🟡 CLASIFICACIÓN: PROBABILIDAD MEDIA — Monitorear")
                else:
                    profile['classification'] = '🔴 BAJA PROBABILIDAD'
                    print(f"      🔴 CLASIFICACIÓN: BAJA PROBABILIDAD — HIBERNAR")
            
            # Perfil de microestructura del estado
            alpha_cols = [c for c in df.columns if 'alpha' in c]
            for col in alpha_cols[:5]:  # Top 5 factores
                profile[f'mean_{col}'] = round(state_df[col].mean(), 6)
            
            self.state_profiles[int(state)] = profile
            results.append(profile)
        
        return results

    def generate_navigation_map(self):
        """
        Genera el mapa de navegación para la V8.0.
        """
        print("\n\n🗺️  MAPA DE NAVEGACIÓN — V8.0")
        print("=" * 65)
        
        # Encontrar el mejor estado
        best_state = max(self.state_profiles.values(), key=lambda x: x.get('win_rate', 0))
        worst_state = min(self.state_profiles.values(), key=lambda x: x.get('win_rate', 0))
        
        print(f"\n   🏆 ESTADO DE ORO: Estado {best_state['state']}")
        print(f"      Win Rate: {best_state['win_rate']:.2f}%")
        print(f"      Muestras: {best_state['samples']:,} ({best_state['pct']:.1f}% del mercado)")
        print(f"      Clasificación: {best_state['classification']}")
        
        print(f"\n   ☠️  ESTADO TÓXICO: Estado {worst_state['state']}")
        print(f"      Win Rate: {worst_state['win_rate']:.2f}%")
        print(f"      Muestras: {worst_state['samples']:,} ({worst_state['pct']:.1f}% del mercado)")
        print(f"      Clasificación: {worst_state['classification']}")
        
        # Reglas de trading
        print(f"\n\n   📜 REGLAS DE TRADING V8.0:")
        print(f"   {'Estado':<10} {'WR':<8} {'Acción':<20} {'Confianza'}")
        print(f"   {'-'*55}")
        
        for state_id in sorted(self.state_profiles.keys()):
            p = self.state_profiles[state_id]
            wr = p.get('win_rate', 0)
            
            if wr > 1.5:
                action = "✅ OPERAR"
                conf = "ALTA"
            elif wr > 0.8:
                action = "🟡 MONITOREAR"
                conf = "MEDIA"
            else:
                action = "🔴 HIBERNAR"
                conf = "ALTA"
            
            print(f"   {state_id:<10} {wr:<8.2f}% {action:<20} {conf}")

    def save_models(self):
        """
        Guarda los modelos entrenados para uso en producción.
        """
        print("\n\n💾 Guardando modelos para producción V8.0...")
        
        joblib.dump(self.scaler, "models/market_scaler_v2.pkl")
        joblib.dump(self.pca, "models/market_pca_v2.pkl")
        joblib.dump(self.kmeans, "models/market_personality_v2.pkl")
        
        # Guardar perfiles como JSON
        import json
        profiles_serializable = {}
        for k, v in self.state_profiles.items():
            profiles_serializable[str(k)] = {str(k2): v2 for k2, v2 in v.items()}
        
        with open("models/market_states_v2.json", "w") as f:
            json.dump(profiles_serializable, f, indent=2)
        
        print(f"   ✅ market_scaler_v2.pkl — Estandarizador")
        print(f"   ✅ market_pca_v2.pkl — Reductor de dimensiones")
        print(f"   ✅ market_personality_v2.pkl — Clasificador de estados")
        print(f"   ✅ market_states_v2.json — Perfiles de estados")

    def run_pipeline(self):
        """
        Ejecuta el pipeline completo.
        """
        # 1. Extraer features
        X = self.extract_alpha_features()
        
        # 2. Reducir dimensiones
        X_pca = self.reduce_dimensions(X)
        
        # 3. Encontrar estados
        states = self.find_states(X_pca)
        
        # 4. Analizar efectividad
        results = self.analyze_states(states)
        
        # 5. Generar mapa de navegación
        self.generate_navigation_map()
        
        # 6. Guardar modelos
        self.save_models()
        
        # 7. Resumen final
        print("\n\n" + "=" * 65)
        print("🎯 RESUMEN — EXP-010 V2 COMPLETADO")
        print("=" * 65)
        
        for r in results:
            wr = r.get('win_rate', 0)
            emoji = "🟢" if wr > 1.5 else ("🟡" if wr > 0.8 else "🔴")
            print(f"\n   {emoji} Estado {r['state']}: {r['pct']:.1f}% del mercado | WR: {wr:.2f}%")
        
        print(f"\n   📊 Total muestras analizadas: {self.n_samples:,}")
        print(f"   🧠 Modelos guardados en: models/")
        print(f"   🎯 Estado de Oro: Estado {max(self.state_profiles, key=lambda x: self.state_profiles[x].get('win_rate', 0))}")
        
        return results


def main():
    """
    Punto de entrada principal.
    """
    FILE_PATH = "data/alpha_master_dataset.csv"
    
    clusterer = ShadowClustererV2(FILE_PATH, n_clusters=3)
    results = clusterer.run_pipeline()
    
    return results


if __name__ == "__main__":
    main()
