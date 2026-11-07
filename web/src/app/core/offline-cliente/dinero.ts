/**
 * Dinero del modo sin conexión del cliente. Los montos viajan y se guardan como TEXTO ("129.00") y las sumas se hacen
 * en centavos enteros, para que el total que el cliente acepta sea exactamente el que se manda al servidor.
 */

/** "129.50" o 129.5 -> 12950. Lo que no es un número da 0. */
export function aCentavos(valor: number | string | null | undefined): number {
  const numero = typeof valor === 'string' ? Number(valor) : (valor ?? 0);
  return Number.isFinite(numero) ? Math.round(numero * 100) : 0;
}

/** 12950 -> "129.50". */
export function textoDinero(centavos: number): string {
  const signo = centavos < 0 ? '-' : '';
  const absoluto = Math.abs(Math.round(centavos));
  return `${signo}${Math.floor(absoluto / 100)}.${String(absoluto % 100).padStart(2, '0')}`;
}

/** Suma de `precio_unitario x cantidad` de las líneas, en centavos. */
export function totalDeLineas(lineas: { precio_unitario: string; cantidad: number }[]): number {
  return lineas.reduce((suma, l) => suma + aCentavos(l.precio_unitario) * l.cantidad, 0);
}
