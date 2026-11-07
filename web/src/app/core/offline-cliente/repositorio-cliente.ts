import Dexie from 'dexie';
import type { BaseCliente } from './db-cliente-offline';
import type {
  AlcanceCliente,
  CambiosPedido,
  EstadoPedidoLocal,
  LineaCarritoLocal,
  PedidoSinConexion,
} from './cliente-offline.models';

const CAMBIOS_PERMITIDOS: (keyof CambiosPedido)[] = [
  'estado',
  'intentos',
  'ultimo_intento_en',
  'proximo_intento_en',
  'ultimo_error',
  'motivo',
  'mensaje',
  'venta_id',
  'codigo_venta',
  'total',
  'total_usd',
  'resuelto_en',
  'visto',
];

const ESTADOS_FINALES: EstadoPedidoLocal[] = ['cobrado', 'rechazado', 'vencido'];

/**
 * La ÚNICA clase que toca las tablas del cliente. Se construye con un alcance obligatorio (empresa y usuario) y todas
 * sus consultas lo aplican: ni un componente ni un servicio recibe una tabla.
 *
 * Un pedido en cola solo se puede quitar con `descartarPedido` (y únicamente si todavía no salió): nada lo borra
 * por intentar enviarlo.
 */
export class RepositorioCliente {
  constructor(
    private readonly db: BaseCliente,
    readonly alcance: AlcanceCliente,
  ) {
    if (!Number.isInteger(alcance?.empresaId) || !Number.isInteger(alcance?.usuarioId)) {
      throw new Error('No se puede usar el almacenamiento local sin empresa y usuario.');
    }
  }

  private get e(): number {
    return this.alcance.empresaId;
  }

  private get u(): number {
    return this.alcance.usuarioId;
  }

  // ---- Meta ----------------------------------------------------------------------------------------------------------------

  async leerMeta<T = unknown>(clave: string): Promise<T | undefined> {
    const fila = await this.db.meta.get([this.e, this.u, clave]);
    return fila?.valor as T | undefined;
  }

  async guardarMeta(clave: string, valor: unknown): Promise<void> {
    await this.db.meta.put({ empresa_id: this.e, usuario_id: this.u, clave, valor });
  }

  async borrarMeta(clave: string): Promise<void> {
    await this.db.meta.delete([this.e, this.u, clave]);
  }

  // ---- Carrito local -------------------------------------------------------------------------------------------------------

  /** Las líneas de MI carrito local, de la más vieja a la más nueva. */
  async carrito(): Promise<LineaCarritoLocal[]> {
    const filas = await this.db.carrito
      .where('[empresa_id+usuario_id+variante_id]')
      .between([this.e, this.u], [this.e, this.u, Dexie.maxKey], true, true)
      .toArray();
    return filas.sort((a, b) => a.agregado_en.localeCompare(b.agregado_en));
  }

  /** Agrega la línea; si la variante ya estaba, suma las cantidades (hasta `maximo`). Una sola transacción. */
  async agregarLinea(linea: LineaCarritoLocal, maximo: number): Promise<LineaCarritoLocal> {
    this.exigirMio(linea);
    return this.db.transaction('rw', this.db.carrito, async () => {
      const clave: [number, number, number] = [this.e, this.u, linea.variante_id];
      const existente = await this.db.carrito.get(clave);
      const nueva = existente
        ? { ...existente, ...linea, cantidad: Math.min(existente.cantidad + linea.cantidad, maximo), agregado_en: existente.agregado_en }
        : { ...linea, cantidad: Math.min(linea.cantidad, maximo) };
      await this.db.carrito.put(nueva);
      return nueva;
    });
  }

  /** Cambia la cantidad de una línea; con 0 o menos la quita. */
  async cambiarCantidad(varianteId: number, cantidad: number): Promise<void> {
    if (cantidad <= 0) {
      await this.quitarLinea(varianteId);
      return;
    }
    await this.db.carrito.update([this.e, this.u, varianteId], { cantidad });
  }

