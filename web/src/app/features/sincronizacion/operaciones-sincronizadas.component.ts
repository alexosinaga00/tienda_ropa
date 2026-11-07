import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { DatePickerModule } from 'primeng/datepicker';
import { DialogModule } from 'primeng/dialog';
import { SelectModule } from 'primeng/select';
import { TableLazyLoadEvent, TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { AuthService } from '../../core/auth.service';
import { fechaLocalIso, instanteServidor } from '../../core/date-utils';
import { codigoFuncional } from '../../core/errores-funcionales';
import { mensajeFuncional } from '../../core/mensajes-error-funcional';
import { ProductoImagenLookupItem } from '../../core/models/catalogo.models';
import { Sucursal } from '../../core/models/organizacion.models';
import { Usuario } from '../../core/models/seguridad.models';
import {
  AccionResolucionSync,
  ConsultaOperacionesSync,
  EstadoOperacionSync,
  LineaPayloadSync,
  OperacionSync,
  OperacionSyncDetalle,
  ResolucionConflictoSync,
  TipoOperacionSync,
} from '../../core/models/sincronizacion.models';
import { aCentavos, centavosATexto } from '../../core/offline/dinero-offline';
import { IconoComponent } from '../../shared/icono/icono.component';
import {
  TEXTO_MOTIVO,
  VISTA_ESTADO,
  VistaEstado,
  formatoBs,
  plural,
} from '../operaciones-pendientes/textos-operacion';
import { SincronizacionAdminService } from './data/sincronizacion-admin.service';

/** Filas por página (el servidor pagina). */
export const TAMANIO_PAGINA = 20;
/** Una operación que llegó con más de esta demora se marca "llegó con N h de retraso". */
export const UMBRAL_RETRASO_MS = 60 * 60 * 1000;
/** Forzar es lo más delicado (ajusta el inventario): el motivo debe decir algo. */
export const MOTIVO_MINIMO_FORZAR = 10;
/** El servidor admite hasta 300 caracteres. */
export const MOTIVO_MAXIMO = 300;

const MS_POR_HORA = 60 * 60 * 1000;

/** Cómo se ve cada estado que guarda el servidor: texto, ícono y color (nunca solo color). */
const VISTA_ESTADO_SYNC: Record<string, VistaEstado> = {
  confirmada: { texto: 'Confirmada', icono: 'check', severidad: 'success' },
  rechazada: { texto: 'Rechazada', icono: 'cerrar', severidad: 'danger' },
  en_conflicto: { texto: 'En conflicto', icono: 'advertencia', severidad: 'warn' },
};

export function vistaEstadoSync(estado: string): VistaEstado {
  // registrada / enviada solo existen en el dispositivo (gris); si llegara otro, también se muestra gris.
  return (
    VISTA_ESTADO_SYNC[estado] ??
    (VISTA_ESTADO as Record<string, VistaEstado>)[estado] ?? { texto: estado, icono: 'reloj', severidad: 'secondary' }
  );
}

export const ETIQUETA_TIPO_SYNC: Record<string, string> = {
  venta_contado: 'Venta de contado',
  reserva: 'Reserva',
};

/**
 * Horas que tardó en llegar al servidor lo que pasó en el dispositivo, solo si superó 1 hora (si no, `null`).
 * Es la diferencia entre "recibida" y la fecha real de la operación.
 */
export function horasDeRetraso(recibidaEn: string, fechaOperacion: string): number | null {
  const diferencia = instanteServidor(recibidaEn).getTime() - instanteServidor(fechaOperacion).getTime();
  if (!Number.isFinite(diferencia) || diferencia <= UMBRAL_RETRASO_MS) return null;
  return Math.max(1, Math.round(diferencia / MS_POR_HORA));
}

/** El mensaje del servidor, o uno claro si no vino ninguno. */
function textoDeError(error: HttpErrorResponse): string {
  const funcional = mensajeFuncional(codigoFuncional(error), error.error, null);
  if (funcional) return funcional.detalle;
  const detalle = error.error?.detail;
  if (typeof detalle === 'string') return detalle;
  if (Array.isArray(detalle)) return detalle.map((d: { msg?: string }) => d.msg ?? String(d)).join(' · ');
  if (detalle && typeof detalle === 'object' && typeof detalle.mensaje === 'string') return detalle.mensaje;
  if (error.status === 0) return 'No se pudo conectar con el servidor. Revisa tu conexión.';
  return 'No se pudo completar la acción. Inténtalo de nuevo.';
}

interface OpcionUsuario {
  id: number;
  etiqueta: string;
}

/**
 * Operaciones sincronizadas (E16, plan 4.6): lo que la PWA y la app enviaron desde sus dispositivos, tal como lo guardó
 * el servidor, para TODA la empresa (o la sucursal propia). Quien tiene `sincronizacion.resolver` decide los conflictos de
 * stock: forzar (ajusta el inventario por lo que faltó y confirma la venta) o rechazar. Nada se puede borrar.
 */
@Component({
  selector: 'app-operaciones-sincronizadas',
  standalone: true,
  imports: [DatePipe, FormsModule, DatePickerModule, DialogModule, SelectModule, TableModule, TagModule, IconoComponent],
  templateUrl: './operaciones-sincronizadas.component.html',
  styleUrl: './operaciones-sincronizadas.component.scss',
})
export class OperacionesSincronizadasComponent implements OnInit {
  private readonly servicio = inject(SincronizacionAdminService);
  private readonly auth = inject(AuthService);
  private readonly messageService = inject(MessageService);

  protected readonly tamanioPagina = TAMANIO_PAGINA;
  protected readonly motivoMinimoForzar = MOTIVO_MINIMO_FORZAR;
  protected readonly motivoMaximo = MOTIVO_MAXIMO;
  protected readonly bs = formatoBs;
  protected readonly vistaEstado = vistaEstadoSync;
  protected readonly etiquetaTipo = (tipo: string): string => ETIQUETA_TIPO_SYNC[tipo] ?? tipo;
  protected readonly horasDeRetraso = horasDeRetraso;

  protected readonly opcionesEstado: { label: string; value: EstadoOperacionSync | null }[] = [
    { label: 'Todos los estados', value: null },
    { label: 'Confirmada', value: 'confirmada' },
    { label: 'Rechazada', value: 'rechazada' },
    { label: 'En conflicto', value: 'en_conflicto' },
  ];
  protected readonly opcionesTipo: { label: string; value: TipoOperacionSync | null }[] = [
    { label: 'Ventas y reservas', value: null },
    { label: 'Ventas de contado', value: 'venta_contado' },
    { label: 'Reservas', value: 'reserva' },
  ];

  /** Solo quien decide los conflictos ve [Forzar] y [Rechazar]; el servidor lo vuelve a exigir. */
  protected readonly puedeResolver = computed(() => this.auth.tienePermiso('sincronizacion.resolver'));

  // ---- Filtros ------------------------------------------------------------------------------------------------------
  protected readonly filtroEstado = signal<EstadoOperacionSync | null>(null);
  protected readonly filtroTipo = signal<TipoOperacionSync | null>(null);
  protected readonly filtroSucursal = signal<number | null>(null);
  protected readonly filtroUsuario = signal<number | null>(null);
  protected readonly filtroRango = signal<(Date | null)[] | null>(null);
  protected readonly hayFiltros = computed(
    () =>
      this.filtroEstado() !== null ||
      this.filtroTipo() !== null ||
      this.filtroSucursal() !== null ||
      this.filtroUsuario() !== null ||
      this.filtroRango() !== null,
  );

  // ---- Datos ----------------------------------------------------------------------------------------------------------
  protected readonly operaciones = signal<OperacionSync[]>([]);
  protected readonly total = signal(0);
  protected readonly pagina = signal(1);
  protected readonly cargando = signal(true);
  protected readonly errorLista = signal(false);
  protected readonly primero = computed(() => (this.pagina() - 1) * TAMANIO_PAGINA);
  /** Cuántas esperan una decisión (de todo el alcance, sin los filtros de la tabla). */
  protected readonly conflictos = signal(0);
  protected readonly textoConflictos = computed(() => `${plural(this.conflictos(), 'conflicto', 'conflictos')} por resolver`);

  protected readonly sucursales = signal<Sucursal[]>([]);
  protected readonly usuarios = signal<Usuario[]>([]);
  protected readonly opcionesUsuario = computed<OpcionUsuario[]>(() =>
    this.usuarios().map((u) => ({ id: u.id, etiqueta: `${u.nombre} ${u.apellido}`.trim() })),
  );
  private readonly variantes = signal<ReadonlyMap<number, ProductoImagenLookupItem>>(new Map());

  // ---- Detalle ----------------------------------------------------------------------------------------------------------
  protected readonly detalleVisible = signal(false);
  protected readonly cargandoDetalle = signal(false);
  protected readonly detalle = signal<OperacionSyncDetalle | null>(null);
  protected readonly lineasDetalle = computed<LineaPayloadSync[]>(() => this.detalle()?.payload?.lineas ?? []);

  // ---- Resolver ----------------------------------------------------------------------------------------------------------
  protected readonly accionPendiente = signal<AccionResolucionSync | null>(null);
  protected readonly motivoAccion = signal('');
  protected readonly entiendeAjuste = signal(false);
  protected readonly enviando = signal(false);
  protected readonly motivoValido = computed(() => {
    const largo = this.motivoAccion().trim().length;
    return this.accionPendiente() === 'forzar' ? largo >= MOTIVO_MINIMO_FORZAR : largo >= 1;
  });
  protected readonly puedeConfirmar = computed(
    () => this.motivoValido() && (this.accionPendiente() !== 'forzar' || this.entiendeAjuste()) && !this.enviando(),
  );
  /** Lo que se sumará al inventario si se fuerza: el faltante exacto de cada prenda. */
  protected readonly ajustesPrevistos = computed(() =>
    (this.detalle()?.faltantes ?? [])
      .map((f) => ({ variante_id: f.variante_id, cantidad: f.solicitado - f.disponible }))
      .filter((a) => a.cantidad > 0),
  );

  private secuencia = 0;

  ngOnInit(): void {
    this.cargar();
    this.cargarConflictos();
    this.servicio.sucursales().subscribe({ next: (s) => this.sucursales.set(s), error: () => undefined });
    // Listar usuarios exige `usuarios.gestionar`: sin él no se ofrece el filtro por usuario.
    if (this.auth.tienePermiso('usuarios.gestionar')) {
      this.servicio.usuarios().subscribe({ next: (u) => this.usuarios.set(u), error: () => undefined });
    }
  }

  // ---- Lista --------------------------------------------------------------------------------------------------------------

  protected cargar(): void {
    const mia = ++this.secuencia;
    this.cargando.set(true);
    this.errorLista.set(false);
    this.servicio.listar(this.consulta()).subscribe({
      next: (pagina) => {
        if (mia !== this.secuencia) return;
        this.operaciones.set(pagina.items);
        this.total.set(pagina.total);
        this.cargando.set(false);
      },
      error: () => {
        if (mia !== this.secuencia) return;
        this.operaciones.set([]);
        this.total.set(0);
        this.errorLista.set(true);
        this.cargando.set(false);
      },
    });
  }

  private consulta(): ConsultaOperacionesSync {
    const rango = this.filtroRango();
    const desde = rango?.[0] ?? null;
    const hasta = rango?.[1] ?? null;
    return {
      pagina: this.pagina(),
      tamanio: TAMANIO_PAGINA,
      estado: this.filtroEstado(),
      tipo: this.filtroTipo(),
      sucursal_id: this.filtroSucursal(),
      usuario_id: this.filtroUsuario(),
      desde: desde ? fechaLocalIso(desde) : null,
      hasta: desde && hasta ? fechaLocalIso(hasta) : null,
    };
  }

  private cargarConflictos(): void {
    this.servicio.contarConflictos().subscribe({ next: (n) => this.conflictos.set(n), error: () => undefined });
  }

  private irAPrimeraPagina(): void {
    this.pagina.set(1);
    this.cargar();
  }

  protected alPaginar(evento: TableLazyLoadEvent): void {
    const filas = evento.rows ?? TAMANIO_PAGINA;
    const pagina = Math.floor((evento.first ?? 0) / filas) + 1;
    if (pagina === this.pagina()) return;
    this.pagina.set(pagina);
    this.cargar();
  }

  protected cambiarEstado(estado: EstadoOperacionSync | null): void {
    this.filtroEstado.set(estado);
    this.irAPrimeraPagina();
  }

  protected cambiarTipo(tipo: TipoOperacionSync | null): void {
    this.filtroTipo.set(tipo);
    this.irAPrimeraPagina();
  }

  protected cambiarSucursal(id: number | null): void {
    this.filtroSucursal.set(id);
    this.irAPrimeraPagina();
  }

  protected cambiarUsuario(id: number | null): void {
    this.filtroUsuario.set(id);
    this.irAPrimeraPagina();
  }

  /** Un rango a medias (solo el primer día) espera al segundo antes de consultar. */
  protected cambiarRango(rango: (Date | null)[] | null): void {
    this.filtroRango.set(rango);
    if (rango !== null && rango[0] && !rango[1]) return;
    this.irAPrimeraPagina();
  }

  protected verConflictos(): void {
    this.cambiarEstado('en_conflicto');
  }

  protected quitarFiltros(): void {
    this.filtroEstado.set(null);
    this.filtroTipo.set(null);
    this.filtroSucursal.set(null);
    this.filtroUsuario.set(null);
    this.filtroRango.set(null);
    this.irAPrimeraPagina();
  }

  // ---- Nombres y textos ---------------------------------------------------------------------------------------------------

  protected nombreSucursal(id: number | null): string {
    if (id === null) return '—';
    return this.sucursales().find((s) => s.id === id)?.nombre ?? `Sucursal n.º ${id}`;
  }

  protected nombreUsuario(id: number): string {
    return this.opcionesUsuario().find((u) => u.id === id)?.etiqueta ?? `Usuario n.º ${id}`;
  }

  protected producto(varianteId: number): string {
    return this.variantes().get(varianteId)?.producto_nombre ?? `Variante n.º ${varianteId}`;
  }

  protected tallaYColor(varianteId: number): string {
    const v = this.variantes().get(varianteId);
    return v ? [v.talla_codigo, v.color_nombre].filter(Boolean).join(' · ') : '';
  }

  /** "Polera Estampada (M · Negro)" o "Variante n.º 7" si no se pudo resolver. */
  protected prenda(varianteId: number): string {
    const detalle = this.tallaYColor(varianteId);
    return detalle ? `${this.producto(varianteId)} (${detalle})` : this.producto(varianteId);
  }

  /** El total de la lista sale del recurso creado (la lista no trae el payload); sin él, "—". */
  protected totalDeFila(op: OperacionSync): string {
    return op.recurso?.total ? formatoBs(op.recurso.total) : '—';
  }

  protected subtotal(linea: LineaPayloadSync): string {
    const precio = aCentavos(linea.precio_unitario ?? 0);
    const descuento = aCentavos(linea.descuento_unitario ?? 0);
    return formatoBs(centavosATexto(linea.cantidad * (precio - (Number.isNaN(descuento) ? 0 : descuento))));
  }

  protected textoRetraso(op: OperacionSync): string | null {
    const horas = horasDeRetraso(op.recibida_en, op.fecha_operacion);
    return horas === null ? null : `llegó con ${horas} h de retraso`;
  }

  protected textoCliente(d: OperacionSyncDetalle): string {
    const id = d.payload?.cliente_id;
    if (id == null) return d.tipo === 'reserva' ? '—' : 'Sin cliente (venta al paso)';
    return `Cliente n.º ${id}`;
  }

  protected textoMetodo(metodo: string): string {
    const limpio = metodo.replace(/_/g, ' ').trim();
    return limpio ? limpio.charAt(0).toUpperCase() + limpio.slice(1) : '—';
  }

  protected textoDecision(resolucion: ResolucionConflictoSync): string {
    return resolucion.accion === 'forzar'
      ? 'Forzada: se ajustó el inventario y se confirmó la venta'
      : 'Rechazada: no se tocó el inventario';
  }

  /** El motivo de una operación en lenguaje claro, o `null` si no hay nada que explicar. */
  protected motivoClaro(op: OperacionSync): string | null {
    if (op.estado === 'confirmada') return null;
    if (op.estado === 'en_conflicto' && (!op.motivo || op.motivo === 'stock_insuficiente')) {
      return op.tipo === 'reserva'
        ? 'No había stock suficiente para esta reserva. Las reservas en conflicto solo se pueden rechazar.'
        : 'No había stock suficiente cuando llegó la venta. Decide si la aceptas (se ajusta el inventario) o la rechazas.';
    }
    const fijo = op.motivo ? TEXTO_MOTIVO[op.motivo] : undefined;
    return fijo ?? (op.mensaje?.trim() || 'El servidor no aceptó la operación.');
  }

  // ---- Detalle ------------------------------------------------------------------------------------------------------------

  protected abrirDetalle(op: OperacionSync): void {
    this.detalle.set(null);
    this.cargandoDetalle.set(true);
    this.detalleVisible.set(true);
    this.servicio.obtener(op.operacion_id).subscribe({
      next: (detalle) => {
        if (!this.detalleVisible()) return;
        this.cargandoDetalle.set(false);
        this.detalle.set(detalle);
        this.cargarNombresDePrendas(detalle);
      },
      error: (error: HttpErrorResponse) => {
        // El manejo global ya avisó. Si la operación ya no está al alcance, la lista se actualiza.
        this.cargandoDetalle.set(false);
        this.detalleVisible.set(false);
        if (error.status === 404) this.cargar();
      },
    });
  }

  protected alCambiarDetalle(visible: boolean): void {
    this.detalleVisible.set(visible);
    if (!visible) {
      this.accionPendiente.set(null);
      this.detalle.set(null);
    }
  }

  private cargarNombresDePrendas(detalle: OperacionSyncDetalle): void {
    const ids = [
      ...(detalle.payload?.lineas ?? []).map((l) => l.variante_id),
      ...detalle.faltantes.map((f) => f.variante_id),
      ...detalle.avisos.map((a) => a.variante_id),
      ...(detalle.resolucion?.ajustes ?? []).map((a) => a.variante_id),
    ];
    this.servicio.detallesDeVariantes(ids).subscribe({
      next: (items) =>
        this.variantes.update((actual) => {
          const nuevo = new Map(actual);
          for (const item of items) if (item.variante_id !== null) nuevo.set(item.variante_id, item);
          return nuevo;
        }),
      error: () => undefined,
    });
  }

  // ---- Resolver --------------------------------------------------------------------------------------------------------------

  protected abrirAccion(accion: AccionResolucionSync): void {
    const op = this.detalle();
    if (!op || op.estado !== 'en_conflicto' || !this.puedeResolver()) return;
    if (accion === 'forzar' && op.tipo !== 'venta_contado') return;
    this.motivoAccion.set('');
    this.entiendeAjuste.set(false);
    this.enviando.set(false);
    this.accionPendiente.set(accion);
  }

  protected cerrarAccion(): void {
    if (this.enviando()) return;
    this.accionPendiente.set(null);
  }

  /** [Confirmar]: se deshabilita al primer clic, así un doble clic no manda dos resoluciones. */
  protected confirmarAccion(): void {
    const accion = this.accionPendiente();
    const op = this.detalle();
    if (accion === null || op === null || !this.puedeConfirmar()) return;
    this.enviando.set(true);
    this.servicio.resolver(op.operacion_id, { accion, motivo: this.motivoAccion().trim() }).subscribe({
      next: (resuelta) => this.alResolver(accion, resuelta),
      error: (error: HttpErrorResponse) => this.alFallarResolver(error, op),
    });
  }

  private alResolver(accion: AccionResolucionSync, resuelta: OperacionSyncDetalle): void {
    this.enviando.set(false);
    this.accionPendiente.set(null);
    this.detalle.set(resuelta);
    this.reemplazarFila(resuelta);
    this.cargarNombresDePrendas(resuelta);
    this.cargarConflictos();
    const codigo = resuelta.recurso?.codigo;
    this.messageService.add(
      accion === 'forzar'
        ? {
            severity: 'success',
            summary: 'Venta confirmada',
            detail: `Se registró el ajuste de inventario${codigo ? ` y la venta ${codigo} quedó confirmada` : ' y la venta quedó confirmada'}.`,
          }
        : {
            severity: 'success',
            summary: 'Operación rechazada',
            detail: 'Quedó guardado tu motivo y el operador recibirá un aviso. No se tocó el inventario.',
          },
    );
  }

  private alFallarResolver(error: HttpErrorResponse, op: OperacionSyncDetalle): void {
    this.enviando.set(false);
    if (error.status === 409) {
      // Otra persona se adelantó, o la operación ya no se puede resolver así: se explica y se muestra cómo quedó.
      this.accionPendiente.set(null);
      this.messageService.add({ severity: 'warn', summary: 'No se pudo resolver', detail: textoDeError(error), life: 8000 });
      this.refrescar(op.operacion_id);
      return;
    }
    if (error.status === 404) {
      this.accionPendiente.set(null);
      this.detalleVisible.set(false);
      this.detalle.set(null);
      this.messageService.add({
        severity: 'warn',
        summary: 'Operación no disponible',
        detail: 'Esta operación ya no está disponible para ti. Actualizamos la lista.',
      });
      this.cargar();
      this.cargarConflictos();
      return;
    }
    // Otro error: el diálogo sigue abierto para reintentar.
    this.messageService.add({ severity: 'error', summary: 'No se pudo resolver', detail: textoDeError(error) });
  }

  /** Vuelve a leer una operación (tras un 409) y deja la fila y el detalle como quedaron en el servidor. */
  private refrescar(operacionId: string): void {
    this.servicio.obtener(operacionId, true).subscribe({
      next: (fresca) => {
        this.reemplazarFila(fresca);
        if (this.detalle()?.operacion_id === operacionId) {
          this.detalle.set(fresca);
          this.cargarNombresDePrendas(fresca);
        }
      },
      error: () => undefined,
    });
    this.cargarConflictos();
  }

  private reemplazarFila(op: OperacionSyncDetalle): void {
    const { payload: _payload, ...fila } = op;
    this.operaciones.update((lista) => lista.map((o) => (o.operacion_id === fila.operacion_id ? fila : o)));
  }
}
