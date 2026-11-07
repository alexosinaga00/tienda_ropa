import { HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MessageService } from 'primeng/api';
import { firstValueFrom, timeout } from 'rxjs';
import { AvisosMostradosService, claveDeVenta } from '../../../core/avisos-mostrados.service';
import { ConectividadService } from '../../../core/conectividad.service';
import { codigoFuncional } from '../../../core/errores-funcionales';
import { PedidoDiferidoCrear, PedidoDiferidoRespuesta } from '../../../core/models/metodo-pago.models';
import {
  FALLOS_AUTOMATICOS_MAX,
  HUERFANO_ENVIANDO_MS,
  INTERVALO_COLA_CLIENTE_MS,
  MAX_LINEAS_PEDIDO,
  MENSAJE_PEDIDO_VENCIDO,
  MENSAJE_PEDIDO_VENCIDO_SERVIDOR,
  NOMBRE_CANDADO_PEDIDOS,
  PEDIDO_CADUCA_MS,
  TIMEOUT_PEDIDO_MS,
} from '../../../core/offline-cliente/cliente-offline.config';
import type {
  AlcanceCliente,
  CambiosPedido,
  LineaCarritoLocal,
  PedidoSinConexion,
} from '../../../core/offline-cliente/cliente-offline.models';
import { ClienteOfflineService } from '../../../core/offline-cliente/cliente-offline.service';
import { aCentavos, textoDinero, totalDeLineas } from '../../../core/offline-cliente/dinero';
import type { RepositorioCliente } from '../../../core/offline-cliente/repositorio-cliente';
import { esperaBackoffMs, leerRetryAfterMs } from '../../../core/offline/cola-sincronizacion.service';
import { generarUuid } from '../../../core/offline/sesion-offline.service';
import { PedidosDiferidosService } from '../data/pedidos-diferidos.service';
import { CarritoLocalService } from './carrito-local.service';
import { MetodoPagoLocalService } from './metodo-pago-local.service';

/** En qué está la cola de pedidos hechos sin conexión. */
export type EstadoColaPedidos =
  | 'inactiva'
  | 'sincronizando'
  | 'esperando_reintento'
  | 'sin_conexion'
  | 'pausada_sesion'
  | 'pausada'
  | 'detenida_por_fallos';

export const MOTIVO_DETENIDA_PEDIDOS = 'No se pudo enviar tu pedido. Sigue guardado: reinténtalo cuando quieras.';
export const MENSAJE_PEDIDO_INVALIDO =
  'No pudimos procesar tu pedido porque sus datos ya no son válidos. No se cobró nada: descártalo y arma uno nuevo.';

/** Lo que hace falta para poner un pedido en la cola. */
export interface EntradaPedido {
  sucursalId: number;
  sucursalNombre: string;
  /** Centavos. Sin conexión solo se ofrece retiro en sucursal: normalmente 0. */
  costoEnvioCentavos: number;
  lineas: LineaCarritoLocal[];
}

interface OpcionesProcesar {
  /** Botón "Enviar ahora": ignora la espera de los reintentos y levanta una pausa o una detención. */
  manual?: boolean;
  /** Volvió la red: levanta una pausa o una detención, pero respeta la espera de cada pedido. */
  reanudar?: boolean;
}

const claveAlcance = (a: AlcanceCliente | null): string | null => (a === null ? null : `${a.empresaId}:${a.usuarioId}`);
const ahoraIso = (): string => new Date().toISOString();

