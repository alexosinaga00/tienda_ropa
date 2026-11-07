import { DecimalPipe } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { environment } from '../../../environments/environment';
import { instanteServidor } from '../../core/date-utils';
import { AuthService } from '../../core/auth.service';
import { ResumenInicio, VentaRecienteInicio } from '../../core/models/inicio.models';
import { EstadoReserva } from '../../core/models/reservas.models';
import { EstadoVenta, etiquetaDevolucionUnidades } from '../../core/models/ventas.models';
import { IconoComponent } from '../../shared/icono/icono.component';

interface ResumenEstadoReserva {
  estado: EstadoReserva;
  etiqueta: string;
  color: string;
  cantidad: number;
}

/** Cómo se muestra el estado de una venta en "Últimas ventas". */
const ESTADO_VENTA: Record<EstadoVenta, { etiqueta: string; chip: string }> = {
  pendiente_pago: { etiqueta: 'Pendiente de pago', chip: 'fs-chip--advertencia' },
  pagada: { etiqueta: 'Pagada', chip: 'fs-chip--exito' },
  entregada: { etiqueta: 'Entregada', chip: 'fs-chip--exito' },
  anulada: { etiqueta: 'Anulada', chip: 'fs-chip--error' },
};

const ESTADOS_RESERVA: { estado: EstadoReserva; etiqueta: string; color: string }[] = [
  { estado: 'pendiente', etiqueta: 'Pendientes', color: 'var(--fs-acento)' },
  { estado: 'en_prueba', etiqueta: 'En prueba', color: 'var(--fs-advertencia)' },
  { estado: 'completada', etiqueta: 'Completadas', color: 'var(--fs-exito)' },
  { estado: 'cancelada', etiqueta: 'Canceladas', color: 'var(--fs-muted)' },
];

/**
 * Resumen de inicio del personal. Una sola llamada (`GET /inicio/resumen`): el servidor suma lo de HOY (día de Bolivia) en
 * la base y devuelve solo las secciones que el usuario puede ver. Mientras llega, las tarjetas muestran un esqueleto: un 0
 * de relleno parecería un dato real.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [DecimalPipe, IconoComponent],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly authService = inject(AuthService);

  protected readonly usuario = this.authService.usuario;
  protected readonly fechaHoy = this.formatearFecha(new Date());

  /** Qué secciones podría tener el usuario por su rol: sirve para dibujar los esqueletos antes de que llegue el resumen. */
  private readonly permiteVentas = computed(() => this.authService.tienePermiso('ventas.gestionar_sucursal'));
  private readonly permiteInventario = computed(() => this.authService.tienePermiso('inventario.ver'));
  private readonly permiteReservas = computed(() => this.authService.tienePermiso('reservas.gestionar_sucursal'));
  /** Un rol sin ventas, inventario ni reservas (p. ej. el proveedor) no tiene nada que mostrar en este resumen. */
  protected readonly sinFuncionesEnResumen = computed(
    () => !this.permiteVentas() && !this.permiteInventario() && !this.permiteReservas(),
  );

  protected readonly cargando = signal(true);
  /** El servidor respondió 403: no es administrador y no tiene sucursal asignada. */
  protected readonly sinSucursal = signal(false);
  /** Falló la carga (red, servidor): se ofrece reintentar. */
  protected readonly fallo = signal(false);
  protected readonly resumen = signal<ResumenInicio | null>(null);

  protected readonly sucursalNombre = computed(() => this.resumen()?.sucursal_nombre || null);

  // Cada sección se ve mientras carga (si el rol la permite) y, ya cargada, solo si el servidor la mandó.
  protected readonly puedeVentas = computed(() => (this.resumen() ? !!this.resumen()?.ventas : this.permiteVentas()));
  protected readonly puedeInventario = computed(() => (this.resumen() ? !!this.resumen()?.stock : this.permiteInventario()));
  protected readonly puedeReservas = computed(() => (this.resumen() ? !!this.resumen()?.reservas : this.permiteReservas()));
  protected readonly mostrarIndicadores = computed(
    () => !this.sinSucursal() && !this.fallo() && !this.sinFuncionesEnResumen(),
  );

  protected readonly ticketsHoy = computed(() => this.resumen()?.ventas?.tickets ?? 0);
  protected readonly totalVentasHoy = computed(() => Number(this.resumen()?.ventas?.total_ventas ?? 0));
  /** Ventas de hoy que aún esperan el pago: no suman a lo vendido, pero se avisan aparte. */
  protected readonly porCobrarCantidad = computed(() => this.resumen()?.ventas?.por_cobrar_cantidad ?? 0);
  protected readonly porCobrarTotal = computed(() => Number(this.resumen()?.ventas?.por_cobrar_total ?? 0));
  protected readonly vendidosHoy = computed(() => this.resumen()?.ventas?.mas_vendidas ?? []);
  /** Las ventas de hoy más recientes (la tabla "Últimas ventas"). */
  protected readonly ventasRecientes = computed(() => this.resumen()?.ventas?.recientes ?? []);
  /** Unidades de la prenda más vendida: es el 100 % de la altura de las barras. */
  protected readonly maxVendido = computed(() => Math.max(1, ...this.vendidosHoy().map((v) => v.cantidad)));

  protected readonly alertasStock = computed(() => this.resumen()?.stock?.alertas ?? []);
  /** Todas las alertas de stock bajo (la lista de abajo muestra solo las primeras). */
  protected readonly totalAlertasStock = computed(() => this.resumen()?.stock?.total_alertas ?? 0);

  protected readonly totalReservasHoy = computed(() => this.resumen()?.reservas?.total ?? 0);
  protected readonly resumenReservas = computed<ResumenEstadoReserva[]>(() => {
    const porEstado = this.resumen()?.reservas?.por_estado ?? [];
    return ESTADOS_RESERVA.map((e) => ({
      ...e,
      cantidad: porEstado.find((fila) => fila.codigo === e.estado)?.cantidad ?? 0,
    }));
  });

  /** Tres filas de relleno para los paneles que se estan cargando. */
  protected readonly filasEsqueleto = [1, 2, 3];

  ngOnInit(): void {
    this.cargar();
  }

  protected reintentar(): void {
    this.cargar();
  }

  private cargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.sinSucursal.set(false);
    this.http.get<ResumenInicio>(`${environment.apiUrl}/inicio/resumen`).subscribe({
      next: (resumen) => {
        this.resumen.set(resumen);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.cargando.set(false);
        // 403: sin alcance global y sin sucursal asignada (el servidor lo dice con ese estado).
        if (error.status === 403) this.sinSucursal.set(true);
        else this.fallo.set(true);
      },
    });
  }

  protected estadoVenta(estado: EstadoVenta): { etiqueta: string; chip: string } {
    return ESTADO_VENTA[estado] ?? { etiqueta: estado, chip: '' };
  }

  /** "Con devolución (1 de 4)" / "Devuelta": la venta sigue "pagada" (los reportes la cuentan), pero se ve que se devolvió. */
  protected etiquetaDevolucion(venta: VentaRecienteInicio): string | null {
    return etiquetaDevolucionUnidades(venta.unidades_vendidas, venta.unidades_devueltas);
  }

  /** Hora local de una venta ("14:35"). */
  protected horaDe(fecha: string): string {
    return instanteServidor(fecha).toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit', hour12: false });
  }

  private formatearFecha(fecha: Date): string {
    const texto = fecha.toLocaleDateString('es-BO', { weekday: 'long', day: 'numeric', month: 'long' });
    return texto.charAt(0).toUpperCase() + texto.slice(1);
  }
}
