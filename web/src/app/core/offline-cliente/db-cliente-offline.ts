import Dexie, { type Table } from 'dexie';
import { NOMBRE_BASE_CLIENTE } from './cliente-offline.config';
import type { FilaMetaCliente, LineaCarritoLocal, PedidoSinConexion } from './cliente-offline.models';

/**
 * La base IndexedDB del cliente de la tienda. Distinta de la del personal. TODA fila lleva `empresa_id` y `usuario_id`
 * y todas las claves empiezan por ellos. Solo `RepositorioCliente` usa esta clase.
 *
 * Para cambiar el esquema: agregar `this.version(2).stores({...})` DEBAJO de la versión 1 (nunca editarla).
 */
export class BaseCliente extends Dexie {
  meta!: Table<FilaMetaCliente, [number, number, string]>;
  carrito!: Table<LineaCarritoLocal, [number, number, number]>;
  pedidos!: Table<PedidoSinConexion, [number, number, string]>;

  constructor(nombre: string = NOMBRE_BASE_CLIENTE) {
    super(nombre);
    this.version(1).stores({
      meta: '[empresa_id+usuario_id+clave]',
      carrito: '[empresa_id+usuario_id+variante_id]',
      pedidos: '[empresa_id+usuario_id+operacion_id], [empresa_id+usuario_id+creado_en]',
    });
  }
}
