import { NOMBRE_BASE_OFFLINE } from '../offline/offline.config';
import { EMPRESA, USUARIO, linea, nuevoEntorno, pedido } from './ayudas-prueba';
import { NOMBRE_BASE_CLIENTE } from './cliente-offline.config';
import { aCentavos, textoDinero, totalDeLineas } from './dinero';
import { RepositorioCliente } from './repositorio-cliente';

describe('almacén del cliente: IndexedDB separada', () => {
  it('usa una base distinta de la del personal', () => {
    expect(NOMBRE_BASE_CLIENTE).not.toBe(NOMBRE_BASE_OFFLINE);
  });
});

describe('dinero en centavos', () => {
  it('convierte a centavos y de vuelta sin errores de coma flotante', () => {
    expect(aCentavos('199.00')).toBe(19900);
    expect(aCentavos(0.1 + 0.2)).toBe(30);
    expect(aCentavos('abc')).toBe(0);
    expect(aCentavos(null)).toBe(0);
    expect(textoDinero(19900)).toBe('199.00');
    expect(textoDinero(5)).toBe('0.05');
    expect(textoDinero(12950)).toBe('129.50');
  });

  it('suma precio por cantidad', () => {
    expect(totalDeLineas([{ precio_unitario: '199.00', cantidad: 2 }, { precio_unitario: '10.50', cantidad: 3 }])).toBe(42950);
  });
});

