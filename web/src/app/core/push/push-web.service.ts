import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { MessageService } from 'primeng/api';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AvisosMostradosService, TIPOS_DE_VENTA, claveDeAviso } from '../avisos-mostrados.service';
import { SIN_TOAST_ERROR } from '../http-contexts';
import { NotificacionesService } from '../notificaciones.service';
import { MENSAJERIA_PUSH, MensajePush, MensajeriaPush } from './firebase-mensajeria';
import { CLAVE_TOAST_AVISO, CLAVE_TOKEN_PUSH_WEB, leerTokenPushGuardado, pedirBajaDelToken } from './push-comun';
import { rutaDeAviso } from './push-rutas';

export { CLAVE_TOAST_AVISO, CLAVE_TOKEN_PUSH_WEB };

export type EstadoAvisosPush =
  /** El navegador no puede recibir push (o es un iPhone con la web sin instalar). */
  | 'no_soportado'
  /** Los avisos exigen una conexión segura (https; localhost vale). */
  | 'sin_https'
  /** La persona bloqueó los avisos en el navegador: solo ella puede desbloquearlos. */
  | 'bloqueado'
  | 'inactivo'
  | 'activando'
  | 'activo';

const MENSAJE_SIN_SOPORTE = 'Este navegador no puede recibir avisos.';
const MENSAJE_IPHONE =
  ' En iPhone solo funcionan con la web instalada en la pantalla de inicio (iOS 16.4 o más).';
const MENSAJE_SIN_HTTPS = 'Los avisos solo funcionan en una conexión segura (https).';
const MENSAJE_BLOQUEADO =
  'Bloqueaste los avisos de este sitio. Permítelos desde el candado junto a la dirección y vuelve a intentarlo.';

const leerToken = leerTokenPushGuardado;

function guardarToken(token: string): void {
  try {
    localStorage.setItem(CLAVE_TOKEN_PUSH_WEB, token);
  } catch {
    // Sin almacenamiento el aviso funciona igual; solo no se recuerda entre visitas.
  }
}

function borrarTokenGuardado(): void {
  try {
    localStorage.removeItem(CLAVE_TOKEN_PUSH_WEB);
  } catch {
    // Nada que borrar.
  }
}

function esIphone(): boolean {
  return typeof navigator !== 'undefined' && /iPhone|iPad|iPod/i.test(navigator.userAgent);
}

/** Lo que el navegador sabe hacer ahora mismo (se lee cada vez: el permiso puede cambiar mientras la página está abierta). */
function estadoDelNavegador(): EstadoAvisosPush {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return 'no_soportado';
  if (window.isSecureContext === false) return 'sin_https';
  if (!('Notification' in window) || !('serviceWorker' in navigator) || !('PushManager' in window)) return 'no_soportado';
  if (Notification.permission === 'denied') return 'bloqueado';
  return leerToken() !== null && Notification.permission === 'granted' ? 'activo' : 'inactivo';
}

/**
 * Avisos push en este navegador (Firebase Cloud Messaging), SIEMPRE por decisión de la persona.
 *
 * - El permiso del navegador solo se pide en `activar()`, que llama el botón "Activar avisos". Nada se pide al cargar.
 * - El token se manda a `POST /dispositivos-push` (`plataforma: "web"`); `sincronizarSiActivo()` lo reenvía si Firebase lo
 *   cambió, y `darDeBajaAlSalir()` lo da de baja al cerrar sesión (mejor esfuerzo).
 * - Firebase se carga con `import()` solo cuando hace falta: el paquete inicial no crece.
 * - Convivencia con el Service Worker de Angular (ngsw, alcance `/`): el de Firebase se registra con su propio alcance
 *   (`/firebase-cloud-messaging-push-scope`) y se le pasa a `getToken`.
 * - Con la pestaña abierta (`onMessage`) el navegador no muestra nada solo: aquí sale un aviso con botón "Ver", salvo que
 *   el mismo hecho ya se le haya avisado (`AvisosMostradosService`) o la persona esté viendo esa compra.
 */
