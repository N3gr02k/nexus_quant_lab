"""
NEXUS QUANT LAB — V5.1 War Room Sentinel
==========================================
war_room_sentinel_v5.py

EL SEMÁFORO DEL CONSEJO — Dashboard de monitoreo en tiempo real.

Muestra el estado del Consejo de Centinelas con:
  - Semáforo 🟢🟡🔴 con el veredicto actual
  - Banner de veto con razón forense
  - Perfil de vetos (gráfico de barras)
  - Estadísticas en vivo del orquestador

Integración con producción:
  from production.war_room_sentinel_v5 import WarRoomSentinel
  war_room = WarRoomSentinel()
  war_room.update(orchestrator.get_war_room_status())
  war_room.render()  # → HTML/CSS/JS listo para servir

Autor: Nexus Quant Lab
Fecha: 2026-06-01
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger("WarRoomSentinel")


class WarRoomSentinel:
    """
    War Room V5.1 — El Semáforo del Consejo de Centinelas.
    
    Genera un dashboard HTML autónomo que muestra:
      - Semáforo grande (VERDE/AMARILLO/ROJO)
      - Banner de veto con razón
      - Panel de estadísticas del Consejo
      - Perfil de vetos (barras horizontales)
      - Log de auditoría en tiempo real
    
    Uso:
      war_room = WarRoomSentinel(title="NEXUS QUANT LAB — WAR ROOM")
      war_room.update(status_data)
      war_room.render()  # → imprime HTML
      war_room.save("war_room.html")  # → guarda a archivo
    """
    
    def __init__(self, title: str = "🛡️ CONSEJO DE CENTINELAS — WAR ROOM V5.1"):
        self.title = title
        self.status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "semaphore": "GRIS",
            "council": {
                "approved": 0,
                "vetoed": 0,
                "consecutive_losses": 0,
                "daily_pnl": 0.0,
                "last_verdict": "INIT",
            },
            "veto_profile": {
                "total_vetoes": 0,
                "layers": {},
                "last_verdict": "INIT",
            },
            "orchestrator": {
                "signals_processed": 0,
                "orders_executed": 0,
                "orders_vetoed": 0,
                "uptime_minutes": 0,
            },
            "last_signal": None,
        }
        
        # Historial de alertas
        self.alerts: List[Dict] = []
        self._add_alert("INFO", "🛡️ Consejo de Centinelas inicializado")
    
    def update(self, status_data: dict):
        """
        Actualiza el estado del War Room con datos del orquestador.
        
        Args:
            status_data: Diccionario de get_war_room_status()
        """
        old_semaphore = self.status.get("semaphore")
        self.status = status_data
        
        # Detectar cambios de semáforo
        new_semaphore = status_data.get("semaphore", "GRIS")
        if old_semaphore and old_semaphore != new_semaphore:
            icon = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴", "GRIS": "⚪"}
            self._add_alert(
                "INFO",
                f"Semáforo cambió: {icon.get(old_semaphore, '❓')} → {icon.get(new_semaphore, '❓')} ({new_semaphore})"
            )
        
        # Detectar vetos
        last_verdict = status_data.get("council", {}).get("last_verdict", "")
        if last_verdict and "VETO" in str(last_verdict):
            self._add_alert("VETO", f"🛡️ {last_verdict}")
        
        # Detectar pérdidas consecutivas
        losses = status_data.get("council", {}).get("consecutive_losses", 0)
        if losses >= 3:
            self._add_alert("CRITICAL", f"🚨 {losses} pérdidas consecutivas. Operaciones pausadas.")
        elif losses >= 2:
            self._add_alert("WARNING", f"⚠️ {losses} pérdidas consecutivas. Precaución.")
    
    def _add_alert(self, alert_type: str, message: str):
        """Añade una alerta al historial."""
        self.alerts.append({
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "type": alert_type,
            "message": message,
        })
        # Mantener solo últimas 50 alertas
        if len(self.alerts) > 50:
            self.alerts = self.alerts[-50:]
    
    def render(self) -> str:
        """
        Genera el HTML completo del War Room.
        
        Returns:
            String HTML con el dashboard completo
        """
        semaphore = self.status.get("semaphore", "GRIS")
        council = self.status.get("council", {})
        veto_profile = self.status.get("veto_profile", {})
        orchestrator = self.status.get("orchestrator", {})
        last_signal = self.status.get("last_signal", {})
        
        # ─── Configuración de colores ───
        semaphore_colors = {
            "VERDE": {"bg": "#00FF88", "shadow": "#00FF8866", "text": "#003311", "icon": "🟢"},
            "AMARILLO": {"bg": "#FFD700", "shadow": "#FFD70066", "text": "#332200", "icon": "🟡"},
            "ROJO": {"bg": "#FF3333", "shadow": "#FF333366", "text": "#330000", "icon": "🔴"},
            "GRIS": {"bg": "#666666", "shadow": "#66666644", "text": "#111111", "icon": "⚪"},
        }
        sc = semaphore_colors.get(semaphore, semaphore_colors["GRIS"])
        
        # ─── Perfil de vetos ───
        veto_layers = veto_profile.get("layers", {})
        total_vetoes = veto_profile.get("total_vetoes", 0)
        
        veto_bars = ""
        layer_colors = {
            "HORA": "#e94560",
            "VELOCIDAD": "#0f3460",
            "VOLUMEN": "#533483",
            "REGIMEN": "#e94560",
            "CONFIANZA": "#16213e",
        }
        
        if total_vetoes > 0:
            for layer, count in sorted(veto_layers.items(), key=lambda x: x[1], reverse=True):
                pct = count / total_vetoes * 100
                color = layer_colors.get(layer.upper(), "#0f3460")
                veto_bars += f"""
                <div class="veto-bar-container">
                    <div class="veto-label">{layer}</div>
                    <div class="veto-bar-bg">
                        <div class="veto-bar" style="width: {pct:.1f}%; background: {color};"></div>
                    </div>
                    <div class="veto-count">{count} ({pct:.1f}%)</div>
                </div>
                """
        else:
            veto_bars = '<div class="no-data">No hay vetos registrados</div>'
        
        # ─── Último veto ───
        last_veto_reason = veto_profile.get("last_veto_reason", "")
        last_verdict = council.get("last_verdict", "INIT")
        
        if last_verdict and "VETO" in str(last_verdict):
            veto_banner = f"""
            <div class="veto-banner">
                🛡️ ÚLTIMO VETO: {last_veto_reason or last_verdict}
            </div>
            """
        elif last_verdict == "APROBADO":
            veto_banner = """
            <div class="approve-banner">
                ✅ ÚLTIMA ORDEN: APROBADA POR EL CONSEJO
            </div>
            """
        else:
            veto_banner = """
            <div class="init-banner">
                ⚪ CONSEJO: INIT — Esperando primera señal
            </div>
            """
        
        # ─── Última señal ───
        signal_html = ""
        if last_signal and last_signal.get("symbol"):
            signal_html = f"""
            <div class="signal-card">
                <div class="signal-symbol">{last_signal['symbol']}</div>
                <div class="signal-direction">{last_signal['direction']}</div>
                <div class="signal-proba">{(last_signal['proba']*100):.0f}%</div>
            </div>
            """
        else:
            signal_html = '<div class="no-data">Esperando señal...</div>'
        
        # ─── Alertas ───
        alerts_html = ""
        for alert in self.alerts[-10:]:  # Últimas 10 alertas
            icon_map = {
                "CRITICAL": "🚨",
                "WARNING": "⚠️",
                "VETO": "🛡️",
                "INFO": "🔵",
                "SUCCESS": "✅",
            }
            icon = icon_map.get(alert["type"], "ℹ️")
            color_map = {
                "CRITICAL": "#FF3333",
                "WARNING": "#FFD700",
                "VETO": "#e94560",
                "INFO": "#00BFFF",
                "SUCCESS": "#00FF88",
            }
            color = color_map.get(alert["type"], "#FFFFFF")
            
            alerts_html += f"""
            <div class="alert-entry" style="border-left: 3px solid {color};">
                <span class="alert-time">{alert['timestamp']}</span>
                <span class="alert-icon">{icon}</span>
                <span class="alert-msg">{alert['message']}</span>
            </div>
            """
        
        if not alerts_html:
            alerts_html = '<div class="no-data">Sin alertas</div>'
        
        # ─── Tasa de aprobación ───
        total_orders = council.get("approved", 0) + council.get("vetoed", 0)
        approval_rate = (council.get("approved", 0) / total_orders * 100) if total_orders > 0 else 0
        
        # ─── HTML completo ───
        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self.title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            background: #0a0a1a;
            color: #e0e0e0;
            font-family: 'Courier New', 'Consolas', monospace;
            padding: 20px;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        
        /* ─── HEADER ─── */
        .header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 20px;
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            border: 1px solid #0f3460;
            border-radius: 12px;
            margin-bottom: 20px;
        }}
        
        .header-title {{
            font-size: 18px;
            font-weight: bold;
            color: #00FF88;
            text-shadow: 0 0 10px #00FF8844;
        }}
        
        .header-time {{
            font-size: 14px;
            color: #888;
        }}
        
        /* ─── SEMÁFORO ─── */
        .semaphore-section {{
            display: flex;
            align-items: center;
            gap: 30px;
            padding: 30px;
            background: #1a1a2e;
            border: 1px solid #16213e;
            border-radius: 12px;
            margin-bottom: 20px;
        }}
        
        .semaphore {{
            width: 120px;
            height: 120px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 48px;
            background: {sc['bg']};
            box-shadow: 0 0 30px {sc['shadow']};
            transition: all 0.5s ease;
            flex-shrink: 0;
        }}
        
        .semaphore-label {{
            font-size: 24px;
            font-weight: bold;
            color: {sc['bg']};
            text-shadow: 0 0 15px {sc['shadow']};
        }}
        
        .semaphore-stats {{
            flex: 1;
        }}
        
        .semaphore-stats .stat-row {{
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            font-size: 14px;
            border-bottom: 1px solid #16213e;
        }}
        
        .stat-value {{
            color: #00FF88;
            font-weight: bold;
        }}
        
        .stat-value.red {{ color: #FF3333; }}
        .stat-value.yellow {{ color: #FFD700; }}
        
        /* ─── BANNERS ─── */
        .veto-banner {{
            padding: 12px 20px;
            background: rgba(255, 51, 51, 0.15);
            border: 1px solid #FF3333;
            border-radius: 8px;
            color: #FF6666;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        
        .approve-banner {{
            padding: 12px 20px;
            background: rgba(0, 255, 136, 0.1);
            border: 1px solid #00FF88;
            border-radius: 8px;
            color: #00FF88;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        
        .init-banner {{
            padding: 12px 20px;
            background: rgba(102, 102, 102, 0.15);
            border: 1px solid #666;
            border-radius: 8px;
            color: #999;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        
        /* ─── GRID ─── */
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }}
        
        .card {{
            background: #1a1a2e;
            border: 1px solid #16213e;
            border-radius: 12px;
            padding: 20px;
        }}
        
        .card-title {{
            font-size: 14px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-bottom: 15px;
            border-bottom: 1px solid #16213e;
            padding-bottom: 10px;
        }}
        
        /* ─── STAT CARDS ─── */
        .stats-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }}
        
        .stat-card {{
            background: #16213e;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
        }}
        
        .stat-card .number {{
            font-size: 28px;
            font-weight: bold;
            color: #00FF88;
        }}
        
        .stat-card .number.red {{ color: #FF3333; }}
        .stat-card .number.yellow {{ color: #FFD700; }}
        .stat-card .label {{
            font-size: 11px;
            color: #888;
            margin-top: 4px;
            text-transform: uppercase;
        }}
        
        /* ─── VETO BARS ─── */
        .veto-bar-container {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 6px 0;
        }}
        
        .veto-label {{
            width: 100px;
            font-size: 12px;
            color: #aaa;
            text-align: right;
        }}
        
        .veto-bar-bg {{
            flex: 1;
            height: 20px;
            background: #0a0a1a;
            border-radius: 4px;
            overflow: hidden;
        }}
        
        .veto-bar {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.5s ease;
            min-width: 2px;
        }}
        
        .veto-count {{
            width: 100px;
            font-size: 12px;
            color: #888;
        }}
        
        /* ─── SIGNAL CARD ─── */
        .signal-card {{
            display: flex;
            align-items: center;
            gap: 15px;
            padding: 15px;
            background: #16213e;
            border-radius: 8px;
        }}
        
        .signal-symbol {{
            font-size: 20px;
            font-weight: bold;
            color: #00FF88;
        }}
        
        .signal-direction {{
            font-size: 16px;
            padding: 4px 12px;
            border-radius: 4px;
            background: #0f3460;
        }}
        
        .signal-proba {{
            font-size: 24px;
            font-weight: bold;
            color: #FFD700;
            margin-left: auto;
        }}
        
        /* ─── ALERTS ─── */
        .alert-entry {{
            padding: 8px 12px;
            margin: 4px 0;
            background: #16213e;
            border-radius: 4px;
            font-size: 12px;
            display: flex;
            gap: 8px;
            align-items: center;
        }}
        
        .alert-time {{
            color: #666;
            font-size: 11px;
            min-width: 60px;
        }}
        
        .alert-icon {{
            min-width: 20px;
        }}
        
        .alert-msg {{
            flex: 1;
        }}
        
        /* ─── NO DATA ─── */
        .no-data {{
            color: #555;
            font-style: italic;
            text-align: center;
            padding: 20px;
        }}
        
        /* ─── FOOTER ─── */
        .footer {{
            text-align: center;
            padding: 20px;
            color: #444;
            font-size: 11px;
            border-top: 1px solid #16213e;
            margin-top: 20px;
        }}
        
        /* ─── RESPONSIVE ─── */
        @media (max-width: 768px) {{
            .grid {{
                grid-template-columns: 1fr;
            }}
            .semaphore-section {{
                flex-direction: column;
                text-align: center;
            }}
            .stats-grid {{
                grid-template-columns: 1fr 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- HEADER -->
        <div class="header">
            <div class="header-title">🛡️ CONSEJO DE CENTINELAS</div>
            <div class="header-time">⏱️ {self.status.get('timestamp', '—')}</div>
        </div>
        
        <!-- SEMÁFORO -->
        <div class="semaphore-section">
            <div class="semaphore">{sc['icon']}</div>
            <div class="semaphore-stats">
                <div class="semaphore-label">{semaphore}</div>
                <div class="stat-row">
                    <span>✅ Órdenes aprobadas</span>
                    <span class="stat-value">{council.get('approved', 0)}</span>
                </div>
                <div class="stat-row">
                    <span>❌ Órdenes vetadas</span>
                    <span class="stat-value red">{council.get('vetoed', 0)}</span>
                </div>
                <div class="stat-row">
                    <span>🔥 Rachas de pérdidas</span>
                    <span class="stat-value {'red' if council.get('consecutive_losses', 0) >= 3 else 'yellow' if council.get('consecutive_losses', 0) >= 2 else ''}">{council.get('consecutive_losses', 0)}</span>
                </div>
                <div class="stat-row">
                    <span>💰 P&L Diario</span>
                    <span class="stat-value {'red' if council.get('daily_pnl', 0) < 0 else 'green'}">${council.get('daily_pnl', 0):.2f}</span>
                </div>
            </div>
        </div>
        
        <!-- BANNER -->
        {veto_banner}
        
        <!-- GRID PRINCIPAL -->
        <div class="grid">
            <!-- ESTADÍSTICAS -->
            <div class="card">
                <div class="card-title">📊 Estadísticas del Consejo</div>
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="number">{council.get('approved', 0)}</div>
                        <div class="label">✅ Aprobadas</div>
                    </div>
                    <div class="stat-card">
                        <div class="number red">{council.get('vetoed', 0)}</div>
                        <div class="label">❌ Vetadas</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">{approval_rate:.1f}%</div>
                        <div class="label">📈 Tasa Aprobación</div>
                    </div>
                    <div class="stat-card">
                        <div class="number {'red' if council.get('consecutive_losses', 0) >= 3 else 'yellow' if council.get('consecutive_losses', 0) >= 2 else ''}">{council.get('consecutive_losses', 0)}</div>
                        <div class="label">🔥 Rachas</div>
                    </div>
                </div>
            </div>
            
            <!-- PERFIL DE VETOS -->
            <div class="card">
                <div class="card-title">📋 Perfil de Vetos</div>
                {veto_bars}
            </div>
            
            <!-- ORQUESTADOR -->
            <div class="card">
                <div class="card-title">⚙️ Orquestador V8.0</div>
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="number">{orchestrator.get('signals_processed', 0)}</div>
                        <div class="label">📡 Señales</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">{orchestrator.get('orders_executed', 0)}</div>
                        <div class="label">📤 Ejecutadas</div>
                    </div>
                    <div class="stat-card">
                        <div class="number red">{orchestrator.get('orders_vetoed', 0)}</div>
                        <div class="label">🛡️ Vetadas</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">{orchestrator.get('uptime_minutes', 0)}</div>
                        <div class="label">⏱️ Minutos</div>
                    </div>
                </div>
            </div>
            
            <!-- ÚLTIMA SEÑAL -->
            <div class="card">
                <div class="card-title">📡 Última Señal del Sniper</div>
                {signal_html}
            </div>
        </div>
        
        <!-- LOG DE ALERTAS -->
        <div class="card">
            <div class="card-title">🚨 Alertas del Consejo</div>
            {alerts_html}
        </div>
        
        <!-- FOOTER -->
        <div class="footer">
            Nexus Quant Lab — V8.4 Sentinel Council | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
        </div>
    </div>
    
    <script>
        // Auto-refresh cada 5 segundos
        setTimeout(function() {{
            location.reload();
        }}, 5000);
    </script>
</body>
</html>"""
        
        return html
    
    def save(self, filepath: str = "war_room.html"):
        """
        Guarda el War Room a un archivo HTML.
        
        Args:
            filepath: Ruta del archivo HTML
        """
        html = self.render()
        
        # Crear directorio si no existe
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        
        logger.info(f"📁 War Room guardado: {filepath}")
        return filepath


