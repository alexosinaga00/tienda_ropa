import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EstadoVenta, Venta } from '../../../core/models/ventas.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { PedidosService } from '../data/pedidos.service';
import { TiendaActualService } from '../state/tienda-actual.service';

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
  imports: [RouterLink, DatePipe, DecimalPipe, IconoComponent],
  templateUrl: './mis-compras.component.html',
  styleUrl: './mis-compras.component.scss',
})
export class MisComprasComponent implements OnInit {
  private readonly pedidosService = inject(PedidosService);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly compras = signal<Venta[]>([]);
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
      },
      error: () => {
        this.cargando.set(false);
        this.error.set(true);
      },
    });
  }

  etiquetaEstado(estado: EstadoVenta): string {
    return ETIQUETAS_ESTADO[estado];
  }

  claseEstado(estado: EstadoVenta): string {
    return CLASES_ESTADO[estado];
  }
}
