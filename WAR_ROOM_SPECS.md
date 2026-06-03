# 📋 WAR ROOM MASTER V5.0 — CONSTITUCIÓN VISUAL

Este es el estándar definitivo. NO se permiten cambios que omitan estas capas:

1. **OTE GLOW (Dorado)**: 
   - Debe tener un rectángulo de fondo `rgba(255, 215, 0, 0.12)`.
   - Borde sólido color `gold` (width=1).
   - 3 líneas internas (618, 705, 790) con etiquetas fondo ORO y texto NEGRO.
2. **ALINEACIÓN L/R**:
   - Izquierda: Muros HTF Púrpura.
   - Derecha: Niveles Intradía, Fibo y Precios Live.
3. **PRECIOS LIVE**: Bid y Ask deben ser visibles con etiquetas de precio a 5 decimales.
4. **CHART SHIFT**: El eje X debe proyectarse 10 periodos al futuro.
5. **PERSISTENCIA**: La probabilidad de la IA calculada al inicio de la hora debe permanecer en el título los 60 min.

---

## 🏛️ CONSTITUCIÓN VISUAL — CAPAS OBLIGATORIAS

| # | Capa | Color | Opacidad | Posición | Prioridad |
|---|------|-------|----------|----------|-----------|
| 1 | Fondo NY Session | Blanco | 0.05 | Fondo | 0 (más fondo) |
| 2 | OTE Zone (Glow) | Dorado | 0.12 | Fondo velas | 1 |
| 3 | FIB 0.618 | gold | 0.8 | Derecha | 2 |
| 4 | OTE 0.705 | gold | 0.8 | Derecha | 3 |
| 5 | FIB 0.790 | gold | 0.8 | Derecha | 4 |
| 6 | HTF HIGH | #BF00FF | 0.8 | Izquierda | 5 |
| 7 | HTF LOW | #BF00FF | 0.8 | Izquierda | 6 |
| 8 | BID | Blanco | 0.4 | Derecha | 7 |
| 9 | ASK | #FF3131 | 0.8 | Derecha | 8 |
| 10 | $ Sweeps | #FF00FF/#00FFFF | 0.9 | Sobre velas | 9 |

---

## 🔧 ESPECIFICACIONES TÉCNICAS

### OTE Zone (Zona de Oro)
```python
fig.add_hrect(
    y0=fib_790, y1=fib_618,
    fillcolor="rgba(255, 215, 0, 0.12)",  # Opacidad 0.12 — VISIBLE
    line=dict(color="gold", width=1, dash="solid"),  # Borde SÓLIDO
    layer="below"
)
```

### Etiquetas Fibonacci
```python
add_level(fib_618, "gold", "FIB 0.618", style="dot", width=1)
add_level(fib_705, "gold", "OTE 0.705", style="solid", width=2)
add_level(fib_790, "gold", "FIB 0.790", style="dot", width=1)
```

### Muros HTF (Izquierda)
```python
add_level(d1_high, "#BF00FF", "HTF HIGH", side="left", style="solid", width=2)
add_level(d1_low, "#BF00FF", "HTF LOW", side="left", style="solid", width=2)
```

---

## 🚫 REGLAS DE NO MODIFICACIÓN

1. **NUNCA** reducir la opacidad del OTE por debajo de 0.12.
2. **NUNCA** cambiar el borde del OTE a "dash" o "dot" — debe ser "solid".
3. **NUNCA** mover los Muros HTF a la derecha — deben estar a la izquierda.
4. **NUNCA** eliminar las etiquetas de precio a 5 decimales.
5. **NUNCA** cambiar el fondo negro (`paper_bgcolor="black"`, `plot_bgcolor="black"`).

---

## 📐 FORMATO DE SALIDA

- **Archivo**: `logs/war_map.html`
- **Auto-refresh**: Cada 30 segundos (`<meta http-equiv="refresh" content="30">`)
- **Altura**: 850px
- **Márgenes**: r=160, l=160 (espacio para etiquetas)
- **Template**: `plotly_dark`

---

## 🔄 INTEGRACIÓN CON PRODUCCIÓN

```python
from production.war_map_generator_v2 import generate_war_map

# En el bucle principal del orquestador
generate_war_map(
    df=df,
    proba=signal.proba,
    direction=1 if signal.direction == "LONG" else -1,
    d1_high=d1_high,
    d1_low=d1_low,
    bid=current_bid,
    ask=current_ask,
    symbol="EURUSD",
    verdict=verdict.status,  # "APROBADO" | "VETADO" | "INIT"
    reason=verdict.reason,
    output_path="logs/war_map.html",
)
```

---

## 📜 HISTORIAL DE VERSIONES

| Versión | Fecha | Cambio |
|---------|-------|--------|
| V1.0 | 2026-05-01 | Versión inicial con velas y niveles básicos |
| V2.0 | 2026-05-10 | Añadidos Muros HTF y Zona OTE |
| V3.0 | 2026-05-15 | Añadidos símbolos $ LuxAlgo |
| V4.0 | 2026-05-25 | Añadidas sesiones NY y Bid/Ask |
| **V5.0** | **2026-06-01** | **THE GOLDEN RECOVERY — OTE Glow restaurado, alineación L/R corregida** |