  async quitarLinea(varianteId: number): Promise<void> {
    await this.db.carrito.delete([this.e, this.u, varianteId]);
  }

  async vaciarCarrito(): Promise<void> {
    await this.db.carrito
      .where('[empresa_id+usuario_id+variante_id]')
      .between([this.e, this.u], [this.e, this.u, Dexie.maxKey], true, true)
      .delete();
  }

  // ---- Pedidos sin conexión ------------------------------------------------------------------------------------------------

  private pedidosDeMiUsuario(): Promise<PedidoSinConexion[]> {
    return this.db.pedidos
      .where('[empresa_id+usuario_id+creado_en]')
      .between([this.e, this.u], [this.e, this.u, Dexie.maxKey], true, true)
      .toArray();
  }

  /**
   * Guarda un pedido NUEVO. Si ya existe uno con la misma `operacion_id` (doble clic), devuelve el que ya estaba y NO
   * crea otro. Opcionalmente vacía el carrito local en la MISMA transacción: o queda el pedido y se vacía, o nada.
   */
  async registrarPedido(pedido: PedidoSinConexion, vaciarCarrito = false): Promise<PedidoSinConexion> {
    this.exigirMio(pedido);
    return this.db.transaction('rw', [this.db.pedidos, this.db.carrito], async () => {
      const existente = await this.db.pedidos.get([this.e, this.u, pedido.operacion_id]);
      if (existente) return existente;
      await this.db.pedidos.add(pedido);
      if (vaciarCarrito) await this.vaciarCarrito();
      return pedido;
    });
  }

  async pedido(operacionId: string): Promise<PedidoSinConexion | undefined> {
    return this.db.pedidos.get([this.e, this.u, operacionId]);
  }

  /** Mis pedidos, del más nuevo al más viejo. */
  async pedidos(): Promise<PedidoSinConexion[]> {
    return (await this.pedidosDeMiUsuario()).sort((a, b) => b.creado_en.localeCompare(a.creado_en));
  }

  /**
   * Lo que falta por enviar, el más antiguo primero: los `pendiente` y los `enviando` que llevan más de `huerfanoMs`
   * (un cierre brusco los dejó a medias; reenviarlos es seguro porque el servidor es idempotente). Un `enviando`
   * reciente NO entra: lo está enviando otra pestaña.
   */
  async pedidosParaEnviar(ahora: string, huerfanoMs: number): Promise<PedidoSinConexion[]> {
    const t = Date.parse(ahora);
    return (await this.pedidosDeMiUsuario())
      .filter((p) => {
        if (p.estado === 'pendiente') return true;
        if (p.estado === 'enviando') return !p.ultimo_intento_en || t - Date.parse(p.ultimo_intento_en) > huerfanoMs;
        return false;
      })
      .sort((a, b) => a.creado_en.localeCompare(b.creado_en));
  }

  /** Antes de enviar: pasa el pedido a `enviando`, suma un intento y anota la hora. Devuelve false si ya no se puede enviar. */
  async marcarEnviando(operacionId: string, ahora: string): Promise<boolean> {
    return this.db.transaction('rw', this.db.pedidos, async () => {
      const actual = await this.pedido(operacionId);
      if (!actual || (actual.estado !== 'pendiente' && actual.estado !== 'enviando')) return false;
      await this.db.pedidos.update([this.e, this.u, operacionId], {
        estado: 'enviando',
        intentos: actual.intentos + 1,
        ultimo_intento_en: ahora,
      });
      return true;
    });
  }