/**
 * Cola de PEDIDOS hechos sin conexión que se pagan con el PayPal guardado (Opción B).
 *
 * Reglas que no se rompen:
 *  - Un pedido NUNCA se borra por intentar enviarlo: solo cambia de estado. Cualquier fallo lo deja `pendiente` (con su
 *    espera) y el reenvío usa la MISMA `operacion_id`: el servidor no cobra dos veces y devuelve lo ya decidido.
 *  - Los pedidos salen UNO A UNO y en orden (el más antiguo primero). Si uno falla por algo temporal, los demás esperan.
 *  - Un solo ciclo a la vez: candado `fs-pedidos-sin-conexion` (Web Locks) entre pestañas y una promesa compartida dentro
 *    de la pestaña.
 *  - Solo se envían los pedidos de la persona de la sesión (el repositorio lo garantiza).
 *
 * Disparadores: volver la red, iniciar sesión / abrir la tienda con sesión, volver a la pestaña con pendientes, un
 * temporizador de 60 s, encolar un pedido y el botón "Enviar ahora".
 */
@Injectable({ providedIn: 'root' })
export class PedidosSinConexionService {
  private readonly api = inject(PedidosDiferidosService);
  private readonly cliente = inject(ClienteOfflineService);
  private readonly conectividad = inject(ConectividadService);
  /** Opcional: la app lo provee en la raíz; si no está, el aviso en pantalla (franja y lista) basta. */
  private readonly mensajes = inject(MessageService, { optional: true });
  private readonly carritoLocal = inject(CarritoLocalService);
  private readonly metodoPagoLocal = inject(MetodoPagoLocalService);
  private readonly avisos = inject(AvisosMostradosService);

  private readonly pedidosState = signal<PedidoSinConexion[]>([]);
  /** Mis pedidos sin conexión, del más nuevo al más viejo. */
  readonly pedidos = this.pedidosState.asReadonly();
  /** Esperando salir o enviándose. */
  readonly pendientes = computed(() => this.pedidosState().filter((p) => p.estado === 'pendiente' || p.estado === 'enviando'));
  /** Cobrados o rechazados que el cliente todavía no vio. */
  readonly sinVer = computed(() => this.pedidosState().filter((p) => (p.estado === 'cobrado' || p.estado === 'rechazado') && !p.visto));

  readonly estadoCola = signal<EstadoColaPedidos>('inactiva');
  /** Texto para el cliente cuando la cola está pausada o detenida (null si no). */
  readonly motivoPausa = signal<string | null>(null);
  /** Cuándo (ISO) se reintentará sola; null si no hay un reintento programado. */
  readonly proximoIntentoEn = signal<string | null>(null);

  private cicloEnCurso: Promise<void> | null = null;
  private nuevaDuranteCiclo = false;
  private opcionesPendientes: OpcionesProcesar | null = null;
  private fallosSeguidos = 0;
  private temporizadorReintento: ReturnType<typeof setTimeout> | null = null;
  /** `undefined` = todavía no se observó la sesión. */
  private claveActual: string | null | undefined = undefined;
  private clavePausadaPorSesion: string | null = null;

  constructor() {
    const destroyRef = inject(DestroyRef);

    this.conectividad.volvioConexion$?.pipe(takeUntilDestroyed(destroyRef)).subscribe(() => {
      this.fallosSeguidos = 0;
      void this.procesar({ reanudar: true });
    });

    // Entra, sale o cambia la persona: arranca o se reinicia la cola de esa persona (también al abrir la tienda con sesión).
    effect(() => {
      const alcance = this.cliente.alcance();
      untracked(() => this.alCambiarAlcance(alcance));
    });

    if (typeof setInterval === 'function') {
      const intervalo = setInterval(() => {
        if (this.conectividad.enLinea() && this.pendientes().length > 0) void this.procesar();
      }, INTERVALO_COLA_CLIENTE_MS);
      destroyRef.onDestroy(() => clearInterval(intervalo));
    }

    if (typeof document !== 'undefined') {
      const alVolverALaPestana = () => {
        if (document.visibilityState === 'visible' && this.pendientes().length > 0) void this.procesar();
      };
      document.addEventListener('visibilitychange', alVolverALaPestana);
      destroyRef.onDestroy(() => document.removeEventListener('visibilitychange', alVolverALaPestana));
    }

    destroyRef.onDestroy(() => this.cancelarReintento());
  }