@Injectable({ providedIn: 'root' })
export class PushWebService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly cargarMensajeria = inject(MENSAJERIA_PUSH);
  private readonly avisos = inject(AvisosMostradosService);
  private readonly notificaciones = inject(NotificacionesService);
  private readonly mensajes = inject(MessageService, { optional: true });

  readonly estado = signal<EstadoAvisosPush>(estadoDelNavegador());
  /** Qué decirle a la persona cuando algo no se pudo (o por qué no está disponible). */
  readonly mensaje = signal<string | null>(this.mensajeDe(this.estado()));

  private dejarDeEscuchar: (() => void) | null = null;
  private sincronizando: Promise<void> | null = null;

  private mensajeDe(estado: EstadoAvisosPush): string | null {
    switch (estado) {
      case 'no_soportado':
        return MENSAJE_SIN_SOPORTE + (esIphone() ? MENSAJE_IPHONE : '');
      case 'sin_https':
        return MENSAJE_SIN_HTTPS;
      case 'bloqueado':
        return MENSAJE_BLOQUEADO;
      default:
        return null;
    }
  }

  private fijar(estado: EstadoAvisosPush, mensaje: string | null = this.mensajeDe(estado)): void {
    this.estado.set(estado);
    this.mensaje.set(mensaje);
  }

  // ---- Activar y desactivar (los botones de la tarjeta) ----------------------------------------------------------

  /** "Activar avisos": pide el permiso (la primera vez), obtiene el token y lo registra en el servidor. */
  async activar(): Promise<boolean> {
    const actual = this.estado();
    if (actual === 'activo') return true;
    if (actual === 'activando' || actual === 'no_soportado' || actual === 'sin_https') return false;

    this.fijar('activando');
    try {
      const mensajeria = await this.cargarMensajeria();
      if (!(await mensajeria.soportado())) {
        this.fijar('no_soportado');
        return false;
      }
      let permiso = Notification.permission;
      if (permiso === 'default') permiso = await Notification.requestPermission();
      if (permiso === 'denied') {
        this.fijar('bloqueado');
        return false;
      }
      if (permiso !== 'granted') {
        this.fijar('inactivo', 'No diste el permiso del navegador, así que los avisos siguen apagados.');
        return false;
      }

      const registro = await mensajeria.registrarServiceWorker();
      const token = await mensajeria.obtenerToken(registro);
      await this.enviarToken(token);
      guardarToken(token);
      this.fijar('activo');
      await this.escuchar(mensajeria);
      return true;
    } catch {
      this.fijar('inactivo', 'No pudimos activar los avisos. Inténtalo de nuevo.');
      return false;
    }
  }

  /** "Desactivar": da de baja el token en el servidor y en Firebase. Si el servidor no responde, sigue activo. */
  async desactivar(): Promise<boolean> {
    const token = leerToken();
    try {
      if (token !== null) await this.darDeBajaEnServidor(token);
    } catch {
      this.mensaje.set('No pudimos desactivar los avisos. Inténtalo de nuevo.');
      return false;
    }
    this.limpiarLocal();
    await this.borrarTokenEnFirebase();
    this.fijar(estadoDelNavegador() === 'bloqueado' ? 'bloqueado' : 'inactivo');
    return true;
  }

  // ---- Mantenimiento (sin pedir permiso jamás) --------------------------------------------------------------------

  /**
   * Si los avisos ya estaban activados: vuelve a leer el token (Firebase puede cambiarlo), lo reenvía si cambió y deja
   * escuchando los avisos con la pestaña abierta. NUNCA pide permiso. Nunca lanza.
   */
  sincronizarSiActivo(): Promise<void> {
    this.sincronizando ??= this.sincronizar().finally(() => (this.sincronizando = null));
    return this.sincronizando;
  }

  private async sincronizar(): Promise<void> {
    const guardado = leerToken();
    const del = estadoDelNavegador();
    if (guardado === null) return;
    if (del !== 'activo') {
      // Quitaron el permiso desde el navegador: el token guardado ya no sirve de nada.
      this.limpiarLocal();
      this.fijar(del);
      return;
    }
    try {
      const mensajeria = await this.cargarMensajeria();
      if (!(await mensajeria.soportado())) return;
      const registro = await mensajeria.registrarServiceWorker();
      const token = await mensajeria.obtenerToken(registro);
      if (token !== guardado) {
        await this.enviarToken(token);
        guardarToken(token);
      }
      this.fijar('activo');
      await this.escuchar(mensajeria);
    } catch {
      // Sin red o sin Firebase ahora: se reintenta en la próxima visita. No se molesta a la persona.
    }
  }

  /**
   * Al cerrar la sesión: da de baja el token (con la sesión que aún vale: llámalo ANTES de borrar los tokens de la
   * sesión) y olvida el dispositivo. Mejor esfuerzo: un fallo no impide salir. Devuelve de inmediato.
   * (`AuthService` envía la baja por su cuenta, sin esperar a que este servicio se cargue, y después llama a
   * `olvidarDispositivo()`; este método hace las dos cosas juntas.)
   */
  darDeBajaAlSalir(): void {
    const token = leerToken();
    if (token === null) return;
    this.darDeBajaEnServidor(token).catch(() => undefined);
    this.olvidarDispositivo();
  }

  /** Olvida este dispositivo en el navegador: token recordado, escucha con la pestaña abierta y token de Firebase. */
  olvidarDispositivo(): void {
    this.limpiarLocal();
    this.fijar(estadoDelNavegador() === 'bloqueado' ? 'bloqueado' : 'inactivo');
    void this.borrarTokenEnFirebase();
  }

  // ---- Servidor ---------------------------------------------------------------------------------------------------------

  private enviarToken(token: string): Promise<unknown> {
    return firstValueFrom(
      this.http.post(`${environment.apiUrl}/dispositivos-push`, { token, plataforma: 'web' }, {
        context: new HttpContext().set(SIN_TOAST_ERROR, true),
      }),
    );
  }

  private darDeBajaEnServidor(token: string): Promise<unknown> {
    return pedirBajaDelToken(this.http, token);
  }

  private limpiarLocal(): void {
    borrarTokenGuardado();
    this.dejarDeEscuchar?.();
    this.dejarDeEscuchar = null;
  }

  private async borrarTokenEnFirebase(): Promise<void> {
    try {
      const mensajeria = await this.cargarMensajeria();
      // Sin soporte no hay token que borrar (y el SDK lanzaría un error suelto al pedir su instancia de mensajería).
      if (await mensajeria.soportado()) await mensajeria.borrarToken();
    } catch {
      // El servidor ya lo dio de baja; que Firebase lo olvide es un extra.
    }
  }

  // ---- Con la pestaña abierta -------------------------------------------------------------------------------------------

  private async escuchar(mensajeria: MensajeriaPush): Promise<void> {
    if (this.dejarDeEscuchar !== null) return;
    this.dejarDeEscuchar = await mensajeria.alRecibir((mensaje) => this.alRecibirEnPrimerPlano(mensaje));
  }

  /** Un aviso llegó con la pestaña abierta: se refresca la lista y, si es nuevo para la persona, sale un aviso con "Ver". */
  alRecibirEnPrimerPlano(mensaje: MensajePush): void {
    const datos = mensaje.data ?? {};
    const tipo = datos['tipo'] ?? null;
    const referencia = datos['referencia_id'] ? Number(datos['referencia_id']) : null;
    const notificacionId = datos['notificacion_id'] ? Number(datos['notificacion_id']) : null;

    // La lista de notificaciones se actualiza siempre (sin avisos de error si el servidor no la entrega a este usuario).
    this.notificaciones.cargar(true).subscribe({ error: () => undefined });

    // Un mismo hecho (p. ej. la misma compra por `compra_confirmada` y por `pedido_diferido`) avisa una sola vez.
    if (!this.avisos.registrar(claveDeAviso(tipo, referencia, notificacionId))) return;
    if (this.estaViendoLoMismo(tipo, referencia)) return;

    const ruta = rutaDeAviso(tipo, referencia, datos['empresa_codigo']);
    this.mensajes?.add({
      key: CLAVE_TOAST_AVISO,
      severity: 'success',
      summary: mensaje.notification?.title || 'Tienes un aviso nuevo',
      detail: mensaje.notification?.body || undefined,
      life: 10000,
      data: { ruta },
    });
  }

  /** La persona ya está en la pantalla de esa compra o en el estado de su pago: avisarle sería repetirle lo que ve. */
  private estaViendoLoMismo(tipo: string | null, referencia: number | null): boolean {
    if (tipo === null || !(TIPOS_DE_VENTA as readonly string[]).includes(tipo)) return false;
    const url = this.router.url;
    if (url.includes('/checkout/estado/')) return true;
    return referencia !== null && new RegExp(`/mis-compras/${referencia}(?:[/?#]|$)`).test(url);
  }
}
