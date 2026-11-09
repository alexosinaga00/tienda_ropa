import { TestBed } from '@angular/core/testing';
import { AvisosMostradosService, claveDeAviso, claveDeVenta } from './avisos-mostrados.service';

describe('AvisosMostradosService', () => {
  let avisos: AvisosMostradosService;

  beforeEach(() => {
    avisos = TestBed.inject(AvisosMostradosService);
  });

  it('el primer aviso de un hecho se muestra y los siguientes no', () => {
    expect(avisos.registrar(claveDeVenta(42))).toBe(true);
    expect(avisos.registrar(claveDeVenta(42))).toBe(false);
    expect(avisos.registrar(claveDeVenta(43))).toBe(true);
    expect(avisos.yaAvisado('venta:42')).toBe(true);
    expect(avisos.yaAvisado('venta:99')).toBe(false);
  });

  it('compra_confirmada y pedido_diferido de la misma venta tienen la MISMA clave', () => {
    expect(claveDeAviso('compra_confirmada', 42, 7)).toBe('venta:42');
    expect(claveDeAviso('pedido_diferido', 42, 8)).toBe('venta:42');
    expect(claveDeAviso('compra_confirmada', 43, 9)).toBe('venta:43');
  });

  it('los demás tipos se reconocen por su notificación', () => {
    expect(claveDeAviso('envio', 42, 11)).toBe('notif:11');
    expect(claveDeAviso('envio', 42, 12)).toBe('notif:12');
    expect(claveDeAviso('reserva', 5, 3)).toBe('notif:3');
    // El reembolso NO se junta con la compra de la misma venta: es otro hecho.
    expect(claveDeAviso('reembolso', 42, 13)).toBe('notif:13');
  });

  it('sin forma de reconocerlo (sin ids) siempre se muestra', () => {
    expect(claveDeAviso('otro', null, null)).toBeNull();
    expect(avisos.registrar(null)).toBe(true);
    expect(avisos.registrar(null)).toBe(true);
  });

  it('al cambiar de sesión se vacía', () => {
    avisos.registrar(claveDeVenta(42));
    avisos.limpiar();
    expect(avisos.registrar(claveDeVenta(42))).toBe(true);
  });

  it('no crece sin límite: olvida lo más viejo', () => {
    for (let i = 0; i < 250; i++) avisos.registrar(`notif:${i}`);
    expect(avisos.yaAvisado('notif:0')).toBe(false);
    expect(avisos.yaAvisado('notif:249')).toBe(true);
  });
});
