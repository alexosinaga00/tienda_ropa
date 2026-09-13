"""Diagramas de tiempo UML (notación de State Lifeline) para FashionStore.

Enterprise Architect no permite cargar por automatización los estados y
transiciones de un State Lifeline, así que se dibujan con la misma notación:
marco «timing», una franja por lifeline con sus estados en el eje Y, la línea
de estado escalonada, eventos en cada transición, mensajes entre lifelines y
restricciones de duración entre llaves. Los estados y eventos salen del código
(reservas/service.py, ventas/service.py, pagos/service.py).
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Polygon, Rectangle

SALIDA = Path(__file__).parent / "diagramas"
COLOR_LINEA = "#1C1713"
COLOR_FRANJA = "#F7F2EA"
COLOR_BORDE = "#6E6156"
COLOR_EVENTO = "#732E16"


def diagrama(archivo, titulo, eje_tiempo, lifelines, mensajes=(), restricciones=(), ancho=16):
    """lifelines: [(nombre, [estados de arriba a abajo], [(t, estado)...])] ; la última
    tupla de cada lifeline marca el final. mensajes: [(t, lifeline_origen, lifeline_destino, texto)].
    restricciones: [(lifeline, t_inicio, t_fin, texto)]."""
    alto_estado = 0.55
    alturas = [len(e) * alto_estado + 0.9 for _, e, _ in lifelines]
    alto_total = sum(alturas) + 1.6
    fig, ax = plt.subplots(figsize=(ancho, alto_total * 0.95))
    t_min, t_max = eje_tiempo[0][0], eje_tiempo[-1][0]
    x0, x1 = 0.0, 1.0
    izq = 0.19

    def X(t):
        return izq + (t - t_min) / (t_max - t_min) * (0.97 - izq)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, alto_total)
    ax.axis("off")
    # marco UML
    ax.add_patch(Rectangle((0.005, 0.05), 0.99, alto_total - 0.1, fill=False, ec=COLOR_BORDE, lw=1.2))
    etiqueta = f"timing {titulo}"
    largo = 0.012 * len(etiqueta) * 0.55 + 0.02
    ax.add_patch(Polygon([(0.005, alto_total - 0.05), (0.005 + largo, alto_total - 0.05),
                          (0.005 + largo, alto_total - 0.35), (0.005 + largo - 0.012, alto_total - 0.5),
                          (0.005, alto_total - 0.5)], closed=True, fill=False, ec=COLOR_BORDE, lw=1.2))
    ax.text(0.012, alto_total - 0.27, etiqueta, fontsize=10, fontweight="bold", va="center", color=COLOR_LINEA)

    posiciones = {}
    y_top = alto_total - 0.8
    for (nombre, estados, cambios), alto in zip(lifelines, alturas):
        y_bottom = y_top - alto
        ax.add_patch(Rectangle((0.02, y_bottom), 0.96, alto, fc=COLOR_FRANJA, ec=COLOR_BORDE, lw=1))
        ax.plot([0.055, 0.055], [y_bottom, y_top], color=COLOR_BORDE, lw=1)
        ax.text(0.037, (y_top + y_bottom) / 2, nombre, rotation=90, ha="center", va="center", fontsize=9, fontweight="bold")
        y_estado = {}
        for i, estado in enumerate(estados):
            y = y_top - 0.55 - i * alto_estado
            y_estado[estado] = y
            ax.text(izq - 0.01, y, estado, ha="right", va="center", fontsize=8.5, color=COLOR_LINEA)
            ax.plot([izq, 0.97], [y, y], color="#DBD0C1", lw=0.6, ls=":")
        posiciones[nombre] = (y_bottom, y_top, y_estado)
        # línea de estado escalonada con eventos
        for (t, estado, *evento), (t2, estado2, *_) in zip(cambios, cambios[1:]):
            ax.plot([X(t), X(t2)], [y_estado[estado], y_estado[estado]], color=COLOR_LINEA, lw=2)
            if estado2 != estado:
                ax.plot([X(t2), X(t2)], [y_estado[estado], y_estado[estado2]], color=COLOR_LINEA, lw=2)
        for t, estado, *evento in cambios[1:-1] if len(cambios) > 2 else []:
            pass
        for (t, estado, *evento) in cambios:
            if evento and evento[0]:
                ax.text(X(t) + 0.004, y_estado[estado] + 0.13, evento[0], fontsize=7.5, color=COLOR_EVENTO, style="italic")
        y_top = y_bottom - 0.25

    for t, origen, destino, texto in mensajes:
        _, _, eo = posiciones[origen]
        yb_o, _, _ = posiciones[origen]
        _, yt_d, _ = posiciones[destino]
        ax.add_patch(FancyArrowPatch((X(t), yb_o + 0.05), (X(t), yt_d - 0.05), arrowstyle="-|>", mutation_scale=12,
                                     color=COLOR_BORDE, lw=1, ls="--"))
        ax.text(X(t) + 0.005, (yb_o + yt_d) / 2, texto, fontsize=7.5, color=COLOR_BORDE, va="center")

    for lifeline, ta, tb, texto in restricciones:
        yb, _, _ = posiciones[lifeline]
        y = yb + 0.18
        ax.add_patch(FancyArrowPatch((X(ta), y), (X(tb), y), arrowstyle="<|-|>", mutation_scale=10, color="#9A3E1F", lw=1))
        ax.text((X(ta) + X(tb)) / 2, y + 0.06, texto, ha="center", fontsize=8, color="#9A3E1F", fontweight="bold")

    # eje de tiempo
    y_eje = 0.35
    ax.plot([izq, 0.97], [y_eje, y_eje], color=COLOR_BORDE, lw=1)
    for t, etiqueta_t in eje_tiempo:
        ax.plot([X(t), X(t)], [y_eje - 0.05, y_eje + 0.05], color=COLOR_BORDE, lw=1)
        ax.text(X(t), y_eje - 0.14, etiqueta_t, ha="center", va="top", fontsize=7.5, color=COLOR_BORDE)
    fig.savefig(SALIDA / archivo, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  ", archivo)


SALIDA.mkdir(exist_ok=True)

# TIE-01: una reserva que el cliente no retira y expira (CU-16, CU-20, tarea de expiración)
diagrama(
    "TIE-01.png", "TIE-01 Reserva no retirada que expira",
    [(0, "D-1 10:00"), (23, "D 09:00"), (32, "D 18:00\n(fin de franja)"), (56, "D+1 18:00"), (62, "D+1 18:05")],
    [
        ("reserva : Reserva", ["pendiente", "preparada", "expirada"],
         [(0, "pendiente", "crearReserva()"), (23, "preparada", "prepararReserva()"), (56.4, "expirada", "expirarReservas()"), (62, "expirada")]),
        ("stock : Stock", ["reservado", "disponible"],
         [(0, "reservado", "reservarStock()"), (56.4, "disponible", "liberarStock()"), (62, "disponible")]),
    ],
    mensajes=[(56.4, "reserva : Reserva", "stock : Stock", "liberar unidades")],
    restricciones=[("reserva : Reserva", 32, 56, "{ fecha_expiracion = fin de franja + 24 h }")],
)

# TIE-02: compra digital con pago aprobado por la pasarela (CU-23, CU-24, CU-29)
diagrama(
    "TIE-02.png", "TIE-02 Compra digital con pago por pasarela",
    [(0, "0 s"), (2, "2 s"), (40, "≈ 40 s"), (45, "45 s"), (50, "50 s")],
    [
        ("venta : Venta", ["pendiente_pago", "pagada"],
         [(0, "pendiente_pago", "registrarVentaDigital()"), (41, "pagada", "confirmarVenta()"), (50, "pagada")]),
        ("pago : Pago", ["iniciado", "aprobado"],
         [(2, "iniciado", "iniciarPagoPasarela()"), (40, "aprobado", "webhook firmado"), (50, "aprobado")]),
        ("stock : Stock", ["reservado", "descontado"],
         [(0, "reservado", "reservarStock()"), (41, "descontado", "registrarMovimiento(venta)"), (50, "descontado")]),
    ],
    mensajes=[(40.5, "pago : Pago", "venta : Venta", "aprobado"), (41.2, "venta : Venta", "stock : Stock", "descontar")],
    restricciones=[("pago : Pago", 2, 40, "{ el cliente completa el pago en la pasarela (sandbox) }")],
)

# TIE-03: atención de una reserva en sucursal con compra parcial (CU-20, CU-25, CU-30)
diagrama(
    "TIE-03.png", "TIE-03 Atención de reserva en sucursal con compra parcial",
    [(0, "09:00"), (2, "09:10"), (10, "14:00"), (11, "14:05"), (13, "14:30"), (14, "14:35"), (16, "14:40")],
    [
        ("reserva : Reserva", ["pendiente", "preparada", "en_prueba", "completada"],
         [(0, "pendiente"), (2, "preparada", "prepararReserva()"), (10, "en_prueba", "confirmarLlegada()"),
          (13, "completada", "registrarSeleccion()"), (16, "completada")]),
        ("stock : Stock", ["reservado", "parcialmente liberado", "vendido"],
         [(0, "reservado"), (13, "parcialmente liberado", "liberar no seleccionadas"), (14, "vendido", "pagarEnCaja()"), (16, "vendido")]),
    ],
    mensajes=[(13.1, "reserva : Reserva", "stock : Stock", "liberar")],
    restricciones=[("reserva : Reserva", 10, 13, "{ prueba dentro de la franja 14:00–15:00 }")],
)
