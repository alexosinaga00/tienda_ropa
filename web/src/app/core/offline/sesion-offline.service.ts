import { Injectable, computed, inject } from '@angular/core';
import { AuthService, ROL_SUPERADMINISTRADOR } from '../auth.service';
import type { UsuarioYo } from '../models/seguridad.models';
import { AlmacenOfflineService } from './almacen-offline.service';
import { CLAVE_DISPOSITIVO, CLAVE_ULTIMA_EMPRESA, metaSucursalCaja } from './offline.config';
import type { AlcanceOffline } from './offline.models';
import type { RepositorioLocal } from './repositorio-local';

/** UUID v4: con `crypto.randomUUID` si existe; si no, con `getRandomValues`, y como último recurso con `Math.random`. */
export function generarUuid(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') {
    c.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function leerLocal(clave: string): string | null {
  try {
    return localStorage.getItem(clave);
  } catch {
    return null;
  }
}

function escribirLocal(clave: string, valor: string): void {
  try {
    localStorage.setItem(clave, valor);
  } catch {
    // Sin almacenamiento (modo privado, cuota): el modo sin conexión sigue funcionando sin recordar este dato.
  }
}

/**
 * Con quién se opera sin conexión: la empresa y el usuario de la sesión. El superadministrador (sin empresa) y quien no
 * ha iniciado sesión NO tienen alcance, así que no hay almacenamiento local para ellos.
 *
 * Además: el identificador estable del equipo, el perfil guardado para reabrir sin red y la limpieza al iniciar o
 * cerrar sesión (E14 4.3 y 4.10). `AuthService` lo obtiene de forma perezosa (`Injector`) para evitar la dependencia
 * circular entre ambos.
 */
@Injectable({ providedIn: 'root' })
export class SesionOfflineService {
  private readonly auth = inject(AuthService);
  private readonly almacen = inject(AlmacenOfflineService);
  private dispositivoEnMemoria: string | null = null;

  readonly alcance = computed<AlcanceOffline | null>(() => {
    const usuario = this.auth.usuario();
    const empresaId = this.auth.empresaId();
    if (usuario === null || empresaId === null || this.auth.esSuperadmin()) return null;
    return { empresaId, usuarioId: usuario.id };
  });

  /** El repositorio acotado a la sesión actual, o null si no hay alcance válido. */
  repositorio(): RepositorioLocal | null {
    const alcance = this.alcance();
    return alcance === null ? null : this.almacen.repositorio(alcance);
  }

  /** Identificador estable de este equipo (UUID en localStorage). Sin localStorage, uno en memoria mientras dure la pestaña. */
  dispositivoId(): string {
    const guardado = leerLocal(CLAVE_DISPOSITIVO);
    if (guardado) return guardado;
    const nuevo = this.dispositivoEnMemoria ?? generarUuid();
    this.dispositivoEnMemoria = nuevo;
    escribirLocal(CLAVE_DISPOSITIVO, nuevo);
    return nuevo;
  }

  /**
   * Al iniciar sesión (o recargar al usuario): guarda su perfil para reabrir sin red y, si la empresa es DISTINTA de la
   * última que usó este equipo, vacía el catálogo de la anterior (sus operaciones NO se tocan). El superadministrador
   * (sin empresa) no guarda nada. Si algo falla, la última empresa no se actualiza: el próximo intento lo repite.
   */
  async alIniciarSesion(usuario: UsuarioYo): Promise<void> {
    const empresaId = usuario.empresa_id;
    if (typeof empresaId !== 'number' || !Number.isInteger(empresaId)) return;
    if (usuario.roles.includes(ROL_SUPERADMINISTRADOR)) return;
    // El modo sin conexión es del personal: un comprador de la tienda no guarda su perfil ni puede vaciar el catálogo
    // de otra empresa en un equipo compartido.
    if (usuario.roles.length > 0 && usuario.roles.every((rol) => rol === 'cliente')) return;
    const alcance: AlcanceOffline = { empresaId, usuarioId: usuario.id };

    const anteriorTexto = leerLocal(CLAVE_ULTIMA_EMPRESA);
    const anterior = anteriorTexto ? Number(anteriorTexto) : null;
    if (anterior !== null && Number.isInteger(anterior) && anterior !== empresaId) {
      // Solo se necesita la empresa para vaciar el catálogo; el usuario es el actual (el repositorio exige uno válido).
      await this.almacen.repositorio({ empresaId: anterior, usuarioId: usuario.id }).vaciarReferencia();
    }

    await this.almacen.repositorio(alcance).guardarPerfil(usuario);
    escribirLocal(CLAVE_ULTIMA_EMPRESA, String(empresaId));
  }

  /**
   * Recuerda en qué sucursal cobra esta persona (se lee con conexión de `/empleados/yo`), para poder abrir Caja y vender si
   * la página se recarga sin red. Solo guarda el número de la sucursal: ningún dato personal. Sin alcance no guarda nada.
   */
  async guardarSucursalDeCaja(sucursalId: number): Promise<void> {
    const alcance = this.alcance();
    if (alcance === null || !Number.isInteger(sucursalId)) return;
    await this.almacen.repositorio(alcance).guardarMeta(metaSucursalCaja(alcance.usuarioId), sucursalId);
  }

  /** La sucursal de caja recordada para la sesión actual, o null si no hay (o no se puede leer). */
  async sucursalDeCajaGuardada(): Promise<number | null> {
    const alcance = this.alcance();
    if (alcance === null) return null;
    try {
      const valor = await this.almacen.repositorio(alcance).leerMeta<number>(metaSucursalCaja(alcance.usuarioId));
      return Number.isInteger(valor) ? (valor as number) : null;
    } catch {
      return null;
    }
  }

  /** El perfil guardado de ese usuario en esa empresa (para reabrir la app sin red), o undefined si no hay. */
  async perfilGuardado(empresaId: number, usuarioId: number): Promise<UsuarioYo | undefined> {
    return this.almacen.repositorio({ empresaId, usuarioId }).perfilGuardado<UsuarioYo>();
  }

  /**
   * Al cerrar sesión (D31): borra los clientes (datos personales) y el perfil guardado de ESTE usuario. Conserva el
   * catálogo, el stock y TODAS las operaciones. Debe llamarse ANTES de limpiar el usuario: el alcance sale de la sesión
   * y se toma de forma síncrona al invocarla.
   */
  async alCerrarSesion(): Promise<void> {
    const repositorio = this.repositorio();
    if (repositorio === null) return;
    await repositorio.vaciarClientes();
    await repositorio.borrarPerfil();
  }
}
