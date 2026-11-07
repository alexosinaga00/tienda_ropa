import { rutaDeAviso } from './push-rutas';

describe('rutaDeAviso', () => {
  it.each(['compra_confirmada', 'envio', 'pedido_diferido'])('%s abre la compra en la tienda', (tipo) => {
    expect(rutaDeAviso(tipo, 42, 'acme')).toBe('/t/acme/mis-compras/42');
    expect(rutaDeAviso(tipo, '42', 'acme')).toBe('/t/acme/mis-compras/42');
  });

  it('reserva_preparada abre las reservas del cliente', () => {
    expect(rutaDeAviso('reserva_preparada', 7, 'acme')).toBe('/t/acme/mis-reservas');
  });

  it('el personal va a su pantalla del back office', () => {
    expect(rutaDeAviso('reserva', 5, 'acme')).toBe('/reservas');
    expect(rutaDeAviso('sincronizacion', 5, null)).toBe('/sincronizacion');
  });

  it('sin tienda o sin id válido no inventa una ruta', () => {
    expect(rutaDeAviso('compra_confirmada', 42, null)).toBeNull();
    expect(rutaDeAviso('compra_confirmada', null, 'acme')).toBeNull();
    expect(rutaDeAviso('compra_confirmada', 'abc', 'acme')).toBeNull();
    expect(rutaDeAviso('reserva_preparada', null, undefined)).toBeNull();
  });

  it('un tipo desconocido no abre nada', () => {
    expect(rutaDeAviso('otro', 1, 'acme')).toBeNull();
    expect(rutaDeAviso(null, 1, 'acme')).toBeNull();
  });

  it('el código de tienda se codifica (no se cuela otra ruta)', () => {
    expect(rutaDeAviso('compra_confirmada', 1, 'a/b')).toBe('/t/a%2Fb/mis-compras/1');
  });
});