  /**
   * Cambia SOLO los campos permitidos de un pedido mío. `cobrado` y `rechazado` son finales: cambiarles el estado es un
   * error (la misma respuesta repetida no cambia nada). Ningún camino lo borra.
   */
  async actualizarPedido(operacionId: string, cambios: CambiosPedido): Promise<PedidoSinConexion> {
    const limpios: Record<string, unknown> = {};
    for (const clave of CAMBIOS_PERMITIDOS) {
      if (clave in cambios) limpios[clave] = cambios[clave];
    }
    const cambiosLimpios = limpios as CambiosPedido;
    return this.db.transaction('rw', this.db.pedidos, async () => {
      const actual = await this.pedido(operacionId);
      if (!actual) throw new Error('No existe ese pedido en este equipo.');
      const nuevo = limpios['estado'] as EstadoPedidoLocal | undefined;
      if (nuevo && nuevo !== actual.estado && ESTADOS_FINALES.includes(actual.estado)) {
        throw new Error(`Un pedido ${actual.estado} ya no puede cambiar de estado.`);
      }
      await this.db.pedidos.update([this.e, this.u, operacionId], cambiosLimpios);
      return { ...actual, ...cambiosLimpios } as PedidoSinConexion;
    });
  }

  /** Quita un pedido que todavía no salió (`pendiente`) o que venció. Devuelve false si no existe o ya está enviándose o cobrado/rechazado. */
  async descartarPedido(operacionId: string): Promise<boolean> {
    return this.db.transaction('rw', this.db.pedidos, async () => {
      const actual = await this.pedido(operacionId);
      if (!actual || (actual.estado !== 'pendiente' && actual.estado !== 'vencido')) return false;
      await this.db.pedidos.delete([this.e, this.u, operacionId]);
      return true;
    });
  }

  /** Marca como vistos los pedidos ya resueltos (cobrados o rechazados). */
  async marcarVistos(): Promise<void> {
    await this.db.transaction('rw', this.db.pedidos, async () => {
      for (const p of await this.pedidosDeMiUsuario()) {
        if (ESTADOS_FINALES.includes(p.estado) && !p.visto) {
          await this.db.pedidos.update([this.e, this.u, p.operacion_id], { visto: true });
        }
      }
    });
  }

  // ---- Cerrar sesión -------------------------------------------------------------------------------------------------------

  /**
   * Al cerrar sesión borra el carrito local, el perfil y todo lo recordado (método de pago, sucursales) y los pedidos ya
   * resueltos. Los pedidos que todavía NO se cobraron (`pendiente` y `enviando`) se CONSERVAN: son compras que el cliente
   * ya aceptó y no se pueden perder; no llevan datos personales y solo se ven y se envían al volver a entrar él mismo.
   */
  async vaciarAlCerrarSesion(): Promise<void> {
    await this.db.transaction('rw', [this.db.meta, this.db.carrito, this.db.pedidos], async () => {
      await this.db.meta
        .where('[empresa_id+usuario_id+clave]')
        .between([this.e, this.u], [this.e, this.u, Dexie.maxKey], true, true)
        .delete();
      await this.vaciarCarrito();
      for (const p of await this.pedidosDeMiUsuario()) {
        if (ESTADOS_FINALES.includes(p.estado)) await this.db.pedidos.delete([this.e, this.u, p.operacion_id]);
      }
    });
  }

  /**
   * "Borrarlos y salir": quita TODO lo de esta persona en este equipo (también los pedidos sin enviar). Es lo único que
   * borra pedidos sin cobrar, y solo se llama porque el cliente lo eligió.
   */
  async borrarTodo(): Promise<void> {
    await this.db.transaction('rw', [this.db.meta, this.db.carrito, this.db.pedidos], async () => {
      await this.db.meta
        .where('[empresa_id+usuario_id+clave]')
        .between([this.e, this.u], [this.e, this.u, Dexie.maxKey], true, true)
        .delete();
      await this.vaciarCarrito();
      await this.db.pedidos
        .where('[empresa_id+usuario_id+creado_en]')
        .between([this.e, this.u], [this.e, this.u, Dexie.maxKey], true, true)
        .delete();
    });
  }

  private exigirMio(fila: { empresa_id: number; usuario_id: number }): void {
    if (fila.empresa_id !== this.e || fila.usuario_id !== this.u) {
      throw new Error('El dato no corresponde a la empresa y el usuario de esta sesión.');
    }
  }
}
