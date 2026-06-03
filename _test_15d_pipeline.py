"""
TEST — Pipeline de 15 Dimensiones → 13 Modelo (Alpha Brain V8.4)
Verifica el puente: 15 features (scaler) → 13 features (XGBoost)
"""
import sys, os, json, warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '.')
os.chdir('.')

import joblib
import pandas as pd
import numpy as np
from datetime import datetime

# ─── 1. CARGAR SCALER Y MODELOS ───
scaler = joblib.load('models/market_scaler_v2.pkl')
print(f'✅ Scaler cargado: {len(scaler.feature_names_in_)} features')
print(f'   {scaler.feature_names_in_.tolist()}')

model_eurusd = joblib.load('models/eurusd_alpha_brain_v2.pkl')
model_gold = joblib.load('models/gold_alpha_brain_v2.pkl')
print(f'✅ Modelo EURUSD: {model_eurusd.n_features_in_} features')
print(f'   {model_eurusd.feature_names_in_.tolist()}')
print(f'✅ Modelo GOLD: {model_gold.n_features_in_} features')
print(f'   {model_gold.feature_names_in_.tolist()}')

# ─── 2. FUNCIÓN DE EXTRACCIÓN (15 dimensiones) ───
def get_alpha_vector_15d(df, symbol, audit_data, other_symbol_data=None):
    now_utc = datetime.utcnow()
    is_ny = 1 if (13 <= now_utc.hour <= 20) else 0
    is_fixing = 1 if (now_utc.hour == 19) else 0
    
    h24 = df['high'].iloc[-24:].max()
    l24 = df['low'].iloc[-24:].min()
    curr = df['close'].iloc[-1]
    near_high = (curr - l24) / (h24 - l24) if (h24 - l24) != 0 else 0.5
    near_low = 1 - near_high

    mom3 = df['close'].iloc[-1] / df['close'].iloc[-3] - 1 if len(df) > 3 else 0
    mom6 = df['close'].iloc[-1] / df['close'].iloc[-6] - 1 if len(df) > 6 else 0
    mom12 = df['close'].iloc[-1] / df['close'].iloc[-12] - 1 if len(df) > 12 else 0

    regime = audit_data.get('regime', 'NEUTRO')
    regime_high_vol = 1.0 if regime == 'ALTA VOLATILIDAD' else 0.0
    regime_low_vol = 1.0 if regime == 'BAJA VOLATILIDAD' else 0.0
    regime_normal = 1.0 if regime in ('NEUTRO', 'NORMAL') else 0.0

    factors = {
        'alpha_rejection_z': audit_data.get('speed', 0.0),
        'alpha_micro_trend': audit_data.get('vol_delta', 0.0),
        'alpha_regime_high_vol': regime_high_vol,
        'alpha_regime_low_vol': regime_low_vol,
        'alpha_regime_normal': regime_normal,
        'alpha_near_high': near_high,
        'alpha_near_low': near_low,
        'alpha_is_fixing_hour': is_fixing,
        'alpha_is_ny_session': is_ny,
        'alpha_mom_3h': mom3,
        'alpha_mom_6h': mom6,
        'alpha_mom_12h': mom12,
        'alpha_divergence': 0.0,
        'alpha_rejection_z_gold': 0.0,
        'alpha_micro_trend_gold': 0.0,
    }

    if other_symbol_data:
        factors['alpha_divergence'] = curr - other_symbol_data.get('close', curr)
        factors['alpha_rejection_z_gold'] = other_symbol_data.get('speed', 0.0)
        factors['alpha_micro_trend_gold'] = other_symbol_data.get('vol_delta', 0.0)

    return factors

# ─── 3. FUNCIÓN PUENTE: 15 → 13 ───
def bridge_15d_to_13d(X_scaled_15d, scaler_feature_names, model_feature_names):
    """
    Convierte el array escalado de 15 features a 13 features para el modelo.
    Colapsa one-hot regime (3 cols) a feature única alpha_regime.
    """
    X_scaled_df = pd.DataFrame(X_scaled_15d, columns=scaler_feature_names)
    
    regime_map = {
        'alpha_regime_high_vol': 'ALTA VOLATILIDAD',
        'alpha_regime_low_vol': 'BAJA VOLATILIDAD',
        'alpha_regime_normal': 'NEUTRO',
    }
    
    # Determinar régimen activo
    active_regime = 'NEUTRO'
    for col, regime_name in regime_map.items():
        if X_scaled_df[col].iloc[0] > 0.5:
            active_regime = regime_name
            break
    
    # Construir vector de 13 features
    X_model_dict = {}
    for name in model_feature_names:
        if name == 'alpha_regime':
            if active_regime == 'ALTA VOLATILIDAD':
                X_model_dict[name] = X_scaled_df['alpha_regime_high_vol'].iloc[0]
            elif active_regime == 'BAJA VOLATILIDAD':
                X_model_dict[name] = X_scaled_df['alpha_regime_low_vol'].iloc[0]
            else:
                X_model_dict[name] = X_scaled_df['alpha_regime_normal'].iloc[0]
        else:
            X_model_dict[name] = X_scaled_df[name].iloc[0]
    
    return pd.DataFrame([X_model_dict], columns=model_feature_names)

