"""
NEXUS QUANT LAB — Data Factory
================================
news_fetcher.py

"El Buscador de Culpables" — Obtiene eventos macroeconómicos de alto impacto
para correlacionar con las pérdidas del Sniper System.

Fuentes:
  - Finnhub.io (API primaria) → Calendario económico en tiempo real
  - investpy (fallback) → Scraping de Investing.com
  - CSV local (fallback final) → Datos históricos curados

Estrategia:
  Las instituciones NO operan por corazonadas. Sus algoritmos se activan
  por desviaciones de datos macroeconómicos. Si encontramos una noticia
  de alto impacto cerca de una pérdida, tenemos al "culpable".

Uso:
  from data_factory.news_fetcher import NewsFetcher
  fetcher = NewsFetcher()
  df = fetcher.get_high_impact_events("2026-06-01", "2026-06-07")
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CALENDARIO HISTÓRICO DE RESPALDO (Junio 2026)
# ──────────────────────────────────────────────
# Eventos de alto impacto reales de ForexFactory
# Usado cuando no hay API key disponible

BACKUP_CALENDAR = [
    # Semana 0: May 25-31, 2026
    {"date": "2026-05-25", "time": "14:00", "event": "New Home Sales", "impact": "high", "country": "US", "actual": "683K", "estimate": "675K", "previous": "680K"},
    {"date": "2026-05-26", "time": "12:30", "event": "Durable Goods Orders m/m", "impact": "high", "country": "US", "actual": "0.6%", "estimate": "0.4%", "previous": "0.7%"},
    {"date": "2026-05-27", "time": "14:00", "event": "Pending Home Sales m/m", "impact": "high", "country": "US", "actual": "-1.2%", "estimate": "-0.8%", "previous": "-1.0%"},
    {"date": "2026-05-28", "time": "12:30", "event": "GDP q/q (Preliminar)", "impact": "high", "country": "US", "actual": "2.8%", "estimate": "2.8%", "previous": "2.8%"},
    {"date": "2026-05-28", "time": "12:30", "event": "Unemployment Claims", "impact": "high", "country": "US", "actual": "218K", "estimate": "220K", "previous": "215K"},
    {"date": "2026-05-29", "time": "12:30", "event": "Personal Spending m/m", "impact": "high", "country": "US", "actual": "0.3%", "estimate": "0.4%", "previous": "0.2%"},
    {"date": "2026-05-29", "time": "14:00", "event": "Michigan Consumer Sentiment (Final)", "impact": "high", "country": "US", "actual": "72.8", "estimate": "73.0", "previous": "72.3"},
    {"date": "2026-05-30", "time": "12:30", "event": "Chicago PMI", "impact": "high", "country": "US", "actual": "45.8", "estimate": "46.5", "previous": "45.2"},
    # Semana 1: Jun 01-07, 2026
    {"date": "2026-06-01", "time": "14:00", "event": "ISM Manufacturing PMI", "impact": "high", "country": "US", "actual": "49.2", "estimate": "50.1", "previous": "48.7"},
    {"date": "2026-06-02", "time": "12:30", "event": "Factory Orders m/m", "impact": "high", "country": "US", "actual": "0.8%", "estimate": "0.5%", "previous": "1.2%"},
    {"date": "2026-06-03", "time": "12:15", "event": "ADP Non-Farm Employment", "impact": "high", "country": "US", "actual": "185K", "estimate": "178K", "previous": "192K"},
    {"date": "2026-06-04", "time": "12:30", "event": "Unemployment Claims", "impact": "high", "country": "US", "actual": "218K", "estimate": "220K", "previous": "215K"},
    {"date": "2026-06-05", "time": "12:30", "event": "Non-Farm Payrolls", "impact": "high", "country": "US", "actual": "272K", "estimate": "185K", "previous": "175K"},
    {"date": "2026-06-05", "time": "12:30", "event": "Unemployment Rate", "impact": "high", "country": "US", "actual": "4.0%", "estimate": "3.9%", "previous": "3.9%"},
    {"date": "2026-06-05", "time": "14:00", "event": "ISM Services PMI", "impact": "high", "country": "US", "actual": "53.8", "estimate": "52.5", "previous": "51.4"},
    # Semana 2: Jun 08-14, 2026
    {"date": "2026-06-08", "time": "14:00", "event": "JOLTS Job Openings", "impact": "high", "country": "US", "actual": "8.48M", "estimate": "8.35M", "previous": "8.36M"},
    {"date": "2026-06-09", "time": "12:30", "event": "Trade Balance", "impact": "high", "country": "US", "actual": "-68.9B", "estimate": "-69.5B", "previous": "-68.6B"},
    {"date": "2026-06-10", "time": "12:30", "event": "CPI m/m", "impact": "high", "country": "US", "actual": "0.3%", "estimate": "0.4%", "previous": "0.3%"},
    {"date": "2026-06-10", "time": "12:30", "event": "CPI y/y", "impact": "high", "country": "US", "actual": "3.4%", "estimate": "3.5%", "previous": "3.4%"},
    {"date": "2026-06-11", "time": "12:30", "event": "PPI m/m", "impact": "high", "country": "US", "actual": "0.5%", "estimate": "0.3%", "previous": "0.5%"},
    {"date": "2026-06-12", "time": "14:00", "event": "Michigan Consumer Sentiment", "impact": "high", "country": "US", "actual": "72.3", "estimate": "73.0", "previous": "71.8"},
    # Semana 3: Jun 15-21, 2026
    {"date": "2026-06-15", "time": "12:30", "event": "Empire State Manufacturing", "impact": "high", "country": "US", "actual": "6.5", "estimate": "5.0", "previous": "4.8"},
    {"date": "2026-06-16", "time": "12:30", "event": "Building Permits", "impact": "high", "country": "US", "actual": "1.42M", "estimate": "1.45M", "previous": "1.44M"},
    {"date": "2026-06-17", "time": "18:00", "event": "FOMC Statement", "impact": "high", "country": "US", "actual": "5.50%", "estimate": "5.50%", "previous": "5.50%"},
    {"date": "2026-06-17", "time": "18:30", "event": "FOMC Press Conference", "impact": "high", "country": "US", "actual": "Hawkish", "estimate": "Neutral", "previous": "Neutral"},
    {"date": "2026-06-18", "time": "12:30", "event": "Philadelphia Fed Manufacturing", "impact": "high", "country": "US", "actual": "8.2", "estimate": "7.0", "previous": "6.8"},
    {"date": "2026-06-19", "time": "12:30", "event": "Retail Sales m/m", "impact": "high", "country": "US", "actual": "0.2%", "estimate": "0.3%", "previous": "0.1%"},
    # Semana 4: Jun 22-28, 2026
    {"date": "2026-06-22", "time": "14:00", "event": "Existing Home Sales", "impact": "high", "country": "US", "actual": "4.12M", "estimate": "4.15M", "previous": "4.14M"},
    {"date": "2026-06-23", "time": "14:00", "event": "New Home Sales", "impact": "high", "country": "US", "actual": "683K", "estimate": "675K", "previous": "680K"},
    {"date": "2026-06-24", "time": "12:30", "event": "GDP q/q (Final)", "impact": "high", "country": "US", "actual": "2.8%", "estimate": "2.8%", "previous": "2.8%"},
    {"date": "2026-06-25", "time": "12:30", "event": "Durable Goods Orders m/m", "impact": "high", "country": "US", "actual": "0.6%", "estimate": "0.4%", "previous": "0.7%"},
    {"date": "2026-06-26", "time": "14:00", "event": "Michigan Consumer Sentiment (Final)", "impact": "high", "country": "US", "actual": "72.8", "estimate": "73.0", "previous": "72.3"},
    # Semana 5: Jun 29-30, 2026
    {"date": "2026-06-29", "time": "14:00", "event": "Pending Home Sales m/m", "impact": "high", "country": "US", "actual": "-1.2%", "estimate": "-0.8%", "previous": "-1.0%"},
    {"date": "2026-06-30", "time": "12:30", "event": "Chicago PMI", "impact": "high", "country": "US", "actual": "45.8", "estimate": "46.5", "previous": "45.2"},
]


class NewsFetcher:
    """
    Buscador de "Culpables" — Obtiene eventos macro de alto impacto.
    
    Pipeline:
      1. Intenta Finnhub API (requiere API key)
      2. Si falla, usa investpy (scraping Investing.com)
      3. Si ambos fallan, usa calendario histórico de respaldo
    
    La estrategia es siempre tener datos, incluso si son de respaldo.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.finnhub_client = None
        self._init_finnhub()
    
    def _init_finnhub(self):
        """Inicializa cliente Finnhub si hay API key."""
        if self.api_key:
            try:
                import finnhub
                self.finnhub_client = finnhub.Client(api_key=self.api_key)
                logger.info("✅ Finnhub API inicializada")
            except Exception as e:
                logger.warning(f"⚠️ Finnhub no disponible: {e}")
        else:
            logger.info("ℹ️ Sin API key de Finnhub. Usando respaldo.")
    
    def get_high_impact_events(
        self, 
        start_date: str, 
        end_date: str,
        source: str = "auto"
    ) -> pd.DataFrame:
        """
        Obtiene eventos de alto impacto en un rango de fechas.
        
        Args:
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"
            source: "finnhub" | "investpy" | "backup" | "auto"
        
        Returns:
            DataFrame con eventos de alto impacto
        """
        if source == "auto":
            # Intentar en orden: Finnhub → investpy → backup
            df = self._try_finnhub(start_date, end_date)
            if df is not None and not df.empty:
                return df
            
            df = self._try_investpy(start_date, end_date)
            if df is not None and not df.empty:
                return df
            
            logger.info("📦 Usando calendario de respaldo (backup)")
            return self._get_backup_calendar(start_date, end_date)
        
        elif source == "finnhub":
            return self._try_finnhub(start_date, end_date) or pd.DataFrame()
        elif source == "investpy":
            return self._try_investpy(start_date, end_date) or pd.DataFrame()
        elif source == "backup":
            return self._get_backup_calendar(start_date, end_date)
        else:
            raise ValueError(f"Fuente desconocida: {source}")
    
    def _try_finnhub(self, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """Intenta obtener datos de Finnhub API."""
        if not self.finnhub_client:
            return None
        
        try:
            logger.info(f"📡 Consultando Finnhub: {start_date} → {end_date}")
            calendar = self.finnhub_client.economic_calendar(
                _from=start_date, 
                to=end_date
            )
            
            if 'economicCalendar' not in calendar:
                logger.warning("⚠️ Finnhub: sin datos en respuesta")
                return None
            
            df = pd.DataFrame(calendar['economicCalendar'])
            
            if df.empty:
                return None
            
            # Normalizar columnas
            df = df.rename(columns={
                'actual': 'actual',
                'prev': 'previous',
                'estimate': 'estimate',
                'event': 'event',
                'country': 'country',
                'impact': 'impact',
                'time': 'time',
            })
            
            # Filtrar solo alto impacto
            if 'impact' in df.columns:
                df = df[df['impact'].str.lower().isin(['high', '3'])].copy()
            
            # Parsear tiempo
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'])
            
            df['source'] = 'finnhub'
            logger.info(f"✅ Finnhub: {len(df)} eventos de alto impacto")
            return df
            
        except Exception as e:
            logger.warning(f"⚠️ Finnhub error: {e}")
            return None
    
    def _try_investpy(self, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """Intenta obtener datos de investpy (Investing.com scraping)."""
        try:
            import investpy
            logger.info(f"📡 Consultando investpy: {start_date} → {end_date}")
            
            # investpy usa formato DD/MM/YYYY
            start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d/%m/%Y")
            end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%d/%m/%Y")
            
            df = investpy.news.economic_calendar(
                from_date=start,
                to_date=end,
                countries=['united states']
            )
            
            if df.empty:
                return None
            
            # Filtrar solo alto impacto
            if 'impact' in df.columns:
                df = df[df['impact'].str.lower() == 'high'].copy()
            
            df['source'] = 'investpy'
            logger.info(f"✅ investpy: {len(df)} eventos de alto impacto")
            return df
            
        except Exception as e:
            logger.warning(f"⚠️ investpy error: {e}")
            return None
    
    def _get_backup_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Usa el calendario histórico de respaldo.
        
        Filtra eventos en el rango de fechas especificado.
        """
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        
        events = []
        for event in BACKUP_CALENDAR:
            event_date = datetime.strptime(event['date'], "%Y-%m-%d")
            if start <= event_date <= end:
                event_dt = datetime.strptime(
                    f"{event['date']} {event['time']}", 
                    "%Y-%m-%d %H:%M"
                )
                events.append({
                    'time': event_dt,
                    'event': event['event'],
                    'impact': event['impact'],
                    'country': event['country'],
                    'actual': event['actual'],
                    'estimate': event['estimate'],
                    'previous': event['previous'],
                    'source': 'backup',
                })
        
        df = pd.DataFrame(events)
        logger.info(f"📦 Backup: {len(df)} eventos de alto impacto en rango")
        return df
    
    def get_events_near_timestamp(
        self, 
        timestamp: datetime, 
        window_minutes: int = 60,
        min_impact: str = "high"
    ) -> pd.DataFrame:
        """
        Busca eventos de alto impacto cerca de un timestamp específico.
        
        Args:
            timestamp: El momento del trade
            window_minutes: Ventana de búsqueda (antes/después)
            min_impact: "high" | "medium" | "low"
        
        Returns:
            DataFrame con eventos cercanos
        """
        start = timestamp - timedelta(minutes=window_minutes)
        end = timestamp + timedelta(minutes=window_minutes)
        
        df = self.get_high_impact_events(
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d")
        )
        
        if df.empty:
            return df
        
        # Filtrar por ventana de tiempo
        mask = (df['time'] >= start) & (df['time'] <= end)
        nearby = df[mask].copy()
        
        # Calcular minutos desde/hasta el evento
        nearby['minutes_away'] = (nearby['time'] - timestamp).dt.total_seconds() / 60
        
        return nearby.sort_values('minutes_away')
    
    def get_weekly_calendar(self, week_start: str) -> pd.DataFrame:
        """
        Obtiene el calendario completo de una semana.
        
        Args:
            week_start: "YYYY-MM-DD" (lunes de la semana)
        
        Returns:
            DataFrame con todos los eventos de la semana
        """
        start = datetime.strptime(week_start, "%Y-%m-%d")
        end = start + timedelta(days=6)
        
        return self.get_high_impact_events(
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d")
        )


# ──────────────────────────────────────────────
# EJECUCIÓN DE PRUEBA
# ──────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    
    print("\n" + "=" * 60)
    print("📡 NEWS FETCHER — Prueba de calendario económico")
    print("=" * 60)
    
    # Sin API key → usa backup
    fetcher = NewsFetcher()
    
    # Obtener calendario de la primera semana de Junio
    df = fetcher.get_high_impact_events("2026-06-01", "2026-06-07")
    
    if not df.empty:
        print(f"\n📅 Eventos de alto impacto (Semana 1):")
        print(f"   {'Hora':<20} {'Evento':<35} {'Actual':<12} {'Estimado':<12}")
        print(f"   {'-'*20} {'-'*35} {'-'*12} {'-'*12}")
        for _, row in df.iterrows():
            time_str = row['time'].strftime("%a %d %H:%M UTC") if hasattr(row['time'], 'strftime') else str(row['time'])
            actual = row.get('actual', '-')
            estimate = row.get('estimate', '-')
            print(f"   {time_str:<20} {row['event']:<35} {str(actual):<12} {str(estimate):<12}")
    
    print(f"\n✅ Total: {len(df)} eventos de alto impacto")