  // ---- Interfaz pública ----------------------------------------------------------------------------------------------------

  /** Vuelve a leer los pedidos de la sesión desde la base local. Nunca lanza. */
  async refrescar(): Promise<void> {
    const repo = this.cliente.repositorio();
    if (repo === null) {
      this.pedidosState.set([]);
      return;
    }
    const clave = claveAlcance(repo.alcance);
    try {
      const pedidos = await repo.pedidos();
      // Si mientras se leía cambió la sesión, estos pedidos ya no son de quien mira.
      if (clave === claveAlcance(this.cliente.alcance())) this.pedidosState.set(pedidos);
    } catch (error) {
      console.warn('No se pudieron leer los pedidos sin conexión.', error);
    }
  }

  /**
   * Pone el pedido en la cola y vacía el carrito local EN LA MISMA transacción. Devuelve el pedido, o null si no hay sesión,
   * el carrito está vacío o es demasiado grande. Con red, la cola intenta enviarlo enseguida.
   */
  async encolar(entrada: EntradaPedido): Promise<PedidoSinConexion | null> {
    const repo = this.cliente.repositorio();
    if (repo === null || entrada.lineas.length === 0 || entrada.lineas.length > MAX_LINEAS_PEDIDO) return null;

    const ahora = ahoraIso();
    const totalMaximo = totalDeLineas(entrada.lineas) + entrada.costoEnvioCentavos;
    const pedido: PedidoSinConexion = {
      empresa_id: repo.alcance.empresaId,
      usuario_id: repo.alcance.usuarioId,
      operacion_id: generarUuid(),
      estado: 'pendiente',
      sucursal_id: entrada.sucursalId,
      sucursal_nombre: entrada.sucursalNombre,
      costo_envio: textoDinero(entrada.costoEnvioCentavos),
      lineas: entrada.lineas.map((l) => ({
        variante_id: l.variante_id,
        cantidad: l.cantidad,
        producto_nombre: l.producto_nombre,
        talla: l.talla,
        color: l.color,
        precio_unitario: l.precio_unitario,
        imagen: l.imagen,
      })),
      total_maximo: textoDinero(totalMaximo),
      fecha_pedido: ahora,
      creado_en: ahora,
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
    };
    try {
      const guardado = await repo.registrarPedido(pedido, true);
      await this.carritoLocal.cargar();
      await this.refrescar();
      this.notificarNuevoPedido();
      return guardado;
    } catch (error) {
      console.warn('No se pudo guardar el pedido sin conexión.', error);
      return null;
    }
  }

  /** Quita un pedido que todavía no salió. Devuelve false si no existe o ya se está enviando o está resuelto. */
  async descartar(operacionId: string): Promise<boolean> {
    const repo = this.cliente.repositorio();
    if (repo === null) return false;
    try {
      const quitado = await repo.descartarPedido(operacionId);
      await this.refrescar();
      return quitado;
    } catch (error) {
      console.warn('No se pudo descartar el pedido.', error);
      return false;
    }
  }

  /**
   * "Borrarlos y salir": quita del equipo TODO lo de esta cuenta, también los pedidos sin enviar. Solo lo llama la
   * pantalla de cerrar sesión cuando el cliente lo eligió. Nunca lanza; devuelve false si no se pudo.
   */
  async borrarTodoDeEstaCuenta(): Promise<boolean> {
    const repo = this.cliente.repositorio();
    if (repo === null) return true;
    try {
      await repo.borrarTodo();
    } catch (error) {
      console.warn('No se pudieron borrar los pedidos de este equipo.', error);
      return false;
    }
    this.pedidosState.set([]);
    await this.carritoLocal.cargar();
    return true;
  }

  /** El cliente ya vio los resultados: dejan de contarse como nuevos. */
  async marcarVistos(): Promise<void> {
    const repo = this.cliente.repositorio();
    if (repo === null) return;
    try {
      await repo.marcarVistos();
    } catch (error) {
      console.warn('No se pudieron marcar los pedidos como vistos.', error);
    }
    await this.refrescar();
  }

