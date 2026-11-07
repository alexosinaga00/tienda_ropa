/** Un código QR listo para dibujar en un `<svg>`: una sola ruta (sin HTML que sanear) dentro de un cuadrado. */
export interface QrSvg {
  /** Lado del cuadrado del `viewBox`, con la zona de silencio incluida. */
  lado: number;
  /** Atributo `d` de un `<path>`: un rectángulo por cada tramo horizontal de módulos oscuros. */
  ruta: string;
}

/** Los módulos en blanco que rodean al código para que un lector lo encuentre (el estándar pide 4; 2 basta en pantalla). */
const ZONA_DE_SILENCIO = 2;

interface ApiQr {
  create(texto: string, opciones?: { errorCorrectionLevel?: 'L' | 'M' | 'Q' | 'H' }): {
    modules: { size: number; get(fila: number, columna: number): number };
  };
}

/**
 * Calcula el QR de un texto. La librería `qrcode` se carga bajo demanda (import dinámico): solo la pide la pantalla del
 * comprobante, así que no engorda el paquete inicial. No toca el DOM ni la red.
 */
export async function generarQr(texto: string): Promise<QrSvg> {
  const modulo = (await import('qrcode')) as unknown as ApiQr & { default?: ApiQr };
  const api: ApiQr = typeof modulo.create === 'function' ? modulo : (modulo.default as ApiQr);
  const { modules } = api.create(texto, { errorCorrectionLevel: 'M' });
  const tamano = modules.size;

  const tramos: string[] = [];
  for (let fila = 0; fila < tamano; fila++) {
    let columna = 0;
    while (columna < tamano) {
      if (!modules.get(fila, columna)) {
        columna++;
        continue;
      }
      const inicio = columna;
      while (columna < tamano && modules.get(fila, columna)) columna++;
      tramos.push(`M${inicio + ZONA_DE_SILENCIO} ${fila + ZONA_DE_SILENCIO}h${columna - inicio}v1h-${columna - inicio}z`);
    }
  }
  return { lado: tamano + ZONA_DE_SILENCIO * 2, ruta: tramos.join('') };
}
