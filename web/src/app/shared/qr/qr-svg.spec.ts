import { generarQr } from './qr-svg';

describe('generarQr', () => {
  it('devuelve un cuadrado con zona de silencio y una ruta de rectángulos', async () => {
    const qr = await generarQr('https://fashionstore.example/caja?venta=VTA-0001');

    // Versión 1 mide 21 módulos; una dirección de este largo necesita una versión mayor. Siempre cuadrado impar + 4.
    expect(qr.lado).toBeGreaterThan(25);
    expect((qr.lado - 4) % 4).toBe(1);
    expect(qr.ruta).toMatch(/^(M\d+ \d+h\d+v1h-\d+z)+$/);
  });

  it('es determinista y depende del texto', async () => {
    const a = await generarQr('VTA-0001');
    const b = await generarQr('VTA-0001');
    const c = await generarQr('VTA-0002');

    expect(a).toEqual(b);
    expect(c.ruta).not.toBe(a.ruta);
  });

  it('los tres cuadrados de búsqueda están en las esquinas (7 módulos oscuros seguidos en la primera fila)', async () => {
    const qr = await generarQr('X');
    // Primera fila del código = fila 2 por la zona de silencio; empieza con un tramo de 7 módulos desde la columna 2.
    expect(qr.ruta.startsWith('M2 2h7v1h-7z')).toBe(true);
  });
});
