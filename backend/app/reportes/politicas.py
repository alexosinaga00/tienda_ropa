"""Cálculos compartidos entre CU-33 y CU-34: ninguno de los dos es un
caso de uso aparte, son fórmulas de una línea que ambos necesitan."""

from decimal import Decimal

_CERO = Decimal("0")


def ticket_promedio(total_ventas: Decimal, transacciones: int) -> Decimal:
    if transacciones == 0:
        return _CERO
    return (total_ventas / transacciones).quantize(Decimal("0.01"))


def tasa_conversion(por_estado: list[dict], ventas_con_reserva: int) -> float:
    total_reservas = sum(fila["cantidad"] for fila in por_estado)
    if total_reservas == 0:
        return 0.0
    return round(ventas_con_reserva / total_reservas, 4)
