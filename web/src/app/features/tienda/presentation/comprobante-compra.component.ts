import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { instanteServidor } from '../../../core/date-utils';
import { Venta } from '../../../core/models/ventas.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { QrSvg, generarQr } from '../../../shared/qr/qr-svg';
import { TiendaActualService } from '../state/tienda-actual.service';

/** Una prenda del comprobante, ya con su nombre (la venta solo trae la variante). */
export interface LineaDeComprobante {
  id: number;
  nombre: string;
  /** "M · Azul". */
  detalle: string;
  cantidad: number;
  subtotal: number;
}

/** Solo una compra ya pagada tiene comprobante: una pendiente de pago o anulada no. */
export function tieneComprobante(venta: Pick<Venta, 'estado'>): boolean {
  return venta.estado === 'pagada' || venta.estado === 'entregada';
}

/**
 * Comprobante de una compra pagada: código, fecha (hora local), sucursal, prendas, total y un QR con el enlace que
 * entrega el servidor (`enlace_verificacion`), que lleva a la venta en la Caja. El QR se dibuja en SVG; "Imprimir o
 * guardar PDF" usa el diálogo de impresión del navegador (`#area-imprimible` + la hoja `@media print`).
 * Vive en memoria: no se guarda en caché, así que sin conexión solo se ve si la compra ya estaba abierta.
 */
@Component({
  selector: 'app-comprobante-compra',
  standalone: true,
  imports: [DatePipe, DecimalPipe, IconoComponent],
  templateUrl: './comprobante-compra.component.html',
  styleUrl: './comprobante-compra.component.scss',
})
export class ComprobanteCompraComponent {
  protected readonly tienda = inject(TiendaActualService);

  readonly venta = input.required<Venta>();
  readonly sucursalNombre = input<string | null>(null);
  readonly lineas = input<LineaDeComprobante[]>([]);

  protected readonly visible = computed(() => tieneComprobante(this.venta()));
  /** El texto que lleva el QR, tal cual lo manda el servidor; sin él no se dibuja ningún código. */
  protected readonly enlace = computed(() => this.venta().enlace_verificacion?.trim() || null);
  protected readonly qr = signal<QrSvg | null>(null);
  protected readonly errorQr = signal(false);
  protected readonly nombreTienda = computed(() => this.tienda.empresa()?.nombre ?? 'FashionStore');
  protected readonly fechaLocal = instanteServidor;

  constructor() {
    effect(() => {
      const enlace = this.visible() ? this.enlace() : null;
      untracked(() => void this.dibujar(enlace));
    });
  }

  private async dibujar(enlace: string | null): Promise<void> {
    this.errorQr.set(false);
    if (enlace === null) {
      this.qr.set(null);
      return;
    }
    try {
      const dibujo = await generarQr(enlace);
      // Si mientras tanto cambió el enlace, este dibujo ya no corresponde.
      if (enlace === this.enlace()) this.qr.set(dibujo);
    } catch {
      this.qr.set(null);
      this.errorQr.set(true);
    }
  }

  /**
   * Abre el diálogo de impresión (ahí se elige "Guardar como PDF"). El navegador nombra el PDF con el título de la
   * página: se le pone el código de la compra mientras dura la impresión.
   */
  protected imprimir(): void {
    const anterior = document.title;
    const restaurar = () => {
      document.title = anterior;
      window.removeEventListener('afterprint', restaurar);
    };
    document.title = `Comprobante ${this.venta().codigo}`;
    window.addEventListener('afterprint', restaurar);
    window.print();
  }
}
