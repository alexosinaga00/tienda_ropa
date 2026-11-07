/**
 * Ayudas SOLO para las pruebas del modo sin conexión del cliente (nada de la app las importa): una base IndexedDB falsa
 * y nueva por prueba, un alcance que se puede cambiar, y una conectividad de mentira.
 */
import { computed, signal } from '@angular/core';
import Dexie from 'dexie';
import { Subject } from 'rxjs';
import type { EstadoConexion } from '../conectividad.service';
import type { AlcanceCliente, LineaCarritoLocal, PedidoSinConexion } from './cliente-offline.models';
import { BaseCliente } from './db-cliente-offline';
import { RepositorioCliente } from './repositorio-cliente';

let contador = 0;

export const EMPRESA = 1;
export const USUARIO = 5;

export function nuevoEntorno() {
  const nombre = `cliente_prueba_${++contador}_${Math.random().toString(36).slice(2)}`;
  const base = new BaseCliente(nombre);
  const alcance = signal<AlcanceCliente | null>({ empresaId: EMPRESA, usuarioId: USUARIO });
  const enLinea = signal(true);
  const volvio = new Subject<void>();

  /** Lo que el resto de la app lee de `ClienteOfflineService`. */
  const cliente = {
    alcance,
    repositorio: () => (alcance() === null ? null : new RepositorioCliente(base, alcance()!)),
  };
  /** Lo que el resto de la app lee de `ConectividadService`. */
  const conectividad = {
    enLinea,
    estado: computed<EstadoConexion>(() => (enLinea() ? 'en_linea' : 'sin_conexion')),
    volvioConexion$: volvio.asObservable(),
  };

  return {
    base,
    alcance,
    enLinea,
    volvio,
    cliente,
    conectividad,
    /** El repositorio de cualquier persona de cualquier empresa (para sembrar y para mirar). */
    repo: (empresaId = EMPRESA, usuarioId = USUARIO) => new RepositorioCliente(base, { empresaId, usuarioId }),
    async cerrar(): Promise<void> {
      base.close();
      await Dexie.delete(nombre);
    },
  };
}

export function linea(n: number, extra: Partial<LineaCarritoLocal> = {}): LineaCarritoLocal {
  return {
    empresa_id: EMPRESA,
    usuario_id: USUARIO,
    variante_id: 100 + n,
    producto_id: 10 + n,
    cantidad: 2,
    producto_nombre: `Polera ${n}`,
    talla: 'M',
    color: 'Negro',
    precio_unitario: '199.00',
    imagen: null,
    sucursal_id: 3,
    sucursal_nombre: 'Centro',
    agregado_en: new Date(Date.UTC(2026, 10, 6, 12, 0, n)).toISOString(),
    ...extra,
  };
}

export function pedido(n: number, extra: Partial<PedidoSinConexion> = {}): PedidoSinConexion {
  // Creado hace una hora (y los siguientes, un minuto después): nunca vencido, sea cual sea el día en que corra la prueba.
  const creado = new Date(Date.now() - 3_600_000 + n * 60_000).toISOString();
  return {
    empresa_id: EMPRESA,
    usuario_id: USUARIO,
    operacion_id: `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`,
    estado: 'pendiente',
    sucursal_id: 3,
    sucursal_nombre: 'Centro',
    costo_envio: '0.00',
    lineas: [
      {
        variante_id: 100 + n,
        cantidad: 2,
        producto_nombre: `Polera ${n}`,
        talla: 'M',
        color: 'Negro',
        precio_unitario: '199.00',
        imagen: null,
      },
    ],
    total_maximo: '398.00',
    fecha_pedido: creado,
    creado_en: creado,
    intentos: 0,
    ultimo_intento_en: null,
    proximo_intento_en: null,
    ultimo_error: null,
    motivo: null,
    mensaje: null,
    venta_id: null,
    codigo_venta: null,
    total: null,
    total_usd: null,
    resuelto_en: null,
    visto: false,
    ...extra,
  };
}
