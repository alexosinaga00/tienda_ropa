import { Injectable, computed, inject } from '@angular/core';
import { AuthService } from '../auth.service';
import type { UsuarioYo } from '../models/seguridad.models';
import { AlmacenClienteOfflineService } from './almacen-cliente-offline.service';
import { META_PERFIL_CLIENTE } from './cliente-offline.config';
import type { AlcanceCliente } from './cliente-offline.models';
import type { RepositorioCliente } from './repositorio-cliente';

/**
 * Con quién se opera sin conexión en la tienda: la empresa y la persona de la sesión, SOLO si es un comprador (su único
 * rol es "cliente"). El personal y el superadministrador no tienen alcance aquí: usan el almacén del personal.
 *
 * También guarda el perfil del comprador para reabrir la tienda sin red y limpia lo suyo al cerrar sesión.
 * `AuthService` lo obtiene de forma perezosa (`Injector`) para evitar la dependencia circular entre ambos.
 */
@Injectable({ providedIn: 'root' })
export class ClienteOfflineService {
  private readonly auth = inject(AuthService);
  private readonly almacen = inject(AlmacenClienteOfflineService);

  readonly alcance = computed<AlcanceCliente | null>(() => {
    const usuario = this.auth.usuario();
    const empresaId = this.auth.empresaId();
    if (usuario === null || empresaId === null || !this.auth.esSoloCliente()) return null;
    return { empresaId, usuarioId: usuario.id };
  });

  /** El repositorio acotado a la sesión actual, o null si no hay un comprador con sesión. */
  repositorio(): RepositorioCliente | null {
    const alcance = this.alcance();
    return alcance === null ? null : this.almacen.repositorio(alcance);
  }

  /** Al cargar al comprador: guarda su perfil para reabrir sin red. */
  async alIniciarSesion(usuario: UsuarioYo): Promise<void> {
    const empresaId = usuario.empresa_id;
    if (typeof empresaId !== 'number' || !Number.isInteger(empresaId)) return;
    await this.almacen.repositorio({ empresaId, usuarioId: usuario.id }).guardarMeta(META_PERFIL_CLIENTE, usuario);
  }

  /** El perfil guardado de ese comprador en esa empresa (para reabrir sin red), o undefined. */
  async perfilGuardado(empresaId: number, usuarioId: number): Promise<UsuarioYo | undefined> {
    return this.almacen.repositorio({ empresaId, usuarioId }).leerMeta<UsuarioYo>(META_PERFIL_CLIENTE);
  }

  /**
   * Al cerrar sesión: borra todo lo del comprador menos los pedidos aún sin cobrar. Recibe el alcance que tenía la
   * sesión al salir (para cuando ya se limpió el usuario); sin él, usa el de la sesión actual.
   */
  async alCerrarSesion(alcance: AlcanceCliente | null = this.alcance()): Promise<void> {
    if (alcance === null) return;
    await this.almacen.repositorio(alcance).vaciarAlCerrarSesion();
  }
}