describe('RepositorioCliente', () => {
  let entorno: ReturnType<typeof nuevoEntorno>;

  beforeEach(() => {
    entorno = nuevoEntorno();
  });

  afterEach(() => entorno.cerrar());

  it('exige empresa y usuario', () => {
    expect(() => new RepositorioCliente(entorno.base, { empresaId: NaN, usuarioId: 1 })).toThrow();
  });

  describe('carrito local', () => {
    it('guarda líneas con sus datos para mostrarlas y suma la misma variante hasta el máximo', async () => {
      const repo = entorno.repo();
      await repo.agregarLinea(linea(1, { cantidad: 2 }), 5);
      await repo.agregarLinea(linea(1, { cantidad: 2 }), 5);
      await repo.agregarLinea(linea(1, { cantidad: 2 }), 5);
      await repo.agregarLinea(linea(2), 5);

      const guardado = await repo.carrito();
      expect(guardado.map((l) => [l.variante_id, l.cantidad])).toEqual([[101, 5], [102, 2]]);
      expect(guardado[0]).toMatchObject({ producto_nombre: 'Polera 1', talla: 'M', color: 'Negro', precio_unitario: '199.00', sucursal_nombre: 'Centro' });
    });

    it('cambia la cantidad, y con 0 quita la línea', async () => {
      const repo = entorno.repo();
      await repo.agregarLinea(linea(1), 5);
      await repo.cambiarCantidad(101, 4);
      expect((await repo.carrito())[0].cantidad).toBe(4);
      await repo.cambiarCantidad(101, 0);
      expect(await repo.carrito()).toEqual([]);
    });

    it('no mezcla el carrito de otra empresa ni de otra persona', async () => {
      await entorno.repo().agregarLinea(linea(1), 5);
      await entorno.repo(2, USUARIO).agregarLinea(linea(2, { empresa_id: 2 }), 5);
      await entorno.repo(EMPRESA, 9).agregarLinea(linea(3, { usuario_id: 9 }), 5);

      expect((await entorno.repo().carrito()).map((l) => l.variante_id)).toEqual([101]);
      expect((await entorno.repo(2, USUARIO).carrito()).map((l) => l.variante_id)).toEqual([102]);
      await entorno.repo().vaciarCarrito();
      expect(await entorno.repo().carrito()).toEqual([]);
      expect(await entorno.repo(2, USUARIO).carrito()).toHaveLength(1);
    });

    it('rechaza guardar una línea que no es de la sesión', async () => {
      await expect(entorno.repo().agregarLinea(linea(1, { usuario_id: 99 }), 5)).rejects.toThrow();
    });
  });

  describe('pedidos', () => {
    it('registrar es idempotente por operacion_id y vacía el carrito en la misma transacción', async () => {
      const repo = entorno.repo();
      await repo.agregarLinea(linea(1), 5);

      await repo.registrarPedido(pedido(1), true);
      expect(await repo.carrito()).toEqual([]);

      await repo.agregarLinea(linea(2), 5);
      const otra = await repo.registrarPedido(pedido(1, { sucursal_nombre: 'Otra' }), true);
      expect(otra.sucursal_nombre).toBe('Centro');
      expect(await repo.pedidos()).toHaveLength(1);
      // El segundo intento (duplicado) no tocó el carrito.
      expect(await repo.carrito()).toHaveLength(1);
    });

    it('los pedidos son de cada persona y empresa', async () => {
      await entorno.repo().registrarPedido(pedido(1));
      await entorno.repo(EMPRESA, 9).registrarPedido(pedido(2, { usuario_id: 9 }));
      await entorno.repo(2, USUARIO).registrarPedido(pedido(3, { empresa_id: 2 }));

      expect((await entorno.repo().pedidos()).map((p) => p.operacion_id.slice(-1))).toEqual(['1']);
      expect(await entorno.repo().pedido(pedido(2).operacion_id)).toBeUndefined();
    });

    it('para enviar: pendientes y huérfanos, el más antiguo primero; un enviando reciente no entra', async () => {
      const repo = entorno.repo();
      const ahora = '2026-11-06T13:00:00.000Z';
      await repo.registrarPedido(pedido(3));
      await repo.registrarPedido(pedido(1));
      await repo.registrarPedido(pedido(2, { estado: 'enviando', ultimo_intento_en: '2026-11-06T12:59:30.000Z' }));
      await repo.registrarPedido(pedido(4, { estado: 'enviando', ultimo_intento_en: '2026-11-06T12:50:00.000Z' }));
      await repo.registrarPedido(pedido(5, { estado: 'cobrado' }));

      const lista = await repo.pedidosParaEnviar(ahora, 120_000);
      expect(lista.map((p) => p.operacion_id.slice(-1))).toEqual(['1', '3', '4']);
    });

    it('marcarEnviando suma un intento y no toca los resueltos', async () => {
      const repo = entorno.repo();
      await repo.registrarPedido(pedido(1));
      await repo.registrarPedido(pedido(2, { estado: 'cobrado' }));

      expect(await repo.marcarEnviando(pedido(1).operacion_id, '2026-11-06T13:00:00.000Z')).toBe(true);
      expect(await repo.marcarEnviando(pedido(2).operacion_id, '2026-11-06T13:00:00.000Z')).toBe(false);
      const uno = await repo.pedido(pedido(1).operacion_id);
      expect(uno).toMatchObject({ estado: 'enviando', intentos: 1, ultimo_intento_en: '2026-11-06T13:00:00.000Z' });
    });

    it('cobrado y rechazado son finales: no cambian de estado; los demás campos no permitidos se ignoran', async () => {
      const repo = entorno.repo();
      await repo.registrarPedido(pedido(1, { estado: 'cobrado' }));

      await expect(repo.actualizarPedido(pedido(1).operacion_id, { estado: 'pendiente' })).rejects.toThrow(/ya no puede cambiar/);
      await repo.actualizarPedido(pedido(1).operacion_id, { visto: true, total_maximo: '1.00' } as never);
      const guardado = await repo.pedido(pedido(1).operacion_id);
      expect(guardado?.visto).toBe(true);
      expect(guardado?.total_maximo).toBe('398.00');
    });

    it('solo se descarta un pedido pendiente', async () => {
      const repo = entorno.repo();
      await repo.registrarPedido(pedido(1));
      await repo.registrarPedido(pedido(2, { estado: 'enviando' }));
      await repo.registrarPedido(pedido(3, { estado: 'cobrado' }));

      expect(await repo.descartarPedido(pedido(2).operacion_id)).toBe(false);
      expect(await repo.descartarPedido(pedido(3).operacion_id)).toBe(false);
      expect(await repo.descartarPedido(pedido(1).operacion_id)).toBe(true);
      expect(await repo.descartarPedido('no-existe')).toBe(false);
      expect(await repo.pedidos()).toHaveLength(2);
    });

    it('al cerrar sesión borra carrito, datos recordados y resueltos, pero CONSERVA los pedidos sin cobrar', async () => {
      const repo = entorno.repo();
      await repo.guardarMeta('metodo_pago', { guardado: true });
      await repo.agregarLinea(linea(1), 5);
      await repo.registrarPedido(pedido(1));
      await repo.registrarPedido(pedido(2, { estado: 'enviando' }));
      await repo.registrarPedido(pedido(3, { estado: 'cobrado' }));
      await repo.registrarPedido(pedido(4, { estado: 'rechazado' }));
      // Los de otra persona no se tocan.
      await entorno.repo(EMPRESA, 9).guardarMeta('metodo_pago', { guardado: false });

      await repo.vaciarAlCerrarSesion();

      expect(await repo.leerMeta('metodo_pago')).toBeUndefined();
      expect(await repo.carrito()).toEqual([]);
      expect((await repo.pedidos()).map((p) => p.estado).sort()).toEqual(['enviando', 'pendiente']);
      expect(await entorno.repo(EMPRESA, 9).leerMeta('metodo_pago')).toEqual({ guardado: false });
    });

    it('un pedido vencido se puede descartar, nunca vuelve a pendiente y no sale para enviar', async () => {
      const repo = entorno.repo();
      await repo.registrarPedido(pedido(1, { estado: 'vencido' }));
      await repo.registrarPedido(pedido(2, { estado: 'vencido' }));

      expect(await repo.pedidosParaEnviar('2026-11-06T13:00:00.000Z', 120_000)).toEqual([]);
      await expect(repo.actualizarPedido(pedido(1).operacion_id, { estado: 'pendiente' })).rejects.toThrow(/ya no puede cambiar/);
      expect(await repo.descartarPedido(pedido(1).operacion_id)).toBe(true);
      expect((await repo.pedidos()).map((p) => p.operacion_id)).toEqual([pedido(2).operacion_id]);
    });

    it('al cerrar sesión los vencidos se borran como cualquier resuelto', async () => {
      const repo = entorno.repo();
      await repo.registrarPedido(pedido(1, { estado: 'vencido' }));
      await repo.registrarPedido(pedido(2));

      await repo.vaciarAlCerrarSesion();

      expect((await repo.pedidos()).map((p) => p.estado)).toEqual(['pendiente']);
    });

    it('borrarTodo ("Borrarlos y salir") quita incluso los sin enviar, pero solo de esta persona', async () => {
      const repo = entorno.repo();
      await repo.guardarMeta('perfil', { x: 1 });
      await repo.agregarLinea(linea(1), 5);
      await repo.registrarPedido(pedido(1));
      await repo.registrarPedido(pedido(2, { estado: 'enviando' }));
      await entorno.repo(EMPRESA, 9).registrarPedido(pedido(3, { usuario_id: 9 }));

      await repo.borrarTodo();

      expect(await repo.pedidos()).toEqual([]);
      expect(await repo.carrito()).toEqual([]);
      expect(await repo.leerMeta('perfil')).toBeUndefined();
      expect(await entorno.repo(EMPRESA, 9).pedidos()).toHaveLength(1);
    });

    it('marcarVistos marca solo los resueltos', async () => {
      const repo = entorno.repo();
      await repo.registrarPedido(pedido(1));
      await repo.registrarPedido(pedido(2, { estado: 'cobrado' }));

      await repo.marcarVistos();

      expect((await repo.pedido(pedido(1).operacion_id))?.visto).toBe(false);
      expect((await repo.pedido(pedido(2).operacion_id))?.visto).toBe(true);
    });
  });
});