  /** Envía ahora, ignorando la espera de los reintentos. Nunca lanza. */
  async enviarAhora(): Promise<void> {
    await this.procesar({ manual: true });
  }

  // ---- Sesión --------------------------------------------------------------------------------------------------------------

  private alCambiarAlcance(alcance: AlcanceCliente | null): void {
    const clave = claveAlcance(alcance);
    if (clave === this.claveActual) return;
    this.claveActual = clave;

    if (clave === null) {
      // Sin sesión no hay nada que mostrar ni que enviar. Lo guardado en el equipo NO se toca.
      this.cancelarReintento();
      this.proximoIntentoEn.set(null);
      this.pedidosState.set([]);
      if (this.estadoCola() !== 'pausada_sesion') this.reiniciarEstado();
      return;
    }

    if (this.estadoCola() === 'pausada_sesion' && this.clavePausadaPorSesion === clave) {
      // La misma persona volvió a iniciar sesión: sus pedidos siguen guardados y se reanuda.
      this.limpiarPausa();
      this.fallosSeguidos = 0;
    } else {
      this.reiniciarEstado();
    }
    void this.refrescar().then(() => {
      // Si todavía corre el ciclo de la persona anterior, el de esta empieza cuando aquel termine.
      if (this.cicloEnCurso !== null) this.nuevaDuranteCiclo = true;
      else void this.procesar();
    });
  }

  private reiniciarEstado(): void {
    this.cancelarReintento();
    this.limpiarPausa();
    this.fallosSeguidos = 0;
    this.estadoCola.set('inactiva');
    this.proximoIntentoEn.set(null);
  }

  private limpiarPausa(): void {
    this.estadoCola.set('inactiva');
    this.motivoPausa.set(null);
    this.clavePausadaPorSesion = null;
  }

  private mismoAlcance(capturado: AlcanceCliente): boolean {
    return claveAlcance(this.cliente.alcance()) === claveAlcance(capturado);
  }

  // ---- Ciclo ---------------------------------------------------------------------------------------------------------------

  private notificarNuevoPedido(): void {
    if (this.cicloEnCurso !== null) {
      // El pedido se guardó después de que el ciclo leyó su lista: al terminar, el ciclo vuelve a mirar.
      this.nuevaDuranteCiclo = true;
      return;
    }
    // Con un reintento ya programado (el servidor falló hace poco) no se martilla: el nuevo sale con el siguiente intento.
    if (this.estadoCola() === 'esperando_reintento') return;
    void this.procesar();
  }

  /** Un solo ciclo a la vez: un segundo disparo comparte el que está en curso (no hay segundo envío). */
  private procesar(opciones: OpcionesProcesar = {}): Promise<void> {
    if (this.cicloEnCurso !== null) {
      // No se envía en paralelo, pero tampoco se pierde el aviso (p. ej. "volvió la red" mientras el ciclo creía estar sin
      // conexión): al terminar este ciclo corre otro con lo pedido.
      this.nuevaDuranteCiclo = true;
      this.opcionesPendientes = {
        manual: this.opcionesPendientes?.manual === true || opciones.manual === true,
        reanudar: this.opcionesPendientes?.reanudar === true || opciones.reanudar === true,
      };
      return this.cicloEnCurso;
    }
    this.cicloEnCurso = this.conCandado(() => this.ciclo(opciones))
      .catch((error: unknown) => console.warn('La cola de pedidos falló; los pedidos siguen guardados.', error))
      .finally(() => {
        this.cicloEnCurso = null;
        if (this.nuevaDuranteCiclo) {
          const siguientes = this.opcionesPendientes ?? {};
          this.nuevaDuranteCiclo = false;
          this.opcionesPendientes = null;
          void this.procesar(siguientes);
        }
      });
    return this.cicloEnCurso;
  }

