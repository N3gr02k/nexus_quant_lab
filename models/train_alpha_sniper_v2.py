"""
🧠 EXP-016: Alpha Brain V2 — Entrenamiento Final
=================================================
Misión: Entrenar un modelo XGBoost que aprenda directamente de los 13 Factores Alfa
construidos en el AlphaStacker (EXP-009). Dejar de usar velas → usar probabilidad pura
basada en microestructura institucional.

Pipeline:
  1. Carga alpha_master_dataset.csv (41,342 filas, 13 factores alfa)
  2. Selecciona columnas 'alpha_*' como features
  3. Entrena XGBoost con validación cross-temporal (TimeSeriesSplit)
  4. Guarda modelo .pkl + lista de features .json
  5. Evalúa importancia de factores y reporta métricas

Output:
  - models/eurusd_alpha_brain_v2.pkl   → Modelo XGBoost entrenado
  - models/eurusd_alpha_features_v2.json → Lista de features usadas
  - models/gold_alpha_brain_v2.pkl     → Modelo XGBoost para GOLD
  - models/gold_alpha_features_v2.json  → Lista de features para GOLD
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
import json
import os
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report, roc_auc_score, confusion_matrix


def load_and_prepare_data(symbol: str):
    """
    Carga el dataset maestro y prepara features/target.
    Para EURUSD usa el dataset completo.
    Para GOLD filtra solo filas donde GOLD tenga datos.
    """
    print(f"📂 Cargando alpha_master_dataset.csv para {symbol}...")
    df = pd.read_csv("data/alpha_master_dataset.csv", index_col='time', parse_dates=True)
    print(f"   Dataset completo: {len(df)} filas")

    # Seleccionar features alfa
    features = sorted([c for c in df.columns if c.startswith('alpha_')])
    print(f"   Features alfa disponibles: {len(features)}")

    # Codificar alpha_regime (categórica → numérica)
    if 'alpha_regime' in features:
        regimes = df['alpha_regime'].unique()
        regime_map = {r: i for i, r in enumerate(regimes)}
        df['alpha_regime'] = df['alpha_regime'].map(regime_map)
        print(f"   alpha_regime codificada: {regime_map}")

    # Para GOLD, filtrar filas donde los features de GOLD no sean cero (tiene datos)
    if symbol == "GOLD":
        gold_features = [c for c in features if 'gold' in c]
        # Mantener filas donde al menos un feature de GOLD sea distinto de cero
        mask = (df[gold_features].abs().sum(axis=1) > 0)
        df = df[mask].copy()
        print(f"   Filas con datos de GOLD: {len(df)}")

    X = df[features].astype(float)
    y = df['target']

    # Limpiar infinitos y NaNs
    X = X.replace([np.inf, -np.inf], np.nan)
    # Rellenar NaNs con la media de cada columna
    X = X.fillna(X.mean())
    # Si aún quedan NaNs (columnas completamente vacías), rellenar con 0
    X = X.fillna(0)

    # Asegurar que y también esté limpio
    y = y.fillna(0).astype(int)

    # Estadísticas del target
    pos_ratio = y.mean()
    print(f"   Target balance: {y.sum()}/{len(y)} ({pos_ratio:.4%} positivos)")

    return X, y, features


def train_model(X, y, symbol: str):
    """
    Entrena XGBoost con validación cross-temporal.
    """
    print(f"\n🧠 Entrenando Alpha Brain V2 para {symbol}...")

    # Balanceo automático
    scale_pos_weight = (y == 0).sum() / max(y.sum(), 1)
    print(f"   Scale pos weight: {scale_pos_weight:.2f}")

    model = xgb.XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.01,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        objective='binary:logistic',
        tree_method='hist',
        random_state=42,
        early_stopping_rounds=50,
        eval_metric='auc'
    )

    # Validación cross-temporal (5 folds)
    tscv = TimeSeriesSplit(n_splits=5)
    auc_scores = []
    feature_importances = []

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False
        )

        y_pred_proba = model.predict_proba(X_val)[:, 1]
        auc = roc_auc_score(y_val, y_pred_proba)
        auc_scores.append(auc)
        feature_importances.append(model.feature_importances_)

        print(f"   Fold {fold+1}/5: AUC = {auc:.4f}")

    # Métricas promedio
    mean_auc = np.mean(auc_scores)
    std_auc = np.std(auc_scores)
    print(f"\n   📊 AUC promedio: {mean_auc:.4f} ± {std_auc:.4f}")

    # Re-entrenar modelo final con todos los datos (sin early_stopping)
    print(f"   Re-entrenando modelo final con todos los datos...")
    model.fit(X, y, eval_set=[(X, y)], verbose=False)

    # Importancia de features (promedio sobre folds)
    avg_importance = np.mean(feature_importances, axis=0)
    importance_df = pd.DataFrame({
        'feature': X.columns,
        'importance': avg_importance
    }).sort_values('importance', ascending=False)

    print(f"\n   🔝 Top 5 factores alfa más importantes:")
    for i, row in importance_df.head(5).iterrows():
        print(f"      {i+1}. {row['feature']}: {row['importance']:.4f}")

    return model, importance_df, mean_auc


def save_model(model, features, symbol: str, auc: float):
    """
    Guarda el modelo y la lista de features.
    """
    model_path = f"models/{symbol.lower()}_alpha_brain_v2.pkl"
    features_path = f"models/{symbol.lower()}_alpha_features_v2.json"

    joblib.dump(model, model_path)
    print(f"   ✅ Modelo guardado: {model_path}")

    features_data = {
        'features': features,
        'auc': round(auc, 4),
        'symbol': symbol,
        'timestamp': pd.Timestamp.now().isoformat()
    }
    with open(features_path, 'w') as f:
        json.dump(features_data, f, indent=2)
    print(f"   ✅ Features guardadas: {features_path}")


def evaluate_model(model, X, y, symbol: str):
    """
    Evaluación final del modelo en todo el dataset.
    """
    y_pred = model.predict(X)
    y_proba = model.predict_proba(X)[:, 1]

    print(f"\n   📋 Reporte de clasificación ({symbol}):")
    print(classification_report(y, y_pred, target_names=['Sin movimiento', 'Movimiento'], zero_division=0))

    tn, fp, fn, tp = confusion_matrix(y, y_pred).ravel()
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)

    print(f"   🎯 Precisión (movimiento): {precision:.2%}")
    print(f"   🎯 Recall (movimiento):    {recall:.2%}")
    print(f"   🎯 Especificidad:          {specificity:.2%}")
    print(f"   🎯 AUC-ROC:                {roc_auc_score(y, y_proba):.4f}")

    return {
        'precision': precision,
        'recall': recall,
        'specificity': specificity,
        'auc': roc_auc_score(y, y_proba)
    }


def train_alpha_v2(symbol: str):
    """
    Pipeline completo de entrenamiento para un símbolo.
    """
    print(f"\n{'='*60}")
    print(f"🧠 EXP-016: Alpha Brain V2 — {symbol}")
    print(f"{'='*60}")

    # 1. Cargar datos
    X, y, features = load_and_prepare_data(symbol)

    if len(X) < 100:
        print(f"❌ Datos insuficientes para {symbol}: {len(X)} filas. Se necesitan al menos 100.")
        return None

    # 2. Entrenar modelo
    model, importance_df, auc = train_model(X, y, symbol)

    # 3. Guardar modelo
    save_model(model, features, symbol, auc)

    # 4. Evaluar
    metrics = evaluate_model(model, X, y, symbol)

    # 5. Guardar importancia de features
    imp_path = f"models/{symbol.lower()}_feature_importance.csv"
    importance_df.to_csv(imp_path, index=False)
    print(f"   ✅ Importancia guardada: {imp_path}")

    print(f"\n   🏆 Entrenamiento completado para {symbol}!")
    return model, metrics


def main():
    """
    Entrena Alpha Brain V2 para EURUSD y GOLD.
    """
    print("=" * 60)
    print("🧠 EXP-016: ALPHA BRAIN V2 — ENTRENAMIENTO FINAL")
    print("=" * 60)
    print("Misión: Entrenar al nuevo cerebro usando los 13 factores alfa")
    print("Meta: Dejar de usar el Sniper V1 (velas) y pasar al Sniper V2")
    print("      (probabilidad pura basada en microestructura)")
    print("=" * 60)

    results = {}

    # EURUSD
    result = train_alpha_v2("EURUSD")
    if result:
        results["EURUSD"] = result[1]

    # GOLD
    result = train_alpha_v2("GOLD")
    if result:
        results["GOLD"] = result[1]

    # Resumen final
    print(f"\n{'='*60}")
    print(f"📊 RESUMEN FINAL — ALPHA BRAIN V2")
    print(f"{'='*60}")
    for symbol, metrics in results.items():
        print(f"\n   {symbol}:")
        print(f"      AUC:          {metrics['auc']:.4f}")
        print(f"      Precisión:    {metrics['precision']:.2%}")
        print(f"      Recall:       {metrics['recall']:.2%}")
        print(f"      Especificidad: {metrics['specificity']:.2%}")

    print(f"\n{'='*60}")
    print(f"✅ EXP-016 COMPLETADO")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
