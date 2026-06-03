# 🧪 NEXUS QUANT LAB

**Misión:** Extraer datos de alta fidelidad para crear el modelo de predicción definitivo.

## 📂 Estructura del Proyecto

```
nexus_quant_lab/
├── data_factory/           # Descarga de Ticks y Volumen real
│   ├── __init__.py
│   └── tick_collector.py   # Recolector de ticks desde MT5
├── experiments/            # Los 3 experimentos principales
│   ├── __init__.py
│   ├── path_profiling.py   # Análisis intrabarra (velocidad)
│   ├── cross_asset.py      # Correlación EURUSD vs GOLD
│   └── montecarlo_sim.py   # Validación de robustez
├── models/                 # Prototipos de Transformers/HMM
│   └── __init__.py
├── notebook_research/      # Análisis visual de resultados
│   └── __init__.py
├── requirements.txt
└── README.md
```

## 🚀 Instalación

```bash
cd D:\nexus_quant_lab
pip install -r requirements.txt
```

## 🔬 Los 3 Experimentos

### 1. Path-Profiling (Análisis de Ticks)
**Hipótesis:** Dos velas con la misma forma de H1 pueden tener intenciones opuestas.

- **Vela A:** Sube lento 55 min y cae en últimos 5 min → *Distribución Institucional*
- **Vela B:** Cae al inicio y sube al final → *Acumulación Institucional*

**Feature clave:** `rejection_speed` — Velocidad de rechazo en muros HTF.
Si |rejection_speed| > 3σ → señal de reversión casi certeza física.

```bash
python experiments/path_profiling.py --symbol EURUSD --from-date 2026-05-01
```

### 2. Correlación Cruzada (Inter-market Alpha)
**Hipótesis:** El DXY o el Oro se mueven segundos antes que el Euro.

**Feature clave:** `asset_divergence` — Si el Oro cae pero el Euro sigue arriba, el Euro está "sostenido por hilos".

```bash
python experiments/cross_asset.py --from-date 2026-05-01 --pairs EURUSD_GOLD EURUSD_DXY
```

### 3. Análisis de Montecarlo (Test de Estrés)
**Hipótesis:** ¿Tus ganancias de hoy son suerte o sistema?

**Método:** Desordena los resultados 10,000 veces para crear curvas de equidad sintéticas.

```bash
python experiments/montecarlo_sim.py --audit-file master_audit.csv --capital 10000 --risk 0.01
```

## ✅ Estado Actual del Laboratorio

| Componente | Estado | Descripción |
|------------|--------|-------------|
| `data_factory/tick_collector.py` | ✅ v2.0 — Bitwise Flags | Recolector con flags reales MT5 y agregación H1 |
| `experiments/path_profiling.py` | ✅ v2.0 — Edge Analysis | Analiza correlación rejection_speed vs retorno futuro 3h |

| `experiments/cross_asset.py` | ⏳ Pendiente | Esperando sincronización multi-símbolo |
| `experiments/montecarlo_sim.py` | ⏳ Pendiente | Requiere historial de trades del Master Sniper |
| `MEMORIA.md` | ✅ Activo | Diario de a bordo de la investigación |


## � Data Factory

El `tick_collector.py` es el corazón del laboratorio. Genera estas features:

| Feature | Descripción |
|---------|-------------|
| `rejection_speed` | Z-score de velocidad de tick (detección de rechazos) |
| `micro_trend` | Pendiente lineal intrabarra (acumulación/distribución) |
| `volume_delta` | Diferencia volumen comprador/vendedor |
| `volume_real` | Volumen real desde flags de MT5 |

```python
from data_factory.tick_collector import TickCollector

collector = TickCollector(symbol="EURUSD")
df = collector.full_pipeline(from_date="2026-05-01")
collector.export_to_csv(df, "data/eurusd_ticks.csv")
collector.disconnect()
```

## ⚙️ Requisitos

- Python 3.9+
- MetaTrader 5 instalado y configurado
- Conexión a internet para descarga de datos


