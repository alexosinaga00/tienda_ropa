import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EstadoVenta, Venta, etiquetaDevolucion } from '../../../core/models/ventas.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { CambiosService } from '../data/cambios.service';
import { PedidosService } from '../data/pedidos.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { MiCuentaPestanasComponent } from './mi-cuenta-pestanas.component';

const ETIQUETAS_ESTADO: Record<EstadoVenta, string> = {
  pendiente_pago: 'Pendiente de pago',
  pagada: 'Pagada',
  entregada: 'Entregada',
  anulada: 'Anulada',
};

/** Variante del chip de estado (ver .fs-chip en styles.scss). */
const CLASES_ESTADO: Record<EstadoVenta, string> = {
  pendiente_pago: 'fs-chip--advertencia',
  pagada: 'fs-chip--exito',
  entregada: 'fs-chip--exito',
  anulada: 'fs-chip--error',
};

@Component({
  selector: 'app-mis-compras',
  standalone: true,
  imports: [RouterLink, DatePipe, DecimalPipe, IconoComponent, MiCuentaPestanasComponent],
  templateUrl: './mis-compras.component.html',
  styleUrl: './mis-compras.component.scss',
})
export class MisComprasComponent implements OnInit {
  private readonly pedidosService = inject(PedidosService);
  protected readonly tienda = inject(TiendaActualService);

  private readonly cambiosService = inject(CambiosService);

  protected readonly compras = signal<Venta[]>([]);
  /** Ids de las compras con una solicitud de cambio de talla o color pendiente. */
  protected readonly conCambioPendiente = signal<Set<number>>(new Set());
  /** Compras que quedaron sin pagar: se avisa arriba para que no pasen desapercibidas. */
  protected readonly pendientes = computed(() => this.compras().filter((c) => c.estado === 'pendiente_pago'));
  protected readonly cargando = signal(true);
  protected readonly error = signal(false);

  ngOnInit(): void {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    this.error.set(false);
    this.pedidosService.listarMisCompras().subscribe({
      next: (compras) => {
        this.compras.set(compras);
        this.cargando.set(false);
        this.cargarCambiosPendientes();
      },
      error: () => {
        this.cargando.set(false);
        this.error.set(true);
      },
    });
  }

  /** Las compras con una solicitud de cambio pendiente. Si la consulta falla, la lista queda como siempre. */
  private cargarCambiosPendientes(): void {
    this.cambiosService.mias().subscribe({
      next: (solicitudes) =>
        this.conCambioPendiente.set(new Set(solicitudes.filter((s) => s.estado === 'pendiente').map((s) => s.venta_id))),
      error: () => this.conCambioPendiente.set(new Set()),
    });
  }

  /** "Con devolución (1 de 4)" / "Devuelta" junto al estado, o null si no se devolvió nada. */
  marcaDevolucion(venta: Venta): string | null {
    return etiquetaDevolucion(venta);
  }

  etiquetaEstado(estado: EstadoVenta): string {
    return ETIQUETAS_ESTADO[estado];
  }

  claseEstado(estado: EstadoVenta): string {
    return CLASES_ESTADO[estado];
  }
}