  /** Con Web Locks, dos pestañas no envían a la vez; sin ellos, solo la bandera de esta pestaña (el servidor es idempotente). */
  private conCandado(trabajo: () => Promise<void>): Promise<void> {
    const locks = typeof navigator !== 'undefined' ? (navigator as Navigator & { locks?: LockManager }).locks : undefined;
    if (!locks || typeof locks.request !== 'function') return trabajo();
    return locks.request(NOMBRE_CANDADO_PEDIDOS, { ifAvailable: true }, async (candado) => {
      if (candado === null) return; // otra pestaña está enviando
      await trabajo();
    }) as Promise<void>;
  }

  private async ciclo(opciones: OpcionesProcesar): Promise<void> {
    const repo = this.cliente.repositorio();
    if (repo === null) return;
    const alcance = repo.alcance;
    const manual = opciones.manual === true;
    const forzado = manual || opciones.reanudar === true;

    // Primero lo vencido: un pedido de más de 7 días no se envía y no cuenta como pendiente (también sin conexión).
    await this.vencerCaducados(repo);

    if (!this.conectividad.enLinea()) {
      await this.refrescar();
      const estado = this.estadoCola();
      if (this.pendientes().length > 0 && estado !== 'pausada_sesion' && estado !== 'pausada' && estado !== 'detenida_por_fallos') {
        this.cancelarReintento();
        this.proximoIntentoEn.set(null);
        this.estadoCola.set('sin_conexion');
      }
      return;
    }

    const estado = this.estadoCola();
    const detenida = estado === 'pausada_sesion' || estado === 'pausada' || estado === 'detenida_por_fallos';
    // Una sesión vencida solo se levanta al volver a entrar (la maneja el cambio de sesión), no con la red ni con el botón.
    if (estado === 'pausada_sesion') return;
    if (detenida && !forzado) return;
    if (detenida) this.limpiarPausa();
    if (forzado) this.fallosSeguidos = 0;
    this.cancelarReintento();

    let detener = false;
    const pedidos = await repo.pedidosParaEnviar(ahoraIso(), HUERFANO_ENVIANDO_MS);
    for (const pedido of pedidos) {
      if (!this.mismoAlcance(alcance)) return;
      // Orden estricto: si el más antiguo todavía espera su turno, los demás también.
      if (!manual && pedido.proximo_intento_en !== null && Date.parse(pedido.proximo_intento_en) > Date.now()) break;
      // El chequeo de caducidad corre ANTES de cada envío (un ciclo largo o una espera pudo hacerlo vencer).
      if (pedido.estado === 'pendiente' && this.caducado(pedido)) {
        await this.marcarVencido(repo, pedido.operacion_id);
        continue;
      }

      this.estadoCola.set('sincronizando');
      this.motivoPausa.set(null);
      this.proximoIntentoEn.set(null);
      if (!(await repo.marcarEnviando(pedido.operacion_id, ahoraIso()))) continue;
      await this.refrescar();

      if ((await this.enviarUno(repo, alcance, pedido)) === 'detener') {
        detener = true;
        break;
      }
    }

    if (!this.mismoAlcance(alcance)) return;
    await this.refrescar();
    if (!detener) await this.fijarEstadoTrasCiclo(repo);
  }

  /** Más de `PEDIDO_CADUCA_DIAS` días desde que se creó en este equipo. */
  private caducado(pedido: PedidoSinConexion): boolean {
    return Date.now() - Date.parse(pedido.creado_en) > PEDIDO_CADUCA_MS;
  }

  private marcarVencido(repo: RepositorioCliente, operacionId: string): Promise<boolean> {
    return this.cambiar(repo, operacionId, {
      estado: 'vencido',
      motivo: 'pedido_vencido',
      mensaje: MENSAJE_PEDIDO_VENCIDO,
      resuelto_en: ahoraIso(),
      ultimo_error: null,
      proximo_intento_en: null,
    });
  }

