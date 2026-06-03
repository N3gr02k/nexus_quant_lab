"""
NEXUS QUANT LAB — SMC STRATEGY ENGINE (V8.5)
=============================================
strategy_engine.py

Implementación de Smart Money Concepts basados en la academia SMC:
  - Valid BOS (Break of Structure): Cierre de cuerpo fuera del rango previo
  - Turtle Soup: Barrido de liquidez (mecha) seguido de reversión
  - Order Block (OB): Última vela contraria antes del movimiento fuerte

Integración con el SQUAD MODE del stratum_v8_master_live.py.

Autor: Nexus Quant Lab
Fecha: 2026-06-03 (V8.5 — SMC Squad)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any


class SMCEngine:
    """
    Motor de detección de estructura SMC (Smart Money Concepts).
    
    Detecta:
      - BOS (Break of Structure): Continuación de tendencia
      - Turtle Soup: Reversión institucional tras barrido de liquidez
      - Order Blocks: Zonas de interés institucional
    """
    
    def __init__(self):
        # Configuración de parámetros
        self.bos_lookback = 20      # Velas hacia atrás para buscar estructura
        self.soup_lookback = 50     # Velas hacia atrás para buscar extremos
        self.ob_lookback = 10       # Velas hacia atrás para Order Blocks
        self.speed_threshold = 1.5  # Desviaciones estándar para Turtle Soup
        self.vol_delta_threshold = 0.15  # Delta de volumen mínimo para BOS
    
    def detect_bos(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        Detecta Break of Structure (BOS) VÁLIDO.
        
        Regla del Video 1:
          - El cierre debe ser con el CUERPO de la vela, no solo la mecha.
          - BOS Alcista: close > máximo de las últimas N velas
          - BOS Bajista: close < mínimo de las últimas N velas
        
        Args:
            df: DataFrame con velas (columnas: open, high, low, close)
        
        Returns:
            Dict con tipo de BOS, nivel y dirección, o None si no hay BOS
        """
        if len(df) < self.bos_lookback + 2:
            return None
        
        last_close = df['close'].iloc[-1]
        last_open = df['open'].iloc[-1]
        
        # Rango de referencia (excluyendo la última vela)
        prev_high = df['high'].iloc[-(self.bos_lookback + 1):-1].max()
        prev_low = df['low'].iloc[-(self.bos_lookback + 1):-1].min()
        
        # BOS ALCISTA: Cierre de cuerpo por encima del máximo anterior
        if last_close > prev_high:
            # Verificar que el cuerpo (close - open) esté fuera del rango
            body_top = max(last_close, last_open)
            if body_top > prev_high:
                return {
                    'type': 'BOS_ALCISTA',
                    'level': prev_high,
                    'direction': 'BUY',
                    'close': last_close,
                    'body_break': body_top - prev_high,
                }
        
        # BOS BAJISTA: Cierre de cuerpo por debajo del mínimo anterior
        if last_close < prev_low:
            # Verificar que el cuerpo esté fuera del rango
            body_bottom = min(last_close, last_open)
            if body_bottom < prev_low:
                return {
                    'type': 'BOS_BAJISTA',
                    'level': prev_low,
                    'direction': 'SELL',
                    'close': last_close,
                    'body_break': prev_low - body_bottom,
                }
        
        return None
    
    def detect_turtle_soup(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        Detecta Turtle Soup (Toma de Liquidez con Reversión).
        
        Regla del Video 2:
          - Turtle Soup Alcista: low barre mínimo de 50 velas, cierre > ese mínimo
          - Turtle Soup Bajista: high barre máximo de 50 velas, cierre < ese máximo
          - La mecha debe cruzar el extremo, pero el cuerpo debe cerrar del otro lado
        
        Args:
            df: DataFrame con velas (columnas: open, high, low, close)
        
        Returns:
            Dict con tipo de Turtle Soup, dirección y extremo barrido
        """
        if len(df) < self.soup_lookback + 2:
            return None
        
        last_high = df['high'].iloc[-1]
        last_low = df['low'].iloc[-1]
        last_close = df['close'].iloc[-1]
        last_open = df['open'].iloc[-1]
        
        # Extremos de referencia (excluyendo la última vela)
        prev_high = df['high'].iloc[-(self.soup_lookback + 1):-1].max()
        prev_low = df['low'].iloc[-(self.soup_lookback + 1):-1].min()
        
        # Turtle Soup Alcista (Fake breakdown)
        # La mecha baja barre el mínimo, pero el cierre está por encima
        if last_low < prev_low and last_close > prev_low:
            # Verificar que el cuerpo esté dentro del rango (reversión real)
            body_bottom = min(last_close, last_open)
            if body_bottom > prev_low:
                return {
                    'type': 'TURTLE_SOUP_BUY',
                    'direction': 'BUY',
                    'extreme': last_low,
                    'swept_level': prev_low,
                    'wick_size': prev_low - last_low,
                    'close_above': last_close - prev_low,
                }
        
        # Turtle Soup Bajista (Fake breakout)
        # La mecha alta barre el máximo, pero el cierre está por debajo
        if last_high > prev_high and last_close < prev_high:
            # Verificar que el cuerpo esté dentro del rango (reversión real)
            body_top = max(last_close, last_open)
            if body_top < prev_high:
                return {
                    'type': 'TURTLE_SOUP_SELL',
                    'direction': 'SELL',
                    'extreme': last_high,
                    'swept_level': prev_high,
                    'wick_size': last_high - prev_high,
                    'close_below': prev_high - last_close,
                }
        
        return None
    
    def detect_order_block(self, df: pd.DataFrame, direction: str) -> Optional[Dict[str, Any]]:
        """
        Detecta Order Block (OB) — la última vela contraria antes del movimiento.
        
        Un Order Block es la última vela en dirección opuesta antes de que
        el precio se mueva fuertemente en la dirección de la tendencia.
        
        Args:
            df: DataFrame con velas
            direction: Dirección de la tendencia ('BUY' o 'SELL')
        
        Returns:
            Dict con información del Order Block
        """
        if len(df) < self.ob_lookback + 3:
            return None
        
        # Buscar hacia atrás desde la última vela
        for i in range(2, min(self.ob_lookback + 2, len(df))):
            candle = df.iloc[-i]
            prev_candle = df.iloc[-(i + 1)]
            next_candle = df.iloc[-(i - 1)]
            
            if direction == 'BUY':
                # OB alcista: vela bajista que precede a un movimiento alcista fuerte
                if candle['close'] < candle['open']:  # Vela bajista
                    # La siguiente vela debe ser alcista y tener buen momentum
                    if next_candle['close'] > next_candle['open']:
                        momentum = (next_candle['close'] - next_candle['open']) / (candle['high'] - candle['low'] + 1e-10)
                        if momentum > 0.5:  # Movimiento significativo
                            return {
                                'type': 'OB_ALCISTA',
                                'direction': 'BUY',
                                'ob_high': candle['high'],
                                'ob_low': candle['low'],
                                'momentum': momentum,
                                'index': -i,
                            }
            else:  # SELL
                # OB bajista: vela alcista que precede a un movimiento bajista fuerte
                if candle['close'] > candle['open']:  # Vela alcista
                    if next_candle['close'] < next_candle['open']:
                        momentum = (next_candle['open'] - next_candle['close']) / (candle['high'] - candle['low'] + 1e-10)
                        if momentum > 0.5:
                            return {
                                'type': 'OB_BAJISTA',
                                'direction': 'SELL',
                                'ob_high': candle['high'],
                                'ob_low': candle['low'],
                                'momentum': momentum,
                                'index': -i,
                            }
        
        return None
    
    def analyze(self, df: pd.DataFrame, audit: Dict[str, Any]) -> Dict[str, Any]:
        """
        Análisis completo SMC: BOS + Turtle Soup + Order Blocks.
        
        Evalúa todas las señales y determina si hay un ataque SQUAD listo.
        
        Args:
            df: DataFrame con velas H1
            audit: Diccionario con métricas de auditoría:
                - speed: rejection_speed (desviaciones estándar)
                - vol_delta: delta de volumen normalizado
                - (otros campos opcionales)
        
        Returns:
            Dict con:
              - squad_attack: señal de Turtle Soup lista para ejecutar (o None)
              - squad_trend: señal de BOS lista para ejecutar (o None)
              - signals: lista de todas las señales detectadas
              - order_block: Order Block detectado (o None)
        """
        result = {
            'squad_attack': None,
            'squad_trend': None,
            'signals': [],
            'order_block': None,
        }
        
        # 1. Detectar BOS
        bos_signal = self.detect_bos(df)
        if bos_signal:
            result['signals'].append(bos_signal)
            
            # Verificar volumen a favor para BOS
            vol_delta = abs(audit.get('vol_delta', 0))
            if vol_delta > self.vol_delta_threshold:
                result['squad_trend'] = {
                    'signal': bos_signal,
                    'vol_delta': vol_delta,
                    'confidence': 'ALTA' if vol_delta > self.vol_delta_threshold * 2 else 'MEDIA',
                }
        
        # 2. Detectar Turtle Soup
        soup_signal = self.detect_turtle_soup(df)
        if soup_signal:
            result['signals'].append(soup_signal)
            
            # Verificar velocidad de rechazo para Turtle Soup
            speed = abs(audit.get('speed', 0))
            if speed > self.speed_threshold:
                result['squad_attack'] = {
                    'signal': soup_signal,
                    'speed': speed,
                    'confidence': 'ALTA' if speed > self.speed_threshold * 1.5 else 'MEDIA',
                }
        
        # 3. Detectar Order Block (si hay alguna señal)
        if bos_signal:
            ob = self.detect_order_block(df, bos_signal['direction'])
            if ob:
                result['order_block'] = ob
                result['signals'].append(ob)
        elif soup_signal:
            ob = self.detect_order_block(df, soup_signal['direction'])
            if ob:
                result['order_block'] = ob
                result['signals'].append(ob)
        
        return result
    
    def get_entry_price(self, signal: Dict[str, Any], df: pd.DataFrame) -> float:
        """
        Calcula el precio de entrada óptimo basado en la señal SMC.
        
        Para Turtle Soup: entrada en el cierre de la vela de barrido.
        Para BOS: entrada en el cierre de la vela de quiebre.
        
        Args:
            signal: Señal detectada (BOS o Turtle Soup)
            df: DataFrame con velas
        
        Returns:
            Precio de entrada
        """
        return df['close'].iloc[-1]
    
    def get_stop_loss(self, signal: Dict[str, Any], df: pd.DataFrame, atr: float) -> float:
        """
        Calcula el Stop Loss basado en la señal SMC.
        
        Para Turtle Soup: SL justo detrás del extremo barrido.
        Para BOS: SL detrás del nivel de quiebre.
        
        Args:
            signal: Señal detectada
            df: DataFrame con velas
            atr: ATR actual para distancia mínima
        
        Returns:
            Precio de Stop Loss
        """
        if signal['type'].startswith('TURTLE_SOUP'):
            if signal['direction'] == 'BUY':
                # SL debajo del extremo barrido
                sl = signal['extreme'] - atr * 0.5
            else:
                sl = signal['extreme'] + atr * 0.5
        elif signal['type'].startswith('BOS'):
            if signal['direction'] == 'BUY':
                sl = signal['level'] - atr * 0.5
            else:
                sl = signal['level'] + atr * 0.5
        else:
            sl = df['close'].iloc[-1] - atr if signal['direction'] == 'BUY' else df['close'].iloc[-1] + atr
        
        return sl
    
    def get_take_profit(self, signal: Dict[str, Any], entry: float, sl: float, atr: float) -> float:
        """
        Calcula el Take Profit basado en la señal SMC.
        
        Risk:Reward de 1:2 como mínimo.
        
        Args:
            signal: Señal detectada
            entry: Precio de entrada
            sl: Precio de Stop Loss
            atr: ATR actual
        
        Returns:
            Precio de Take Profit
        """
        risk = abs(entry - sl)
        if signal['direction'] == 'BUY':
            tp = entry + risk * 2.0
        else:
            tp = entry - risk * 2.0
        
        return tp
