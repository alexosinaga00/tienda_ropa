import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpClient, HttpContext, HttpErrorResponse } from '@angular/common/http';
import {
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  Injector,
  OnDestroy,
  OnInit,
  ViewChild,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { TableModule } from 'primeng/table';
import { forkJoin, map, of, switchMap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { ConectividadService } from '../../core/conectividad.service';
import { fechaLocalIso } from '../../core/date-utils';
import { SIN_TOAST_ERROR } from '../../core/http-contexts';
import { CatalogoDetalle, ProductoImagenLookupItem, VarianteBusqueda } from '../../core/models/catalogo.models';
import { Empleado, Sucursal } from '../../core/models/organizacion.models';
import { MetodoPagoCaja, Pago, PagoCajaRequest, PagoCajaRespuesta } from '../../core/models/pagos.models';
import { FilaVentasPorSucursal, ReporteVentas } from '../../core/models/reportes.models';
import { Reserva } from '../../core/models/reservas.models';
import {
  Devolucion,
  DevolucionCrear,
  PlazoCambio,
  Venta,
  VentaPresencialCrear,
  etiquetaDevolucion,
} from '../../core/models/ventas.models';
import { CatalogoLocalService, VarianteBusquedaLocal } from '../../core/offline/catalogo-local.service';
import { ColaSincronizacionService } from '../../core/offline/cola-sincronizacion.service';
import { SesionOfflineService } from '../../core/offline/sesion-offline.service';
import { aCentavos } from '../../core/offline/dinero-offline';
import type { FaltanteLocal, OperacionOffline } from '../../core/offline/offline.models';
import {
  ErrorOperacionOffline,
  OperacionesOfflineService,
  StockLocalInsuficienteError,
} from '../../core/offline/operaciones-offline.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { NombreIcono } from '../../shared/icono/iconos';

/** Una talla o color por la que se puede cambiar una línea devuelta (mismo producto y mismo precio). */
interface OpcionCambio {
  variante_id: number;
  /** "L · Azul". */
  etiqueta: string;
  /** Unidades disponibles en la sucursal de la venta. */
  disponible: number;
}

interface LineaCarrito {
  variante_id: number;
  descripcion: string;
  /** Nombre del producto y "talla · color": se muestran en dos renglones. */
  nombre: string;
  detalleVariante: string;
  sku: string;
  precio_efectivo: number;
  /** Solo si la prenda salió de los datos descargados (sin conexión): es el descuento que usará la venta guardada. */
  descuento_unitario?: number;
  cantidad: number;
}

/** El cobro sin conexión en curso: su identificador se crea UNA vez y se conserva en cada reintento (idempotencia local). */
interface CobroOffline {
  operacionId: string;
  /** El cajero ya vio el aviso de "no hay stock local" y decidió registrar de todos modos. */
  aceptarSinStock: boolean;
}

type FaseVenta = 'armando' | 'cobrando';

/** Cada cuánto como máximo se refresca la cuenta regresiva del plazo de cambio. */
const INTERVALO_PLAZO_MS = 60_000;
/** Tope de ventas del historial cuyo plazo se consulta a la vez; las demás quedan sin indicador (el botón sigue como siempre). */
const MAX_PLAZOS_PARALELOS = 30;
/** Días hacia atrás que cubre "Ventas recientes": el plazo de cambio más largo de los planes es de 72 h. */
const DIAS_VENTAS_RECIENTES = 3;

/** localStorage: la última sucursal en la que cobró el administrador (alcance global), para no elegirla cada vez. */
const CLAVE_SUCURSAL_ADMIN = 'fs_caja_sucursal_admin';

/** Fila del resumen del administrador: una por sucursal, también las que hoy no vendieron nada. */
interface FilaResumenCaja {
  sucursal_id: number;
  sucursal: string;
  transacciones: number;
  total_ventas: number;
}

/** El plazo de una venta tal como lo dijo el servidor, más el reloj local al recibirlo (solo para la cuenta regresiva visible). */
interface PlazoVenta {
  /** null solo cuando se supo que venció (409) sin haber podido consultar el plazo. */
  plazoHoras: number | null;
  venceMs: number;
  /** Lo que respondió el servidor: él decide. */
  vigente: boolean;
  obtenidoMs: number;
}

/** Lo que se muestra de un plazo: el texto del indicador, el del botón y si ya venció. */
interface IndicadorPlazo {
  vencido: boolean;
  texto: string;
  titulo: string;
}

const OPCIONES_METODO_PAGO: { label: string; value: MetodoPagoCaja; icono: NombreIcono }[] = [
  { label: 'Efectivo', value: 'efectivo', icono: 'dinero' },
  { label: 'QR', value: 'qr', icono: 'qr' },
  { label: 'Tarjeta', value: 'tarjeta', icono: 'tarjeta' },
  { label: 'Transferencia', value: 'transferencia', icono: 'transferencia' },
];

@Component({
  selector: 'app-caja',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    FormsModule,
    ButtonModule,
    DialogModule,
    IconoComponent,
    TableModule,
  ],
  templateUrl: './caja.component.html',
  styleUrl: './caja.component.scss',
})
export class CajaComponent implements OnInit, OnDestroy {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly messageService = inject(MessageService);
  private readonly authService = inject(AuthService);
  private readonly conectividad = inject(ConectividadService);
  private readonly injector = inject(Injector);

  @ViewChild('inputBusqueda') private inputBusqueda?: ElementRef<HTMLInputElement>;
  @ViewChild('inputMontoRecibido') private inputMontoRecibido?: ElementRef<HTMLInputElement>;
  @ViewChild('inputReserva') private inputReserva?: ElementRef<HTMLInputElement>;

  protected readonly opcionesMetodoPago = OPCIONES_METODO_PAGO;

  /** Marca del comprobante: la empresa de la sesión; sin dato, un título neutro. */
  protected readonly nombreEmpresa = computed(
    () => this.authService.usuario()?.empresa_nombre?.trim() || 'Comprobante de venta',
  );

  /** Nombre de las prendas que se agregaron por búsqueda (variante_id -> "producto · talla · color"). */
  private readonly nombresVariante: Record<number, string> = {};

  protected nombreVariante(varianteId: number): string {
    return this.nombresVariante[varianteId] ?? `Variante ${varianteId}`;
  }

  /** Color del chip de estado de una venta en el historial de hoy. */
  protected claseEstadoVenta(estado: string): string {
    if (estado === 'pagada' || estado === 'entregada') return 'fs-chip--exito';
    if (estado === 'pendiente_pago') return 'fs-chip--advertencia';
    if (estado === 'anulada') return 'fs-chip--error';
    return '';
  }

  protected readonly sucursalId = signal<number | null>(null);
  protected readonly cargandoSucursal = signal(true);
  protected readonly noEsEmpleado = signal(false);

  // ---- Resumen para el administrador (sin sucursal propia = alcance global) ----
  private readonly esAdministrador = computed(() => this.authService.roles().includes('administrador'));
  protected readonly vistaResumenGlobal = signal(false);
  protected readonly cargandoResumen = signal(false);
  protected readonly resumenPorSucursal = signal<FilaVentasPorSucursal[]>([]);
  /** El resumen no se pudo cargar: se avisa (antes un error se veía igual que "sin ventas") y se ofrece reintentar. */
  protected readonly errorResumen = signal(false);
  /** Sucursales donde el administrador puede cobrar (activas y que no son depósito). */
  protected readonly sucursalesCaja = signal<Sucursal[]>([]);
  protected readonly cargandoSucursales = signal(false);

  /** Una fila por sucursal con lo vendido hoy (0 si no vendió). Si no hubo lista de sucursales, solo las que vendieron. */
  protected readonly filasResumen = computed<FilaResumenCaja[]>(() => {
    const vendido = new Map(this.resumenPorSucursal().map((fila) => [fila.sucursal_id, fila]));
    const sucursales = this.sucursalesCaja();
    if (sucursales.length === 0) {
      return this.resumenPorSucursal().map((f) => ({ ...f, total_ventas: Number(f.total_ventas) }));
    }
    return sucursales.map((s) => {
      const fila = vendido.get(s.id);
      return {
        sucursal_id: s.id,
        sucursal: s.nombre,
        transacciones: fila?.transacciones ?? 0,
        // El backend serializa los montos (Decimal) como texto.
        total_ventas: Number(fila?.total_ventas ?? 0),
      };
    });
  });

  protected readonly fase = signal<FaseVenta>('armando');

  /** Sin red o sin servidor: la caja trabaja con lo descargado en este equipo (E14). El mismo criterio que la búsqueda. */
  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');

  // ---- Búsqueda de producto -------------------------------------------------

  protected readonly textoBusqueda = signal('');
  protected readonly resultados = signal<VarianteBusqueda[]>([]);
  protected readonly indiceResaltado = signal(0);
  protected readonly buscando = signal(false);
  /** La última búsqueda se resolvió con los datos descargados en este equipo (sin conexión). */
  protected readonly busquedaLocal = signal(false);

  // ---- Carrito / reserva -----------------------------------------------------

  protected readonly lineas = signal<LineaCarrito[]>([]);
  protected readonly reservaCargada = signal<Reserva | null>(null);
  protected readonly codigoReserva = signal('');
  protected readonly buscandoReserva = signal(false);

  protected readonly hayVentaEnCurso = computed(() => this.lineas().length > 0 || this.reservaCargada() !== null);

  protected readonly subtotalEstimado = computed(() =>
    this.lineas().reduce((acumulado, linea) => acumulado + linea.precio_efectivo * linea.cantidad, 0),
  );

  // ---- Cobro (fase 'cobrando': la venta ya existe, con total real) ----------------

  protected readonly ventaPendiente = signal<Venta | null>(null);
  protected readonly metodoPago = signal<MetodoPagoCaja>('efectivo');
  protected readonly montoRecibido = signal<number | null>(null);
  protected readonly registrandoVenta = signal(false);
  protected readonly registrandoPago = signal(false);

  protected readonly cambioEstimado = computed(() => {
    const venta = this.ventaPendiente();
    const recibido = this.montoRecibido();
    if (this.cobroOffline() !== null) {
      const recibidoCentavos = aCentavos(recibido);
      if (!Number.isFinite(recibidoCentavos)) return null;
      return Math.max(0, recibidoCentavos - this.totalLocal().total) / 100;
    }
    if (venta === null || recibido === null) return null;
    return Math.max(0, redondear(recibido - venta.total));
  });

  // ---- Venta sin conexión (E14b) ----------------------------------------------------------

  /** Cobro sin conexión en curso (fase 'cobrando' sin venta en el servidor); null = el flujo en línea de siempre. */
  protected readonly cobroOffline = signal<CobroOffline | null>(null);
  protected readonly guardandoOffline = signal(false);
  /** Mensaje listo para mostrar cuando la venta no se pudo guardar en este equipo. */
  protected readonly avisoOffline = signal<string | null>(null);
  /** Prendas que no alcanzan según el stock local: abren la confirmación "registrar de todos modos". */
  protected readonly faltantesLocales = signal<FaltanteLocal[]>([]);
  protected readonly sinStockVisible = signal(false);
  /** La venta guardada sin conexión, con la que se arma el comprobante local. */
  protected readonly comprobanteOffline = signal<OperacionOffline | null>(null);

  /** Subtotal, descuento y total del carrito en CENTAVOS, con el precio y el descuento descargados (la misma cuenta que la venta guardada). */
  protected readonly totalLocal = computed(() => {
    let subtotal = 0;
    let descuento = 0;
    for (const linea of this.lineas()) {
      subtotal += linea.cantidad * aCentavos(linea.precio_efectivo);
      descuento += linea.cantidad * aCentavos(linea.descuento_unitario ?? 0);
    }
    return { subtotal, descuento, total: subtotal - descuento };
  });

  /** Todas las líneas salieron de los datos descargados: el total mostrado es exactamente el que se guardará. */
  protected readonly totalLocalExacto = computed(() => this.lineas().every((l) => l.descuento_unitario !== undefined));

  // ---- Comprobante -------------------------------------------------------------

  protected readonly comprobanteVisible = signal(false);
  protected readonly ventaConfirmada = signal<Venta | null>(null);
  protected readonly pagoConfirmado = signal<Pago | null>(null);
  protected readonly cambioConfirmado = signal<number | null>(null);

  // ---- Ventas recientes --------------------------------------------------------
  // Un cambio o una devolución casi nunca es el mismo día de la compra: se listan los últimos 3 días (cubre el plazo
  // más largo de los planes, 72 h) y se puede buscar por código. El servidor igual decide si el plazo sigue vigente.

  protected readonly historialVisible = signal(false);
  protected readonly ventasRecientes = signal<Venta[]>([]);
  protected readonly cargandoHistorial = signal(false);
  protected readonly busquedaHistorial = signal('');
  /** Las ventas recientes, filtradas por el código que se escribió (sin distinguir mayúsculas). */
  protected readonly ventasFiltradas = computed(() => {
    const texto = this.busquedaHistorial().trim().toLowerCase();
    const ventas = this.ventasRecientes();
    return texto ? ventas.filter((v) => v.codigo.toLowerCase().includes(texto)) : ventas;
  });
  protected readonly etiquetaDevolucion = etiquetaDevolucion;

  // ---- Devoluciones --------------------------------------------------------------

  protected readonly devolucionVisible = signal(false);
  protected readonly ventaParaDevolucion = signal<Venta | null>(null);
  protected readonly cantidadesDevolucion = signal<Record<number, number>>({});
  protected readonly registrandoDevolucion = signal(false);
  /** Mensaje del servidor cuando rechaza (409) la devolución: se muestra dentro del diálogo. */
  protected readonly errorDevolucion = signal<string | null>(null);
  /** Se registró una devolución: el historial muestra el paso siguiente del CAMBIO (la nueva venta). */
  protected readonly cambioPendiente = signal(false);
  /** Por línea de la venta (id del detalle): las tallas o colores por los que se puede cambiar. */
  protected readonly opcionesCambio = signal<Record<number, OpcionCambio[]>>({});
  /** Por línea de la venta: la variante nueva elegida (null o ausente = solo devolver). */
  protected readonly cambiosElegidos = signal<Record<number, number | null>>({});
  protected readonly cargandoOpcionesCambio = signal(false);
  /** No se pudieron cargar las tallas: se avisa y la devolución simple sigue disponible. */
  protected readonly errorOpcionesCambio = signal(false);

  // ---- Plazo para devolver o cambiar (D19) ---------------------------------------
  // El servidor decide: el plazo y su vencimiento salen de GET /ventas/{id}/plazo-cambio. El reloj
  // del navegador solo mueve la cuenta regresiva visible y, al llegar a cero, se vuelve a preguntar.

  private readonly plazos = signal<Record<number, PlazoVenta>>({});
  /** Reloj local de la cuenta regresiva (se actualiza con la consulta y con cada tic). */
  private readonly ahora = signal(Date.now());
  private temporizadorPlazo: ReturnType<typeof setTimeout> | null = null;
  /** Última consulta pedida por venta: una respuesta vieja no pisa a una más nueva. */
  private readonly secuenciaPlazo = new Map<number, number>();
  /** Ventas cuya cuenta llegó a cero y ya se volvió a preguntar al servidor. */
  private readonly vencimientoConfirmado = new Set<number>();

  constructor() {
    // El reloj de la cuenta regresiva corre solo mientras se ve el historial o el diálogo de devolución.
    effect(() => {
      const historial = this.historialVisible();
      this.devolucionVisible();
      this.plazos();
      untracked(() => {
        this.programarTic();
        // El aviso del cambio vive en el historial: al cerrarlo (con la X o con "Nueva venta") se va.
        if (!historial) this.cambioPendiente.set(false);
      });
    });
  }

  ngOnDestroy(): void {
    this.detenerTic();
  }

  ngOnInit(): void {
    this.http.get<Empleado>(`${environment.apiUrl}/empleados/yo`).subscribe({
      next: (empleado) => {
        this.cargandoSucursal.set(false);
        // Un administrador sin ficha de sucursal es alcance global, no un
        // error de configuración (ver organizacion.politicas.sucursal_asignada
        // en el backend) -- no puede cobrar sin elegir una sucursal, pero sí
        // puede ver cómo le está yendo a cada una.
        if (empleado.sucursal_id === null && this.esAdministrador()) {
          this.iniciarVistaAdministrador();
          return;
        }
        this.sucursalId.set(empleado.sucursal_id);
        if (empleado.sucursal_id === null) {
          this.messageService.add({
            severity: 'warn',
            summary: 'No tienes una sucursal asignada',
            detail: 'Pide a un administrador que te asigne una sucursal para poder cobrar.',
          });
        } else {
          // Se recuerda la sucursal para poder abrir Caja si la página se recarga sin red (E14b).
          this.recordarSucursal(empleado.sucursal_id);
          // #inputBusqueda recién existe en el DOM ahora: está detrás del
          // @if que depende de cargandoSucursal/sucursalId (ver el
          // template), así que enfocarlo desde ngAfterViewInit no sirve —
          // en ese momento todavía se está mostrando "Cargando...".
          this.enfocarBusqueda();
        }
      },
      error: (error: HttpErrorResponse) => {
        // Sin red (status 0) la sucursal recordada permite abrir Caja y vender sin conexión.
        if (error.status === 0 && !this.esAdministrador()) {
          void this.abrirConSucursalRecordada();
          return;
        }
        this.cargandoSucursal.set(false);
        if (this.esAdministrador()) {
          this.iniciarVistaAdministrador();
          return;
        }
        this.noEsEmpleado.set(true);
      },
    });
  }

  /** Anota la sucursal de caja para poder reabrir sin red. Es un extra: si falla, Caja sigue igual. */
  private recordarSucursal(sucursalId: number): void {
    try {
      void this.injector.get(SesionOfflineService).guardarSucursalDeCaja(sucursalId)?.catch(() => undefined);
    } catch {
      // Sin almacenamiento local no se recuerda nada: no afecta a la venta en línea.
    }
  }

  /** Reabre Caja sin red con la sucursal que se leyó la última vez con conexión; si no hay, es el aviso de siempre. */
  private async abrirConSucursalRecordada(): Promise<void> {
    let sucursal: number | null = null;
    try {
      sucursal = await this.injector.get(SesionOfflineService).sucursalDeCajaGuardada();
    } catch {
      sucursal = null;
    }
    this.cargandoSucursal.set(false);
    if (sucursal === null) {
      this.noEsEmpleado.set(true);
      return;
    }
    this.sucursalId.set(sucursal);
    this.enfocarBusqueda();
  }

  /** `/reportes/ventas` ya agrega por sucursal del lado del servidor (CU-22)
   * y con alcance global trae todas en una sola consulta -- nada de pedir
   * sucursal por sucursal y sumar aquí. */
  private cargarResumenGlobal(): void {
    this.vistaResumenGlobal.set(true);
    this.cargandoResumen.set(true);
    this.errorResumen.set(false);
    const hoy = fechaLocalIso(new Date());
    this.http
      .get<ReporteVentas>(`${environment.apiUrl}/reportes/ventas`, { params: { desde: hoy, hasta: hoy } })
      .subscribe({
        next: (reporte) => {
          this.cargandoResumen.set(false);
          this.resumenPorSucursal.set(reporte.por_sucursal);
        },
        error: () => {
          this.cargandoResumen.set(false);
          this.errorResumen.set(true);
        },
      });
  }

  /** "Reintentar" cuando el resumen del administrador no cargó. */
  protected reintentarResumen(): void {
    this.cargarResumenGlobal();
  }

  /**
   * El administrador no tiene sucursal propia (alcance global): elige en cuál cobrar y ve cómo va hoy cada una. El
   * servidor ya le permite vender en cualquier sucursal de su empresa.
   */
  private iniciarVistaAdministrador(): void {
    this.cargarResumenGlobal();
    this.cargandoSucursales.set(true);
    this.http.get<Sucursal[]>(`${environment.apiUrl}/sucursales`, { params: { pagina: 1, tamanio: 100 } }).subscribe({
      next: (sucursales) => {
        this.cargandoSucursales.set(false);
        this.sucursalesCaja.set(sucursales.filter((s) => s.activo && !s.es_deposito));
        const recordada = this.sucursalRecordadaDelAdministrador();
        if (recordada !== null && this.sucursalesCaja().some((s) => s.id === recordada)) {
          this.elegirSucursalCaja(recordada);
        }
      },
      error: () => this.cargandoSucursales.set(false),
    });
  }

  /** Cambia la sucursal en la que cobra el administrador. No se puede con una venta en curso. */
  protected elegirSucursalCaja(id: number | null): void {
    if (!this.vistaResumenGlobal() || this.fase() !== 'armando' || this.hayVentaEnCurso()) return;
    if (id !== null && !this.sucursalesCaja().some((s) => s.id === id)) return;
    this.sucursalId.set(id);
    this.recordarSucursalDelAdministrador(id);
    // Lo que se veía era de la sucursal anterior.
    this.textoBusqueda.set('');
    this.resultados.set([]);
    this.ventasRecientes.set([]);
    if (id !== null) this.enfocarBusqueda();
  }

  private sucursalRecordadaDelAdministrador(): number | null {
    try {
      const valor = Number(localStorage.getItem(CLAVE_SUCURSAL_ADMIN));
      return Number.isInteger(valor) && valor > 0 ? valor : null;
    } catch {
      return null;
    }
  }

  private recordarSucursalDelAdministrador(id: number | null): void {
    try {
      if (id === null) localStorage.removeItem(CLAVE_SUCURSAL_ADMIN);
      else localStorage.setItem(CLAVE_SUCURSAL_ADMIN, String(id));
    } catch {
      // Sin almacenamiento no se recuerda la elección: no afecta a la venta.
    }
  }

  private enfocarBusqueda(): void {
    setTimeout(() => this.inputBusqueda?.nativeElement.focus());
  }

  /** Atajos globales, sin necesitar el mouse (Revisar de P5.4): F2 salta al
   * código de reserva, F9 dispara el siguiente paso (cobrar o confirmar el
   * pago) según la fase. No pisan Enter/flechas de la búsqueda, que se
   * manejan aparte en onBusquedaKeydown porque ahí el foco ya está adentro
   * del input y necesitan preventDefault selectivo. */
  @HostListener('window:keydown', ['$event'])
  onAtajoGlobal(evento: KeyboardEvent): void {
    if (this.comprobanteVisible() || this.historialVisible() || this.devolucionVisible() || this.sinStockVisible()) {
      return;
    }
    if (evento.key === 'F2' && this.fase() === 'armando') {
      evento.preventDefault();
      this.inputReserva?.nativeElement.focus();
      return;
    }
    if (evento.key === 'F9') {
      evento.preventDefault();
      if (this.fase() === 'armando') {
        this.cobrar();
      } else {
        this.confirmarPago();
      }
    }
  }

  // ---- Búsqueda de producto -------------------------------------------------

  onBusquedaKeydown(evento: KeyboardEvent): void {
    if (evento.key === 'ArrowDown') {
      if (this.resultados().length > 0) {
        evento.preventDefault();
        this.indiceResaltado.set(Math.min(this.indiceResaltado() + 1, this.resultados().length - 1));
      }
      return;
    }
    if (evento.key === 'ArrowUp') {
      if (this.resultados().length > 0) {
        evento.preventDefault();
        this.indiceResaltado.set(Math.max(this.indiceResaltado() - 1, 0));
      }
      return;
    }
    if (evento.key === 'Escape') {
      this.limpiarBusqueda();
      return;
    }
    if (evento.key === 'Enter') {
      evento.preventDefault();
      if (this.resultados().length > 0) {
        this.agregarResultado(this.resultados()[this.indiceResaltado()]);
      } else if (this.textoBusqueda().trim().length > 0) {
        this.buscar();
      }
    }
  }

  private buscar(): void {
    const texto = this.textoBusqueda().trim();
    if (!texto) return;
    this.buscando.set(true);
    // Sin conexión (o sin servidor) no se intenta la red: se busca en lo descargado en este equipo (E14).
    if (this.conectividad.estado() !== 'en_linea') {
      void this.buscarLocal(texto);
      return;
    }
    this.busquedaLocal.set(false);
    this.http
      .get<VarianteBusqueda[]>(`${environment.apiUrl}/catalogo/variantes/buscar`, { params: { q: texto } })
      .subscribe({
        next: (resultados) => {
          this.buscando.set(false);
          this.mostrarResultados(resultados, texto);
        },
        error: (error: HttpErrorResponse) => {
          // Status 0: la red se cortó entre la última comprobación y esta petición.
          if (error.status === 0) {
            void this.buscarLocal(texto);
            return;
          }
          this.buscando.set(false);
        },
      });
  }

  private mostrarResultados(resultados: VarianteBusqueda[], texto: string): void {
    if (resultados.length === 0) {
      this.messageService.add({
        severity: 'warn',
        summary: 'Sin resultados',
        detail: this.busquedaLocal() ? `${texto} (en los datos descargados)` : texto,
      });
      return;
    }
    if (resultados.length === 1) {
      this.agregarResultado(resultados[0]);
      return;
    }
    this.resultados.set(resultados);
    this.indiceResaltado.set(0);
  }

  /** Busca en el catálogo descargado. El servicio se pide solo cuando hace falta: en línea no se toca el almacenamiento local. */
  private async buscarLocal(texto: string): Promise<void> {
    this.busquedaLocal.set(true);
    try {
      const resultados = await this.injector.get(CatalogoLocalService).buscarVariantes(texto);
      this.mostrarResultados(resultados, texto);
    } catch {
      this.messageService.add({
        severity: 'error',
        summary: 'No pudimos buscar sin conexión',
        detail: 'No se pudieron leer los datos descargados en este equipo. Conéctate para buscar en el servidor.',
      });
    } finally {
      this.buscando.set(false);
    }
  }

  seleccionarResultado(indice: number): void {
    this.indiceResaltado.set(indice);
    this.agregarResultado(this.resultados()[indice]);
  }

  private agregarResultado(variante: VarianteBusqueda): void {
    this.nombresVariante[variante.variante_id] =
      `${variante.producto_nombre} · ${variante.talla_codigo} · ${variante.color_nombre}`;
    // Solo el resultado de la búsqueda local trae el descuento descargado; en línea no existe y la línea no lo lleva.
    const descuentoLocal = (variante as Partial<VarianteBusquedaLocal>).descuento_unitario;
    this.lineas.update((lineas) => {
      const existente = lineas.find((l) => l.variante_id === variante.variante_id);
      if (existente) {
        return lineas.map((l) =>
          l.variante_id === variante.variante_id
            ? {
                ...l,
                cantidad: l.cantidad + 1,
                ...(descuentoLocal === undefined
                  ? {}
                  : { precio_efectivo: variante.precio_efectivo, descuento_unitario: descuentoLocal }),
              }
            : l,
        );
      }
      return [
        ...lineas,
        {
          variante_id: variante.variante_id,
          descripcion: `${variante.producto_nombre} · ${variante.talla_codigo} · ${variante.color_nombre}`,
          nombre: variante.producto_nombre,
          detalleVariante: `${variante.talla_codigo} · ${variante.color_nombre}`,
          sku: variante.sku,
          precio_efectivo: variante.precio_efectivo,
          ...(descuentoLocal === undefined ? {} : { descuento_unitario: descuentoLocal }),
          cantidad: 1,
        },
      ];
    });
    this.limpiarBusqueda();
  }

  limpiarBusqueda(): void {
    this.textoBusqueda.set('');
    this.resultados.set([]);
    this.busquedaLocal.set(false);
    this.indiceResaltado.set(0);
    this.enfocarBusqueda();
  }

  actualizarCantidad(varianteId: number, cantidad: number | null): void {
    if (cantidad === null || cantidad <= 0) {
      this.quitarLinea(varianteId);
      return;
    }
    this.lineas.update((lineas) => lineas.map((l) => (l.variante_id === varianteId ? { ...l, cantidad } : l)));
  }

  /** Cantidad escrita a mano en el carrito: se aplica al salir del campo o con Enter.
   * Vacía vuelve a la cantidad anterior; cero o negativa quita la línea (igual que
   * antes del rediseño); los decimales se truncan. */
  fijarCantidad(varianteId: number, evento: Event): void {
    const campo = evento.target as HTMLInputElement;
    if (campo.value.trim() === '') {
      const actual = this.lineas().find((l) => l.variante_id === varianteId);
      campo.value = String(actual?.cantidad ?? 1);
      return;
    }
    const cantidad = Math.trunc(Number(campo.value));
    if (Number.isNaN(cantidad)) {
      return;
    }
    this.actualizarCantidad(varianteId, cantidad);
    campo.value = String(this.lineas().find((l) => l.variante_id === varianteId)?.cantidad ?? cantidad);
  }

  quitarLinea(varianteId: number): void {
    this.lineas.update((lineas) => lineas.filter((l) => l.variante_id !== varianteId));
    this.enfocarBusqueda();
  }

  // ---- Reserva atendida -> venta -----------------------------------------------

  cargarReserva(): void {
    const codigo = this.codigoReserva().trim();
    const sucursalId = this.sucursalId();
    if (!codigo || sucursalId === null || this.sinConexion()) return;
    this.buscandoReserva.set(true);
    this.http.get<Reserva[]>(`${environment.apiUrl}/reservas/sucursal/${sucursalId}`).subscribe({
      next: (reservas) => {
        this.buscandoReserva.set(false);
        const reserva = reservas.find((r) => r.codigo.toLowerCase() === codigo.toLowerCase());
        if (!reserva) {
          this.messageService.add({ severity: 'warn', summary: 'Reserva no encontrada', detail: codigo });
          return;
        }
        if (reserva.estado !== 'completada') {
          this.messageService.add({
            severity: 'warn',
            summary: 'Esa reserva todavía no está atendida',
            detail: `Estado actual: ${reserva.estado}`,
          });
          return;
        }
        this.lineas.set([]);
        this.reservaCargada.set(reserva);
        this.codigoReserva.set('');
        this.messageService.add({ severity: 'success', summary: 'Reserva cargada', detail: reserva.codigo });
        this.enfocarBusqueda();
      },
      error: () => this.buscandoReserva.set(false),
    });
  }

  quitarReserva(): void {
    this.reservaCargada.set(null);
    this.enfocarBusqueda();
  }

  // ---- Paso 1: cobrar (crea la venta, con total real de la promoción vigente) ---

  cobrar(): void {
    const sucursalId = this.sucursalId();
    if (sucursalId === null || this.fase() !== 'armando') return;
    if (!this.hayVentaEnCurso()) {
      this.messageService.add({ severity: 'warn', summary: 'El carrito está vacío' });
      return;
    }
    // Sin conexión no se crea la venta en el servidor: se cobra en efectivo y se guarda en este equipo (E14b).
    if (this.sinConexion()) {
      // El administrador elige sucursal solo en línea: el modo sin conexión es del cajero de su sucursal.
      if (this.vistaResumenGlobal()) {
        this.messageService.add({
          severity: 'warn',
          summary: 'Sin conexión',
          detail: 'El administrador solo puede cobrar con conexión. Espera a que vuelva Internet.',
        });
        return;
      }
      void this.abrirCobroOffline();
      return;
    }

    const payload: VentaPresencialCrear = this.reservaCargada()
      ? { sucursal_id: sucursalId, reserva_id: this.reservaCargada()!.id }
      : {
          sucursal_id: sucursalId,
          detalle: this.lineas().map((l) => ({ variante_id: l.variante_id, cantidad: l.cantidad })),
        };

    this.registrandoVenta.set(true);
    this.http.post<Venta>(`${environment.apiUrl}/ventas/presencial`, payload).subscribe({
      next: (venta) => {
        this.registrandoVenta.set(false);
        this.ventaPendiente.set(venta);
        this.fase.set('cobrando');
        this.metodoPago.set('efectivo');
        this.montoRecibido.set(null);
        setTimeout(() => this.inputMontoRecibido?.nativeElement.focus());
      },
      error: () => this.registrandoVenta.set(false),
    });
  }

  /** Grupo de opciones: las flechas mueven la selección entre los métodos de pago. */
  onMetodoKeydown(evento: KeyboardEvent, indice: number): void {
    const salto = ['ArrowRight', 'ArrowDown'].includes(evento.key) ? 1 : ['ArrowLeft', 'ArrowUp'].includes(evento.key) ? -1 : 0;
    // Sin conexión solo existe el efectivo: las flechas no tienen a dónde mover la selección.
    if (salto === 0 || this.cobroOffline() !== null) return;
    evento.preventDefault();
    const total = this.opcionesMetodoPago.length;
    const siguiente = (indice + salto + total) % total;
    this.metodoPago.set(this.opcionesMetodoPago[siguiente].value);
    const botones = (evento.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLElement>('[role="radio"]');
    botones?.[siguiente]?.focus();
  }

  seleccionarMetodoPago(metodo: MetodoPagoCaja): void {
    if (this.cobroOffline() !== null && metodo !== 'efectivo') return;
    this.metodoPago.set(metodo);
    if (metodo === 'efectivo') {
      setTimeout(() => this.inputMontoRecibido?.nativeElement.focus());
    }
  }

  // ---- Paso 2: confirmar el pago -------------------------------------------------

  confirmarPago(): void {
    if (this.cobroOffline() !== null) {
      void this.confirmarPagoOffline();
      return;
    }
    const venta = this.ventaPendiente();
    if (!venta || this.fase() !== 'cobrando') return;
    if (this.metodoPago() === 'efectivo' && (this.montoRecibido() === null || this.montoRecibido()! < venta.total)) {
      this.messageService.add({ severity: 'warn', summary: 'El monto recibido no cubre el total' });
      return;
    }

    const payload: PagoCajaRequest = {
      venta_id: venta.id,
      metodo_pago: this.metodoPago(),
      monto_recibido: this.metodoPago() === 'efectivo' ? this.montoRecibido() : null,
    };
    this.registrandoPago.set(true);
    this.http.post<PagoCajaRespuesta>(`${environment.apiUrl}/pagos/caja`, payload).subscribe({
      next: (respuesta) => {
        this.registrandoPago.set(false);
        this.ventaConfirmada.set(venta);
        this.pagoConfirmado.set(respuesta.pago);
        this.cambioConfirmado.set(respuesta.cambio);
        this.comprobanteVisible.set(true);
      },
      error: () => this.registrandoPago.set(false),
    });
  }

  imprimirComprobante(): void {
    window.print();
  }

  nuevaVenta(): void {
    this.comprobanteVisible.set(false);
    this.fase.set('armando');
    this.lineas.set([]);
    this.reservaCargada.set(null);
    this.ventaPendiente.set(null);
    this.montoRecibido.set(null);
    this.metodoPago.set('efectivo');
    this.ventaConfirmada.set(null);
    this.pagoConfirmado.set(null);
    this.cambioConfirmado.set(null);
    this.comprobanteOffline.set(null);
    this.cobroOffline.set(null);
    this.avisoOffline.set(null);
    this.enfocarBusqueda();
  }

  // ---- Venta sin conexión (E14b) -------------------------------------------------------------

  /** Abre el cobro sin conexión: refresca las líneas con lo descargado (para que el total mostrado sea el que se guarda) y crea el identificador de la operación UNA vez. */
  private async abrirCobroOffline(): Promise<void> {
    if (this.registrandoVenta() || this.fase() !== 'armando') return;
    if (this.reservaCargada() !== null) {
      this.avisoOffline.set('Una reserva atendida solo se cobra con conexión. Quita la reserva o espera a tener Internet.');
      return;
    }
    this.avisoOffline.set(null);
    this.registrandoVenta.set(true);
    try {
      await this.actualizarLineasConDatosLocales();
      this.cobroOffline.set({
        operacionId: this.injector.get(OperacionesOfflineService).nuevoOperacionId(),
        aceptarSinStock: false,
      });
      this.fase.set('cobrando');
      this.metodoPago.set('efectivo');
      this.montoRecibido.set(null);
      setTimeout(() => this.inputMontoRecibido?.nativeElement.focus());
    } catch (error) {
      this.avisoOffline.set(
        error instanceof ErrorOperacionOffline
          ? error.message
          : 'No pudimos leer los datos descargados en este equipo. Inténtalo de nuevo o conéctate a Internet.',
      );
    } finally {
      this.registrandoVenta.set(false);
    }
  }

  /** Pone en cada línea el precio y el descuento DESCARGADOS: son los que usará la venta guardada. */
  private async actualizarLineasConDatosLocales(): Promise<void> {
    const catalogo = this.injector.get(CatalogoLocalService);
    const locales = new Map<number, VarianteBusquedaLocal>();
    for (const linea of this.lineas()) {
      const local = (await catalogo.buscarVariantes(linea.sku)).find((v) => v.variante_id === linea.variante_id);
      if (!local) {
        throw new ErrorOperacionOffline(
          `${linea.descripcion} no está en los datos descargados en este equipo. Quítala del carrito o conéctate a Internet.`,
        );
      }
      locales.set(linea.variante_id, local);
    }
    this.lineas.update((lineas) =>
      lineas.map((l) => {
        const local = locales.get(l.variante_id);
        return local ? { ...l, precio_efectivo: local.precio_efectivo, descuento_unitario: local.descuento_unitario } : l;
      }),
    );
  }

  /** Vuelve del cobro sin conexión al carrito (no hay nada guardado: la venta todavía no existe). */
  cancelarCobroOffline(): void {
    if (this.guardandoOffline()) return;
    this.cobroOffline.set(null);
    this.fase.set('armando');
    this.montoRecibido.set(null);
    this.avisoOffline.set(null);
    this.enfocarBusqueda();
  }

  /** Confirma el cobro sin conexión: guarda la venta en este equipo. Un doble clic no la duplica (guarda + mismo identificador). */
  private async confirmarPagoOffline(): Promise<void> {
    const cobro = this.cobroOffline();
    const sucursalId = this.sucursalId();
    if (cobro === null || sucursalId === null || this.guardandoOffline() || this.fase() !== 'cobrando') return;
    const recibido = this.montoRecibido();
    if (recibido === null || !(aCentavos(recibido) >= this.totalLocal().total)) {
      this.messageService.add({ severity: 'warn', summary: 'El monto recibido no cubre el total' });
      return;
    }

    this.guardandoOffline.set(true);
    this.avisoOffline.set(null);
    try {
      const operacion = await this.injector.get(OperacionesOfflineService).registrarVenta({
        sucursalId,
        lineas: this.lineas().map((l) => ({ varianteId: l.variante_id, cantidad: l.cantidad })),
        montoRecibido: recibido,
        operacionId: cobro.operacionId,
        aceptarSinStock: cobro.aceptarSinStock,
      });
      this.terminarVentaOffline(operacion);
    } catch (error) {
      if (error instanceof StockLocalInsuficienteError) {
        this.faltantesLocales.set(error.faltantes);
        this.sinStockVisible.set(true);
      } else if (error instanceof ErrorOperacionOffline) {
        this.avisoOffline.set(error.message);
      } else {
        this.avisoOffline.set('No se pudo registrar la venta en este equipo. NO se guardó: inténtalo de nuevo.');
      }
    } finally {
      this.guardandoOffline.set(false);
    }
  }

  /** La venta ya está guardada: vacía el carrito, muestra el comprobante local y avisa a la cola de envío. */
  private terminarVentaOffline(operacion: OperacionOffline): void {
    this.cobroOffline.set(null);
    this.sinStockVisible.set(false);
    this.faltantesLocales.set([]);
    this.fase.set('armando');
    this.lineas.set([]);
    this.montoRecibido.set(null);
    this.metodoPago.set('efectivo');
    this.comprobanteOffline.set(operacion);
    this.comprobanteVisible.set(true);
    // La operación YA está guardada: un fallo de la cola de envío no debe presentarse como "no se registró".
    try {
      const cola = this.injector.get(ColaSincronizacionService);
      cola.notificarNuevaOperacion();
      void cola.refrescarConteos().catch(() => undefined);
    } catch {
      // La cola reintenta sola al volver la red; no hay nada que decirle al cajero.
    }
  }

  /** "Registrar de todos modos": el cajero vio el aviso de stock local; se repite el guardado con el MISMO identificador. */
  aceptarSinStock(): void {
    const cobro = this.cobroOffline();
    if (cobro === null || this.guardandoOffline()) return;
    this.cobroOffline.set({ ...cobro, aceptarSinStock: true });
    this.sinStockVisible.set(false);
    void this.confirmarPagoOffline();
  }

  /** Cancela el aviso: no se guarda nada y el cobro sigue abierto. */
  cancelarSinStock(): void {
    this.sinStockVisible.set(false);
    this.faltantesLocales.set([]);
  }

  protected descripcionFaltante(faltante: FaltanteLocal): string {
    return [faltante.producto_nombre, faltante.talla, faltante.color].filter((p) => !!p).join(' · ');
  }

  /** Subtotal de una venta guardada, antes del descuento (cantidad x precio unitario, en centavos exactos). */
  protected subtotalGuardado(operacion: OperacionOffline): number {
    return operacion.lineas.reduce((suma, l) => suma + l.cantidad * aCentavos(l.precio_unitario), 0) / 100;
  }

  /** Descuento total de una venta guardada (cantidad x descuento unitario, en centavos exactos). */
  protected descuentoGuardado(operacion: OperacionOffline): number {
    return operacion.lineas.reduce((suma, l) => suma + l.cantidad * aCentavos(l.descuento_unitario), 0) / 100;
  }

  // ---- Historial de ventas de hoy -----------------------------------------------

  abrirHistorial(): void {
    const sucursalId = this.sucursalId();
    if (sucursalId === null || this.sinConexion()) return;
    this.historialVisible.set(true);
    this.cargandoHistorial.set(true);
    this.plazos.set({});
    this.vencimientoConfirmado.clear();
    this.http.get<Venta[]>(`${environment.apiUrl}/ventas/sucursal/${sucursalId}`).subscribe({
      next: (ventas) => {
        // `venta.fecha` viene del backend sin offset: comparar contra toISOString() (UTC) desalinea la fecha cerca de
        // medianoche. Se compara por DÍA calendario local, con un día de margen: el plazo exacto lo decide el servidor
        // (el indicador de cada fila) y la fila vencida solo desactiva su botón.
        const desde = fechaLocalIso(new Date(Date.now() - DIAS_VENTAS_RECIENTES * 24 * 3_600_000));
        const recientes = ventas.filter((v) => v.fecha.slice(0, 10) >= desde).sort((a, b) => b.id - a.id);
        this.ventasRecientes.set(recientes);
        this.busquedaHistorial.set('');
        this.cargandoHistorial.set(false);
        // Solo las ventas que ofrecen devolución necesitan su plazo; las más recientes primero.
        recientes
          .filter((v) => this.permiteDevolucion(v))
          .slice(0, MAX_PLAZOS_PARALELOS)
          .forEach((v) => this.pedirPlazo(v.id));
      },
      error: () => this.cargandoHistorial.set(false),
    });
  }

  /** Solo una venta pagada o entregada ofrece el botón "Devolución". */
  protected permiteDevolucion(venta: Venta): boolean {
    return venta.estado === 'pagada' || venta.estado === 'entregada';
  }

  // ---- Plazo para devolver o cambiar ---------------------------------------------

  /** Lo que se dice del plazo de una venta; null si no se conoce (consulta pendiente, fallida o fuera del tope). */
  protected indicadorPlazo(ventaId: number): IndicadorPlazo | null {
    const plazo = this.plazos()[ventaId];
    if (!plazo) return null;
    const ahora = this.ahora();
    // La cuenta solo "llega a cero" si al recibirla todavía faltaba tiempo: si el reloj de este equipo va
    // adelantado y el servidor sigue diciendo "vigente", manda el servidor.
    const cuentaTerminada = plazo.venceMs > plazo.obtenidoMs && ahora >= plazo.venceMs;
    if (!plazo.vigente || cuentaTerminada) {
      const horas = plazo.plazoHoras;
      return {
        vencido: true,
        texto: horas === null ? 'Pasó el plazo para devolver o cambiar' : `Pasó el plazo de ${textoHoras(horas)}`,
        titulo:
          horas === null
            ? 'Pasó el plazo para devolver o cambiar'
            : `Pasó el plazo de ${textoHoras(horas)} para devolver o cambiar`,
      };
    }
    const texto = `Quedan ${textoRestante(plazo.venceMs - ahora)} para devolver o cambiar`;
    return { vencido: false, texto, titulo: texto };
  }

  /** Pide el plazo de una venta. Un fallo no muestra aviso ni bloquea nada: el servidor decide al confirmar. */
  private pedirPlazo(ventaId: number, forzarVencido = false): void {
    if (this.sinConexion()) return;
    const secuencia = (this.secuenciaPlazo.get(ventaId) ?? 0) + 1;
    this.secuenciaPlazo.set(ventaId, secuencia);
    this.http
      .get<PlazoCambio>(`${environment.apiUrl}/ventas/${ventaId}/plazo-cambio`, {
        context: new HttpContext().set(SIN_TOAST_ERROR, true),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (respuesta) => {
          if (this.secuenciaPlazo.get(ventaId) !== secuencia) return;
          this.guardarPlazo(respuesta, forzarVencido);
        },
        error: () => undefined,
      });
  }

  private guardarPlazo(respuesta: PlazoCambio, forzarVencido: boolean): void {
    const venceMs = Date.parse(respuesta.vence_en);
    if (Number.isNaN(venceMs) || typeof respuesta.vigente !== 'boolean') return;
    const ahora = Date.now();
    this.vencimientoConfirmado.delete(respuesta.venta_id);
    this.ahora.set(ahora);
    this.plazos.update((actuales) => ({
      ...actuales,
      [respuesta.venta_id]: {
        plazoHoras: respuesta.plazo_horas,
        venceMs,
        vigente: respuesta.vigente && !forzarVencido,
        obtenidoMs: ahora,
      },
    }));
  }

  /** El servidor rechazó por plazo (409): la venta queda vencida aunque aún no llegue la consulta nueva. */
  private marcarPlazoVencido(ventaId: number): void {
    const ahora = Date.now();
    // Subir la secuencia descarta las consultas anteriores que sigan en camino.
    this.secuenciaPlazo.set(ventaId, (this.secuenciaPlazo.get(ventaId) ?? 0) + 1);
    this.ahora.set(ahora);
    this.plazos.update((actuales) => ({
      ...actuales,
      [ventaId]: { ...(actuales[ventaId] ?? { plazoHoras: null, venceMs: ahora, obtenidoMs: ahora }), vigente: false },
    }));
  }

  private detenerTic(): void {
    if (this.temporizadorPlazo !== null) {
      clearTimeout(this.temporizadorPlazo);
      this.temporizadorPlazo = null;
    }
  }

  /** Programa el próximo tic: como mucho en un minuto, o antes si un plazo vence antes (así el botón se apaga a tiempo). */
  private programarTic(): void {
    this.detenerTic();
    if (!this.historialVisible() && !this.devolucionVisible()) return;
    const ahora = Date.now();
    const faltantes = Object.values(this.plazos())
      .filter((p) => p.vigente && p.venceMs > ahora)
      .map((p) => p.venceMs - ahora);
    if (faltantes.length === 0) return;
    const espera = Math.min(INTERVALO_PLAZO_MS, Math.max(100, Math.min(...faltantes) + 100));
    this.temporizadorPlazo = setTimeout(() => this.alPasarElTiempo(), espera);
  }

  private alPasarElTiempo(): void {
    this.temporizadorPlazo = null;
    const ahora = Date.now();
    this.ahora.set(ahora);
    // Una cuenta que llegó a cero se confirma con el servidor (una sola vez por consulta recibida).
    for (const [id, plazo] of Object.entries(this.plazos())) {
      const ventaId = Number(id);
      if (plazo.vigente && plazo.venceMs > plazo.obtenidoMs && ahora >= plazo.venceMs && !this.vencimientoConfirmado.has(ventaId)) {
        this.vencimientoConfirmado.add(ventaId);
        this.pedirPlazo(ventaId);
      }
    }
    this.programarTic();
  }

  // ---- Devoluciones --------------------------------------------------------------

  abrirDevolucion(venta: Venta): void {
    if (this.sinConexion()) return;
    this.ventaParaDevolucion.set(venta);
    this.cantidadesDevolucion.set(Object.fromEntries(venta.detalle.map((d) => [d.id, 0])));
    this.cambiosElegidos.set({});
    this.opcionesCambio.set({});
    this.errorDevolucion.set(null);
    this.devolucionVisible.set(true);
    // El dato fresco manda: el de la fila pudo quedar viejo mientras el cajero atendía.
    this.pedirPlazo(venta.id);
    this.cargarOpcionesCambio(venta);
  }

  actualizarCantidadDevolucion(detalleId: number, cantidad: number | null): void {
    this.cantidadesDevolucion.update((actual) => ({ ...actual, [detalleId]: cantidad ?? 0 }));
  }

  elegirCambio(detalleId: number, varianteNuevaId: number | null): void {
    this.cambiosElegidos.update((actual) => ({ ...actual, [detalleId]: varianteNuevaId }));
  }

  /**
   * Las tallas y colores por los que se puede cambiar cada línea: las demás variantes del MISMO producto y del MISMO
   * precio (lo que el servidor exige), con su stock en la sucursal de la venta. También deja a la vista el nombre
   * real de cada prenda. Si algo falla, la devolución simple sigue disponible.
   */
  private cargarOpcionesCambio(venta: Venta): void {
    this.errorOpcionesCambio.set(false);
    this.cargandoOpcionesCambio.set(true);
    const url = `${environment.apiUrl}/catalogo`;
    const idsVenta = [...new Set(venta.detalle.map((d) => d.variante_id))];
    this.http
      .get<ProductoImagenLookupItem[]>(`${url}/variantes/detalle`, { params: { variante_ids: idsVenta.join(',') } })
      .pipe(
        switchMap((propias) => {
          const productos = [...new Set(propias.map((p) => p.producto_id))];
          const detalles$ = productos.length
            ? forkJoin(
                productos.map((id) =>
                  this.http.get<CatalogoDetalle>(`${url}/${id}`, { params: { sucursal_id: venta.sucursal_id } }),
                ),
              )
            : of([] as CatalogoDetalle[]);
          return detalles$.pipe(map((detalles) => ({ propias, detalles })));
        }),
        switchMap(({ propias, detalles }) => {
          const hermanas = [...new Set(detalles.flatMap((d) => d.variantes.map((v) => v.id)))];
          const nombres$ = hermanas.length
            ? this.http.get<ProductoImagenLookupItem[]>(`${url}/variantes/detalle`, {
                params: { variante_ids: hermanas.join(',') },
              })
            : of([] as ProductoImagenLookupItem[]);
          return nombres$.pipe(map((nombres) => ({ propias, detalles, nombres })));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: ({ propias, detalles, nombres }) => {
          for (const p of propias) {
            if (p.variante_id != null) {
              this.nombresVariante[p.variante_id] = `${p.producto_nombre} · ${p.talla_codigo ?? ''} · ${p.color_nombre ?? ''}`;
            }
          }
          const etiquetas = new Map(nombres.map((n) => [n.variante_id, `${n.talla_codigo ?? ''} · ${n.color_nombre ?? ''}`]));
          const porLinea: Record<number, OpcionCambio[]> = {};
          for (const linea of venta.detalle) {
            const propia = propias.find((p) => p.variante_id === linea.variante_id);
            const producto = detalles.find((d) => d.id === propia?.producto_id);
            const original = producto?.variantes.find((v) => v.id === linea.variante_id);
            if (!producto || !original) continue;
            porLinea[linea.id] = producto.variantes
              .filter((v) => v.id !== original.id && Number(v.precio_efectivo) === Number(original.precio_efectivo))
              .map((v) => ({
                variante_id: v.id,
                etiqueta: etiquetas.get(v.id) ?? v.sku,
                disponible: v.cantidad_disponible ?? 0,
              }));
          }
          this.opcionesCambio.set(porLinea);
          this.cargandoOpcionesCambio.set(false);
        },
        error: () => {
          this.cargandoOpcionesCambio.set(false);
          this.errorOpcionesCambio.set(true);
        },
      });
  }

  confirmarDevolucion(): void {
    const venta = this.ventaParaDevolucion();
    if (!venta || this.sinConexion()) return;
    const elegidos = this.cambiosElegidos();
    const detalle = Object.entries(this.cantidadesDevolucion())
      .filter(([, cantidad]) => cantidad > 0)
      .map(([id, cantidad]) => {
        const nueva = elegidos[Number(id)];
        return { venta_detalle_id: Number(id), cantidad, ...(nueva ? { variante_nueva_id: nueva } : {}) };
      });
    if (detalle.length === 0) {
      this.messageService.add({ severity: 'warn', summary: 'Indica al menos una cantidad a devolver' });
      return;
    }
    const payload: DevolucionCrear = { venta_id: venta.id, detalle };
    this.registrandoDevolucion.set(true);
    this.errorDevolucion.set(null);
    this.http.post<Devolucion>(`${environment.apiUrl}/devoluciones`, payload).subscribe({
      next: (respuesta) => {
        this.registrandoDevolucion.set(false);
        this.devolucionVisible.set(false);
        if ((respuesta?.reposiciones ?? []).length > 0) {
          // Un cambio de talla o color ya está completo: la talla devuelta volvió al stock y la nueva salió.
          this.messageService.add({
            severity: 'success',
            summary: 'Cambio registrado',
            detail: respuesta.correo_programado
              ? 'Entrega la prenda nueva. Se envió el comprobante al correo del cliente.'
              : 'Entrega la prenda nueva. El cliente no tiene correo: no se envió comprobante.',
          });
        } else {
          this.messageService.add({ severity: 'success', summary: 'Devolución registrada' });
          // Un cambio de OTRA prenda es esta devolución más una venta nueva: el historial dice el paso siguiente.
          this.cambioPendiente.set(true);
        }
        this.abrirHistorial();
      },
      error: (error: HttpErrorResponse) => {
        this.registrandoDevolucion.set(false);
        if (error.status !== 409) return;
        // 409: el servidor rechazó la devolución (p. ej. venció el plazo con el diálogo abierto). Su mensaje se ve aquí.
        const mensaje = mensajeDeConflicto(error);
        this.errorDevolucion.set(mensaje);
        const porPlazo = /plazo/i.test(mensaje);
        if (porPlazo) this.marcarPlazoVencido(venta.id);
        this.pedirPlazo(venta.id, porPlazo);
      },
    });
  }

  /** "Nueva venta" tras una devolución: cierra los diálogos y deja el formulario de venta listo con foco en la búsqueda. */
  irANuevaVenta(): void {
    this.devolucionVisible.set(false);
    this.historialVisible.set(false);
    this.cambioPendiente.set(false);
    // Una venta a medias (carrito armado o cobro en curso) no se borra: solo se vuelve a ella.
    if (this.fase() === 'armando' && !this.hayVentaEnCurso()) {
      this.nuevaVenta();
    } else {
      this.enfocarBusqueda();
    }
  }
}

function redondear(valor: number): number {
  return Math.round(valor * 100) / 100;
}

/** "24 horas" / "1 hora": las horas reales del plazo que dijo el servidor. */
function textoHoras(horas: number): string {
  return `${horas} ${horas === 1 ? 'hora' : 'horas'}`;
}

/** Tiempo que falta, en horas y minutos enteros ("5 h 12 min"); menos de un minuto se dice como tal. */
function textoRestante(milisegundos: number): string {
  const minutos = Math.floor(milisegundos / 60_000);
  if (minutos < 1) return 'menos de 1 min';
  const horas = Math.floor(minutos / 60);
  const resto = minutos % 60;
  if (horas === 0) return `${resto} min`;
  return resto === 0 ? `${horas} h` : `${horas} h ${resto} min`;
}

/** El texto con que el servidor explicó el 409 (`detail` en texto, o `detail.mensaje` / `mensaje`). */
function mensajeDeConflicto(error: HttpErrorResponse): string {
  const detalle = error.error?.detail;
  if (typeof detalle === 'string' && detalle.trim()) return detalle;
  if (typeof detalle?.mensaje === 'string' && detalle.mensaje.trim()) return detalle.mensaje;
  if (typeof error.error?.mensaje === 'string' && error.error.mensaje.trim()) return error.error.mensaje;
  return 'El servidor no aceptó la devolución. Revisa la venta e inténtalo de nuevo.';
}