  /** Pasa a `vencido` los pedidos pendientes que ya pasaron el plazo. Solo los `pendiente`: un `enviando` puede estar decidido en el servidor. */
  private async vencerCaducados(repo: RepositorioCliente): Promise<void> {
    let alguno = false;
    try {
      for (const pedido of await repo.pedidos()) {
        if (pedido.estado === 'pendiente' && this.caducado(pedido) && (await this.marcarVencido(repo, pedido.operacion_id))) alguno = true;
      }
    } catch (error) {
      console.warn('No se pudo revisar la caducidad de los pedidos.', error);
    }
    if (alguno) await this.refrescar();
  }

  /** Envía UN pedido y guarda lo que pase. 'seguir': se puede mirar el siguiente; 'detener': el ciclo termina aquí. */
  private async enviarUno(repo: RepositorioCliente, alcance: AlcanceCliente, pedido: PedidoSinConexion): Promise<'seguir' | 'detener'> {
    const cuerpo: PedidoDiferidoCrear = {
      operacion_id: pedido.operacion_id,
      sucursal_id: pedido.sucursal_id,
      costo_envio: pedido.costo_envio,
      lineas: pedido.lineas.map((l) => ({ variante_id: l.variante_id, cantidad: l.cantidad })),
      total_maximo: pedido.total_maximo,
      fecha_pedido: pedido.fecha_pedido,
    };

    let respuesta: PedidoDiferidoRespuesta;
    try {
      respuesta = await firstValueFrom(this.api.enviar(cuerpo).pipe(timeout({ first: TIMEOUT_PEDIDO_MS })));
    } catch (error) {
      return this.alFallar(repo, alcance, pedido, error);
    }

    if (!respuesta || (respuesta.estado !== 'cobrado' && respuesta.estado !== 'rechazado')) {
      // Un 200 que no es lo que manda este servidor (un proxy, una página de error): se trata como un fallo temporal.
      return this.devolverPorFallo(repo, pedido, 'respuesta_invalida');
    }

    // El servidor también vence los pedidos de más de 7 días: decisión final, con un texto claro en vez del genérico.
    const mensaje = respuesta.motivo === 'pedido_vencido' ? MENSAJE_PEDIDO_VENCIDO_SERVIDOR : (respuesta.mensaje ?? null);
    const guardado = await this.cambiar(repo, pedido.operacion_id, {
      estado: respuesta.estado,
      motivo: respuesta.motivo ?? null,
      mensaje,
      venta_id: respuesta.venta_id ?? null,
      codigo_venta: respuesta.codigo_venta ?? null,
      total: respuesta.total ?? null,
      total_usd: respuesta.total_usd ?? null,
      resuelto_en: ahoraIso(),
      ultimo_error: null,
      proximo_intento_en: null,
      visto: false,
    });
    this.fallosSeguidos = 0;
    if (guardado && this.mismoAlcance(alcance)) await this.avisarResultado({ ...respuesta, mensaje: mensaje ?? respuesta.mensaje });
    return 'seguir';
  }