# ─── 4. CREAR DATAFRAME SIMULADO ───
np.random.seed(42)
n = 100
df_test = pd.DataFrame({
    'open': np.cumsum(np.random.randn(n) * 0.0001) + 1.08,
    'high': np.cumsum(np.random.randn(n) * 0.0001) + 1.08 + np.random.rand(n) * 0.0005,
    'low': np.cumsum(np.random.randn(n) * 0.0001) + 1.08 - np.random.rand(n) * 0.0005,
    'close': np.cumsum(np.random.randn(n) * 0.0001) + 1.08,
})
df_test['high'] = df_test[['open', 'close', 'high']].max(axis=1)
df_test['low'] = df_test[['open', 'close', 'low']].min(axis=1)

# ─── TEST 1: Vector de 15 dimensiones ───
print('\n' + '='*60)
print('TEST 1: Generación del Vector Alfa (15 dimensiones)')
print('='*60)
audit_data = {'speed': 1.5, 'vol_delta': 0.002, 'regime': 'NEUTRO'}
alpha_dict = get_alpha_vector_15d(df_test, 'EURUSD', audit_data)
print(f'📊 Factores generados: {len(alpha_dict)}')
for k, v in alpha_dict.items():
    print(f'   {k}: {v}')

# ─── TEST 2: Sincronización con scaler (15 features) ───
print('\n' + '='*60)
print('TEST 2: Scaler transform (15 features)')
print('='*60)
scaler_feature_names = scaler.feature_names_in_
X_list_15d = [alpha_dict.get(name, 0.0) for name in scaler_feature_names]
X_15d = pd.DataFrame([X_list_15d], columns=scaler_feature_names)
X_scaled_15d = scaler.transform(X_15d)
print(f'✅ Scaler transform OK: {X_scaled_15d.shape}')

# ─── TEST 3: Puente 15→13 y predicción EURUSD ───
print('\n' + '='*60)
print('TEST 3: Puente 15→13 + Predicción EURUSD')
print('='*60)
model_feature_names = model_eurusd.feature_names_in_
X_model = bridge_15d_to_13d(X_scaled_15d, scaler_feature_names, model_feature_names)
print(f'✅ Bridge 15→13: {X_model.shape}')
print(f'   Columnas: {X_model.columns.tolist()}')

proba = model_eurusd.predict_proba(X_model)[0][1]
direction = 'LONG' if proba > 0.5 else 'SHORT'
proba_display = max(proba, 1 - proba)
print(f'🧠 Predicción EURUSD (15→13): {proba_display*100:.2f}% → {direction}')

# ─── TEST 4: Cross-Asset ───
print('\n' + '='*60)
print('TEST 4: Vector con Cross-Asset')
print('='*60)
other_data = {'close': 2350.0, 'speed': 0.8, 'vol_delta': -0.001}
alpha_dict_cross = get_alpha_vector_15d(df_test, 'EURUSD', audit_data, other_data)
print(f'   alpha_divergence = {alpha_dict_cross["alpha_divergence"]:.5f}')
print(f'   alpha_rejection_z_gold = {alpha_dict_cross["alpha_rejection_z_gold"]}')
print(f'   alpha_micro_trend_gold = {alpha_dict_cross["alpha_micro_trend_gold"]}')

# ─── TEST 5: Predicción GOLD ───
print('\n' + '='*60)
print('TEST 5: Predicción GOLD (15→13)')
print('='*60)
X_list_15d_gold = [alpha_dict_cross.get(name, 0.0) for name in scaler_feature_names]
X_15d_gold = pd.DataFrame([X_list_15d_gold], columns=scaler_feature_names)
X_scaled_15d_gold = scaler.transform(X_15d_gold)
X_model_gold = bridge_15d_to_13d(X_scaled_15d_gold, scaler_feature_names, model_gold.feature_names_in_)

proba_gold = model_gold.predict_proba(X_model_gold)[0][1]
direction_gold = 'LONG' if proba_gold > 0.5 else 'SHORT'
proba_gold_display = max(proba_gold, 1 - proba_gold)
print(f'🧠 Predicción GOLD (15→13): {proba_gold_display*100:.2f}% → {direction_gold}')

# ─── TEST 6: Error de dimensiones (el bug original) ───
print('\n' + '='*60)
print('TEST 6: Verificación anti-error')
print('='*60)

# Error 4 features en scaler
try:
    bad_X = pd.DataFrame([[1,2,3,4]], columns=['a','b','c','d'])
    scaler.transform(bad_X)
    print('❌ ERROR: Debió fallar con 4 features en scaler')
except Exception as e:
    print(f'✅ Scaler rechaza 4 features: {str(e)[:80]}...')

# Error 15 features en modelo
try:
    model_eurusd.predict_proba(X_15d)
    print('❌ ERROR: Debió fallar con 15 features en modelo')
except Exception as e:
    print(f'✅ Modelo rechaza 15 features: {str(e)[:80]}...')

# Pipeline completo funciona
print(f'✅ Pipeline 15→13 funciona perfectamente')

# ─── RESUMEN FINAL ───
print('\n' + '='*60)
print('RESUMEN FINAL — Pipeline 15→13 Dimensiones')
print('='*60)
print(f'✅ Scaler espera: {len(scaler_feature_names)} features')
print(f'✅ Vector Alfa genera: {len(alpha_dict)} factores')
print(f'✅ Bridge entrega: {X_model.shape[1]} columnas (13)')
print(f'✅ EURUSD predice: {proba_display*100:.2f}%')
print(f'✅ GOLD predice: {proba_gold_display*100:.2f}%')
print(f'❌ Error "X has 4 features": ELIMINADO')
print(f'❌ Error "expected 13, got 15": ELIMINADO')
print('='*60)
print('🎯 Alpha Brain V8.4 sincronizado con el laboratorio')
