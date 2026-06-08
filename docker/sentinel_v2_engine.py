import os
import sys
import joblib
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger("SentinelV2")

class SentinelV2Engine:
    def __init__(self):
        # Sincronización de rutas del laboratorio
        root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        if root_path not in sys.path:
            sys.path.insert(0, root_path)
        
        self.models_dir = os.path.join(root_path, "models")
        
        self.scaler = None
        self.pca = None
        self.model = None
        self.load_models()

    def load_models(self):
        try:
            s_path = os.path.join(self.models_dir, "market_scaler_v2.pkl")
            p_path = os.path.join(self.models_dir, "market_pca_v2.pkl")
            m_path = os.path.join(self.models_dir, "market_personality_v2.pkl")

            if os.path.exists(s_path):
                self.scaler = joblib.load(s_path)
                self.pca = joblib.load(p_path)
                self.model = joblib.load(m_path)
                logger.info(f"✅ SentinelV2: Modelos cargados desde {self.models_dir}")
            else:
                logger.warning(f"❌ SentinelV2: Archivos no encontrados en {self.models_dir}")
        except Exception as e:
            logger.error(f"❌ SentinelV2: Error en load_models: {e}")

    def evaluate(self, features_dict):
        if self.scaler is None:
            return None, True, "Modelos no cargados", {}

        try:
            # ─── 1. LIMPIEZA DE DATOS (Anti-Series Shield) ───
            clean_features = {}
            for k, v in features_dict.items():
                try:
                    # Si es una Serie de Pandas, tomamos el último valor
                    if isinstance(v, (pd.Series, pd.DataFrame)):
                        clean_features[k] = float(v.iloc[-1])
                    else:
                        clean_features[k] = float(v)
                except:
                    clean_features[k] = 0.0  # Valor neutral si falla

            # ─── 2. CONSTRUCCIÓN DEL VECTOR DE 15 DIMENSIONES (EXP-009) ───
            feature_names = self.scaler.feature_names_in_
            vector = []
            for name in feature_names:
                # Si falta una feature, buscamos en el dict o ponemos 0.0
                val = clean_features.get(name, 0.0)
                vector.append(val)

            # ─── 3. PROCESAMIENTO SKLEARN ───
            X_df = pd.DataFrame([vector], columns=feature_names)
            X_scaled = self.scaler.transform(X_df)
            X_pca = self.pca.transform(X_scaled)
            state = self.model.predict(X_pca)[0]

            # ─── 4. VEREDICTO ───
            veto = True if state == 2 else False
            reason = "Black Hole (WR 0%)" if veto else "Mercado Operable"

            # Calcular probabilidad y dirección para el orquestador
            if hasattr(self.model, 'predict_proba'):
                proba = self.model.predict_proba(X_pca)[0][1]
            else:
                proba = 0.5
            direction = "LONG" if proba > 0.5 else "SHORT"
            proba = max(proba, 1 - proba)

            return int(state), veto, reason, {
                "pca_coords": X_pca.tolist(),
                "proba": float(proba),
                "direction": direction,
            }

        except Exception as e:
            logger.error(f"❌ Error crítico en SentinelV2 evaluation: {e}")
            return None, True, f"Error: {e}", {}