  private async alFallar(
    repo: RepositorioCliente,
    alcance: AlcanceCliente,
    pedido: PedidoSinConexion,
    error: unknown,
  ): Promise<'seguir' | 'detener'> {
    if (!(error instanceof HttpErrorResponse)) {
      return this.devolverPorFallo(repo, pedido, (error as { name?: string } | null)?.name === 'TimeoutError' ? 'timeout' : 'error_red');
    }

    switch (error.status) {
      case 401: {
        // El interceptor ya intentó renovar la sesión: si llegó aquí, venció. El pedido sigue guardado.
        await this.volverAPendiente(repo, pedido.operacion_id, 'sesion_vencida', null);
        this.cancelarReintento();
        this.proximoIntentoEn.set(null);
        if (this.mismoAlcance(alcance)) {
          this.clavePausadaPorSesion = claveAlcance(alcance);
          this.estadoCola.set('pausada_sesion');
          this.motivoPausa.set('Inicia sesión para enviar tu pedido. Sigue guardado.');
        }
        return 'detener';
      }
      case 403: {
        // La tienda no puede recibir pedidos ahora (suscripción, plan o permiso): no es un rechazo del pedido.
        const codigo = codigoFuncional(error) ?? 'http_403';
        await this.volverAPendiente(repo, pedido.operacion_id, codigo, null);
        this.cancelarReintento();
        this.proximoIntentoEn.set(null);
        if (this.mismoAlcance(alcance)) {
          this.estadoCola.set('pausada');
          this.motivoPausa.set(
            codigo === 'suscripcion_no_activa'
              ? 'La tienda no puede recibir pedidos por ahora. Tu pedido sigue guardado: inténtalo más tarde.'
              : 'No pudimos enviar tu pedido porque tu cuenta no tiene permiso para comprar. Tu pedido sigue guardado.',
          );
        }
        return 'detener';
      }
      case 400:
      case 422: {
        // El servidor dice que el pedido tiene mala forma: reintentar no lo arregla. No se cobró; queda a la vista para descartarlo.
        await this.cambiar(repo, pedido.operacion_id, {
          estado: 'rechazado',
          motivo: 'pedido_invalido',
          mensaje: MENSAJE_PEDIDO_INVALIDO,
          resuelto_en: ahoraIso(),
          ultimo_error: `http_${error.status}`,
          proximo_intento_en: null,
          visto: false,
        });
        this.fallosSeguidos = 0;
        return 'seguir';
      }
      case 429:
        return this.devolverPorFallo(repo, pedido, 'http_429', leerRetryAfterMs(error.headers?.get('Retry-After')));
      case 0:
        if (!this.conectividad.enLinea()) {
          // Se fue la red a mitad del envío: no es un fallo del servidor. Espera sin castigo hasta volver la conexión.
          await this.volverAPendiente(repo, pedido.operacion_id, 'sin_conexion', null);
          this.cancelarReintento();
          this.proximoIntentoEn.set(null);
          if (this.mismoAlcance(alcance)) this.estadoCola.set('sin_conexion');
          return 'detener';
        }
        return this.devolverPorFallo(repo, pedido, 'sin_conexion');
      default:
        // 503 `paypal_no_disponible` (resultado incierto) y cualquier otro fallo del servidor: se reintenta con la misma operacion_id.
        return this.devolverPorFallo(repo, pedido, codigoFuncional(error) ?? `http_${error.status}`);
    }
  }

  /** Red, tiempo agotado, 503, 5xx, 429...: el pedido vuelve a `pendiente` con espera y el ciclo termina. */
  private async devolverPorFallo(
    repo: RepositorioCliente,
    pedido: PedidoSinConexion,
    motivo: string,
    esperaFija: number | null = null,
  ): Promise<'detener'> {
    const espera = esperaFija ?? esperaBackoffMs(this.fallosSeguidos + 1);
    await this.volverAPendiente(repo, pedido.operacion_id, motivo, espera);
    this.registrarFallo(espera);
    return 'detener';
  }

  /** Suma un fallo seguido: reintenta sola con espera creciente y, pasado el tope, se detiene (siguen guardados). */
  private registrarFallo(esperaMs: number): void {
    this.fallosSeguidos += 1;
    if (this.fallosSeguidos >= FALLOS_AUTOMATICOS_MAX) {
      this.cancelarReintento();
      this.proximoIntentoEn.set(null);
      this.estadoCola.set('detenida_por_fallos');
      this.motivoPausa.set(MOTIVO_DETENIDA_PEDIDOS);
      return;
    }
    this.estadoCola.set('esperando_reintento');
    this.motivoPausa.set(null);
    this.programarReintento(esperaMs);
  }

  // ---- Reintentos ----------------------------------------------------------------------------------------------------------

