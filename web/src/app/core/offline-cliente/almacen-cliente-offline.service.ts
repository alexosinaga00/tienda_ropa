import { Injectable } from '@angular/core';
import type { AlcanceCliente } from './cliente-offline.models';
import { BaseCliente } from './db-cliente-offline';
import { RepositorioCliente } from './repositorio-cliente';

/**
 * Dueño de la única conexión a la IndexedDB del cliente. Entrega repositorios YA acotados a una empresa y un usuario.
 * En las pruebas se reemplaza `base` por otra con `fake-indexeddb`.
 */
@Injectable({ providedIn: 'root' })
export class AlmacenClienteOfflineService {
  readonly base = new BaseCliente();

  repositorio(alcance: AlcanceCliente): RepositorioCliente {
    return new RepositorioCliente(this.base, alcance);
  }
}