# ──────────────────────────────────────────────
# DEMO: GENERAR WAR ROOM
# ──────────────────────────────────────────────

def run_demo():
    """
    Genera un War Room de demostración con datos simulados.
    """
    print("\n" + "=" * 70)
    print("🖥️ V5.0 DEMO: WAR ROOM SENTINEL")
    print("   Generando dashboard del Consejo de Centinelas...")
    print("=" * 70)
    
    # Simular datos de prueba
    demo_status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "semaphore": "VERDE",
        "council": {
            "approved": 12,
            "vetoed": 8,
            "consecutive_losses": 1,
            "daily_pnl": 245.50,
            "last_verdict": "APROBADO",
        },
        "veto_profile": {
            "total_vetoes": 8,
            "layers": {
                "HORA": 3,
                "VELOCIDAD": 2,
                "VOLUMEN": 2,
                "REGIMEN": 1,
                "CONFIANZA": 0,
            },
            "last_verdict": "APROBADO",
            "last_veto_reason": "Volumen Institucional en contra (volume_delta=-0.35 en contra de LONG)",
        },
        "orchestrator": {
            "signals_processed": 20,
            "orders_executed": 12,
            "orders_vetoed": 8,
            "uptime_minutes": 145,
        },
        "last_signal": {
            "symbol": "EURUSD",
            "direction": "LONG",
            "proba": 0.92,
        },
    }
    
    # Crear War Room
    war_room = WarRoomSentinel()
    war_room.update(demo_status)
    
    # Añadir alertas de demostración
    war_room._add_alert("SUCCESS", "✅ EURUSD LONG aprobada por el Consejo")
    war_room._add_alert("VETO", "🛡️ VETO: Volumen Institucional en contra")
    war_room._add_alert("WARNING", "⚠️ 2 pérdidas consecutivas. Precaución.")
    war_room._add_alert("INFO", "🔵 Semáforo cambió: 🟡 → 🟢 (VERDE)")
    
    # Guardar
    output_path = "war_room.html"
    war_room.save(output_path)
    
    print(f"\n✅ War Room generado: {output_path}")
    print(f"   📊 Semáforo: {demo_status['semaphore']}")
    print(f"   ✅ Aprobadas: {demo_status['council']['approved']}")
    print(f"   ❌ Vetadas: {demo_status['council']['vetoed']}")
    print(f"   📈 Tasa: {demo_status['council']['approved'] / (demo_status['council']['approved'] + demo_status['council']['vetoed']) * 100:.1f}%")
    
    return war_room


if __name__ == "__main__":
    war_room = run_demo()