  private programarReintento(esperaMs: number): void {
    this.cancelarReintento();
    this.proximoIntentoEn.set(new Date(Date.now() + esperaMs).toISOString());
    // Unos milisegundos de margen: al despertar, la espera del pedido ya tiene que haber pasado.
    this.temporizadorReintento = setTimeout(() => {
      this.temporizadorReintento = null;
      void this.procesar();
    }, esperaMs + 25);
  }

  private cancelarReintento(): void {
    if (this.temporizadorReintento !== null) {
      clearTimeout(this.temporizadorReintento);
      this.temporizadorReintento = null;
    }
  }

  /** Terminado un ciclo sin fallos: si algún pedido sigue esperando su turno, se programa; si no, la cola descansa. */
  private async fijarEstadoTrasCiclo(repo: RepositorioCliente): Promise<void> {
    const estado = this.estadoCola();
    if (estado === 'pausada_sesion' || estado === 'pausada' || estado === 'detenida_por_fallos') return;
    let proxima: number | null = null;
    try {
      const ahora = Date.now();
      const esperando = (await repo.pedidosParaEnviar(ahoraIso(), HUERFANO_ENVIANDO_MS)).filter(
        (p) => p.proximo_intento_en !== null && Date.parse(p.proximo_intento_en) > ahora,
      );
      if (esperando.length > 0) proxima = Math.min(...esperando.map((p) => Date.parse(p.proximo_intento_en as string)));
    } catch {
      proxima = null;
    }
    if (proxima !== null) {
      this.estadoCola.set('esperando_reintento');
      this.motivoPausa.set(null);
      this.programarReintento(Math.max(proxima - Date.now(), 0));
      return;
    }
    this.cancelarReintento();
    this.proximoIntentoEn.set(null);
    this.motivoPausa.set(null);
    this.estadoCola.set('inactiva');
  }

  // ---- Escrituras seguras y avisos -----------------------------------------------------------------------------------------

  private async volverAPendiente(repo: RepositorioCliente, operacionId: string, motivo: string, esperaMs: number | null): Promise<void> {
    await this.cambiar(repo, operacionId, {
      estado: 'pendiente',
      ultimo_error: motivo,
      proximo_intento_en: esperaMs === null ? null : new Date(Date.now() + esperaMs).toISOString(),
    });
  }

  /** Cambia un pedido sin lanzar: si no se puede (ya era final, falló IndexedDB) queda como estaba y se recupera después. */
  private async cambiar(repo: RepositorioCliente, operacionId: string, cambios: CambiosPedido): Promise<boolean> {
    try {
      await repo.actualizarPedido(operacionId, cambios);
      return true;
    } catch (error) {
      console.warn('No se pudo actualizar un pedido local.', error);
      return false;
    }
  }

  /** Un toast cuando un pedido pasa a cobrado o rechazado. Si no tenía PayPal guardado, se recuerda para decidir sin red. */
  private async avisarResultado(respuesta: PedidoDiferidoRespuesta): Promise<void> {
    if (respuesta.estado === 'cobrado') {
      // Si el aviso push (o el panel de pago aprobado) ya le contó a la persona de esta misma compra, no se repite.
      if (respuesta.venta_id != null && !this.avisos.registrar(claveDeVenta(respuesta.venta_id))) return;
      const total = respuesta.total ? ` por Bs ${textoDinero(aCentavos(respuesta.total))}` : '';
      this.mensajes?.add({
        severity: 'success',
        summary: 'Cobramos tu pedido',
        detail: respuesta.codigo_venta ? `Tu pedido ${respuesta.codigo_venta}${total} está pagado.` : `Tu pedido${total} está pagado.`,
        life: 8000,
      });
    } else {
      if (respuesta.motivo === 'sin_metodo_pago') {
        await this.metodoPagoLocal.recordar({ guardado: false, correo_paypal: null, guardado_en: null });
      }
      this.mensajes?.add({
        severity: 'warn',
        summary: 'No pudimos cobrar tu pedido',
        detail: respuesta.mensaje || 'Revisa "Mis pedidos sin conexión" para ver el motivo.',
        life: 10000,
      });
    }
  }
}
