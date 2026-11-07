import { DecimalPipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';
import { environment } from '../../../environments/environment';
import { diaLocalDe, fechaLocalIso, instanteServidor } from '../../core/date-utils';
import { AuthService } from '../../core/auth.service';
import { ProductoImagenLookupItem } from '../../core/models/catalogo.models';
import { FilaConsolidado } from '../../core/models/inventario.models';
import { Empleado, Sucursal } from '../../core/models/organizacion.models';
import { EstadoReserva, Reserva } from '../../core/models/reservas.models';
import { EstadoVenta, Venta, etiquetaDevolucion } from '../../core/models/ventas.models';
import { IconoComponent } from '../../shared/icono/icono.component';

interface ProductoVendidoHoy {
  variante_id: number;
  cantidad: number;
  nombre: string;
}

interface AlertaStockConFoto extends FilaConsolidado {
  imagen: string | null;
}

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

const VENTAS_RECIENTES = 5;

/** Solo estas ventas cuentan como "vendido": una pendiente de pago aún puede cancelarse y una anulada ya no vale. */
const ESTADOS_VENDIDA: ReadonlySet<EstadoVenta> = new Set<EstadoVenta>(['pagada', 'entregada']);

const ESTADOS_RESERVA: { estado: EstadoReserva; etiqueta: string; color: string }[] = [
  { estado: 'pendiente', etiqueta: 'Pendientes', color: 'var(--fs-acento)' },
  { estado: 'en_prueba', etiqueta: 'En prueba', color: 'var(--fs-advertencia)' },
  { estado: 'completada', etiqueta: 'Completadas', color: 'var(--fs-exito)' },
  { estado: 'cancelada', etiqueta: 'Canceladas', color: 'var(--fs-muted)' },
];

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

  protected readonly puedeVentas = computed(() => this.authService.tienePermiso('ventas.gestionar_sucursal'));
  protected readonly puedeInventario = computed(() => this.authService.tienePermiso('inventario.ver'));
  protected readonly puedeReservas = computed(() =>
    this.authService.tienePermiso('reservas.gestionar_sucursal'),
  );
  /** Un rol sin ventas, inventario ni reservas (p. ej. el proveedor) no tiene nada que mostrar en este resumen. */
  protected readonly sinFuncionesEnResumen = computed(
    () => !this.puedeVentas() && !this.puedeInventario() && !this.puedeReservas(),
  );
  private readonly esAdministrador = computed(() => this.authService.roles().includes('administrador'));

  protected readonly cargando = signal(true);
  protected readonly sucursalId = signal<number | null>(null);
  protected readonly sucursalNombre = signal<string | null>(null);
  protected readonly vistaGlobal = signal(false);
  protected readonly mostrarIndicadores = computed(() => this.sucursalId() !== null || this.vistaGlobal());

  protected readonly ticketsHoy = signal(0);
  protected readonly totalVentasHoy = signal(0);
  /** Ventas de hoy que aún esperan el pago: no suman a lo vendido, pero se avisan aparte. */
  protected readonly porCobrarCantidad = signal(0);
  protected readonly porCobrarTotal = signal(0);
  protected readonly vendidosHoy = signal<ProductoVendidoHoy[]>([]);

  /** Las ventas de hoy más recientes (la tabla "Últimas ventas"). */
  protected readonly ventasRecientes = signal<Venta[]>([]);
  /** Unidades de la prenda más vendida: es el 100 % de la altura de las barras. */
  protected readonly maxVendido = computed(() => Math.max(1, ...this.vendidosHoy().map((v) => v.cantidad)));

  protected readonly alertasStock = signal<AlertaStockConFoto[]>([]);
  /** Todas las alertas de stock bajo (la lista de abajo muestra solo las primeras). */
  protected readonly totalAlertasStock = signal(0);

  protected readonly reservasHoy = signal<Reserva[]>([]);
  protected readonly totalReservasHoy = computed(() => this.reservasHoy().length);
  protected readonly resumenReservas = computed<ResumenEstadoReserva[]>(() => {
    const reservas = this.reservasHoy();
    return ESTADOS_RESERVA.map((e) => ({ ...e, cantidad: reservas.filter((r) => r.estado === e.estado).length }));
  });

  ngOnInit(): void {
    this.http.get<Empleado>(`${environment.apiUrl}/empleados/yo`).subscribe({
      next: (empleado) => {
        this.cargando.set(false);
        // Un administrador con ficha de empleado pero sin sucursal ve lo mismo
        // que uno sin ficha: los indicadores de todas las sucursales.
        if (empleado.sucursal_id === null && this.esAdministrador()) {
          this.cargarVistaGlobal();
          return;
        }
        this.sucursalId.set(empleado.sucursal_id);
        if (empleado.sucursal_id === null) return;

        this.cargarSucursal(empleado.sucursal_id);
        if (this.puedeVentas()) this.cargarVentasHoy(empleado.sucursal_id);
        if (this.puedeInventario()) this.cargarAlertasStock(empleado.sucursal_id);
        if (this.puedeReservas()) this.cargarReservasHoy(empleado.sucursal_id);
      },
      error: () => {
        this.cargando.set(false);
        if (this.esAdministrador()) this.cargarVistaGlobal();
      },
    });
  }

  /** Un administrador no tiene por qué tener un registro de empleado (no
   * está atado a una sucursal): en vez del aviso "sin sucursal asignada",
   * arma los mismos indicadores pero agregados de todas las sucursales. */
  private cargarVistaGlobal(): void {
    this.vistaGlobal.set(true);
    this.sucursalNombre.set('Todas las sucursales');

    if (this.puedeInventario()) this.cargarAlertasStock(null);

    this.http.get<Sucursal[]>(`${environment.apiUrl}/sucursales?tamanio=100`).subscribe({
      next: (sucursales) => {
        const ids = sucursales.map((s) => s.id);
        if (!ids.length) return;

        if (this.puedeVentas()) this.cargarVentasTodasSucursales(ids);
        if (this.puedeReservas()) this.cargarReservasTodasSucursales(ids);
      },
    });
  }

  private cargarSucursal(sucursalId: number): void {
    this.http
      .get<Sucursal>(`${environment.apiUrl}/sucursales/${sucursalId}`)
      .subscribe({ next: (sucursal) => this.sucursalNombre.set(sucursal.nombre) });
  }

  private cargarVentasHoy(sucursalId: number): void {
    this.http
      .get<Venta[]>(`${environment.apiUrl}/ventas/sucursal/${sucursalId}`)
      .subscribe({ next: (ventas) => this.procesarVentas(ventas) });
  }

  private cargarVentasTodasSucursales(sucursalIds: number[]): void {
    forkJoin(sucursalIds.map((id) => this.http.get<Venta[]>(`${environment.apiUrl}/ventas/sucursal/${id}`))).subscribe(
      { next: (listas) => this.procesarVentas(listas.flat()) },
    );
  }

  private procesarVentas(ventas: Venta[]): void {
    const hoy = fechaLocalIso(new Date());
    // `fecha` es un instante UTC: "hoy" se decide por el día LOCAL de quien mira (una venta de las 23:12 en Bolivia
    // es del día siguiente en UTC y cortar el texto la sacaría de hoy).
    const ventasHoy = ventas.filter((v) => diaLocalDe(v.fecha) === hoy);
    const vendidas = ventasHoy.filter((v) => ESTADOS_VENDIDA.has(v.estado));
    const porCobrar = ventasHoy.filter((v) => v.estado === 'pendiente_pago');

    // "Últimas ventas" muestra todas, con su estado: ahí interesa ver también las anuladas y las pendientes.
    this.ventasRecientes.set(
      [...ventasHoy]
        .sort((a, b) => instanteServidor(b.fecha).getTime() - instanteServidor(a.fecha).getTime())
        .slice(0, VENTAS_RECIENTES),
    );
    // Lo vendido (tickets, total y gráfico) cuenta solo las pagadas y entregadas.
    this.ticketsHoy.set(vendidas.length);
    // El backend serializa los montos (Decimal) como texto: sin Number() se concatenan.
    this.totalVentasHoy.set(vendidas.reduce((acc, v) => acc + Number(v.total), 0));
    this.porCobrarCantidad.set(porCobrar.length);
    this.porCobrarTotal.set(porCobrar.reduce((acc, v) => acc + Number(v.total), 0));

    const cantidadPorVariante = new Map<number, number>();
    for (const venta of vendidas) {
      for (const linea of venta.detalle) {
        cantidadPorVariante.set(linea.variante_id, (cantidadPorVariante.get(linea.variante_id) ?? 0) + linea.cantidad);
      }
    }
    const top = [...cantidadPorVariante.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([variante_id, cantidad]) => ({ variante_id, cantidad, nombre: `Variante ${variante_id}` }));
    this.vendidosHoy.set(top);

    if (top.length) {
      this.cargarFotos(top.map((v) => v.variante_id), []);
    }
  }

  private cargarAlertasStock(sucursalId: number | null): void {
    const query = sucursalId !== null ? `?sucursal_id=${sucursalId}` : '';
    this.http.get<FilaConsolidado[]>(`${environment.apiUrl}/inventario/alertas${query}`).subscribe({
      next: (filas) => {
        this.totalAlertasStock.set(filas.length);
        const top: AlertaStockConFoto[] = filas.slice(0, 4).map((f) => ({ ...f, imagen: null }));
        this.alertasStock.set(top);
        if (top.length) {
          this.cargarFotos([], top.map((f) => f.producto_id));
        }
      },
    });
  }

  private cargarReservasHoy(sucursalId: number): void {
    this.http
      .get<Reserva[]>(`${environment.apiUrl}/reservas/sucursal/${sucursalId}`)
      .subscribe({ next: (reservas) => this.procesarReservas(reservas) });
  }

  private cargarReservasTodasSucursales(sucursalIds: number[]): void {
    forkJoin(
      sucursalIds.map((id) => this.http.get<Reserva[]>(`${environment.apiUrl}/reservas/sucursal/${id}`)),
    ).subscribe({ next: (listas) => this.procesarReservas(listas.flat()) });
  }

  private procesarReservas(reservas: Reserva[]): void {
    const hoy = fechaLocalIso(new Date());
    this.reservasHoy.set(reservas.filter((r) => r.fecha_visita.slice(0, 10) === hoy));
  }

  /** Resuelve el nombre real de lo vendido y la foto de las alertas de stock
   * vía el catálogo público -- ver ProductoImagenLookupItem. Se llama una vez por origen de ids (ventas
   * de hoy / alertas de stock), cada una independiente de la otra. */
  private cargarFotos(varianteIds: number[], productoIds: number[]): void {
    const params = new URLSearchParams();
    if (varianteIds.length) params.set('variante_ids', varianteIds.join(','));
    if (productoIds.length) params.set('producto_ids', productoIds.join(','));
    if (!params.toString()) return;

    this.http
      .get<ProductoImagenLookupItem[]>(`${environment.apiUrl}/catalogo/variantes/detalle?${params}`)
      .subscribe({
        next: (items) => {
          const porVariante = new Map(
            items.filter((i) => i.variante_id !== null).map((i) => [i.variante_id as number, i]),
          );
          const porProducto = new Map(items.map((i) => [i.producto_id, i]));

          this.vendidosHoy.update((lista) =>
            lista.map((v) => {
              const item = porVariante.get(v.variante_id);
              return item ? { ...v, nombre: item.producto_nombre } : v;
            }),
          );
          this.alertasStock.update((lista) =>
            lista.map((f) => {
              const item = porProducto.get(f.producto_id);
              return item ? { ...f, imagen: item.imagen_principal } : f;
            }),
          );
        },
      });
  }

  /** "Con devolución (1 de 4)" / "Devuelta": la venta sigue "pagada" (los reportes la cuentan), pero se ve que se devolvió. */
  protected readonly etiquetaDevolucion = etiquetaDevolucion;

  protected estadoVenta(estado: EstadoVenta): { etiqueta: string; chip: string } {
    return ESTADO_VENTA[estado] ?? { etiqueta: estado, chip: '' };
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
