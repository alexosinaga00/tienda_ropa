import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { NotificacionesService } from '../../../core/notificaciones.service';
import { ConectividadService } from '../../../core/conectividad.service';
import type { EstadoPedidoLocal, PedidoSinConexion } from '../../../core/offline-cliente/cliente-offline.models';
import { aCentavos, textoDinero } from '../../../core/offline-cliente/dinero';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { PedidosSinConexionService } from '../state/pedidos-sin-conexion.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { MiCuentaPestanasComponent } from './mi-cuenta-pestanas.component';

const ETIQUETAS: Record<EstadoPedidoLocal, string> = {
  pendiente: 'Pendiente de envío',
  enviando: 'Enviando…',
  cobrado: 'Cobrado',
  rechazado: 'Rechazado',
  vencido: 'Vencido',
};

const CLASES: Record<EstadoPedidoLocal, string> = {
  pendiente: 'fs-chip--advertencia',
  enviando: 'fs-chip--advertencia',
  cobrado: 'fs-chip--exito',
  rechazado: 'fs-chip--error',
  vencido: 'fs-chip--error',
};

/** Tipo de notificación del servidor para estos pedidos. */
export const TIPO_NOTIFICACION_PEDIDO = 'pedido_diferido';

/**
 * Mi cuenta > Pedidos sin conexión: lo que el cliente pidió sin red y paga con su PayPal guardado. Cada pedido está
 * Pendiente de envío, Enviando, Cobrado (con enlace a la compra) o Rechazado (con el motivo en palabras). Un pedido que
 * todavía no salió se puede descartar. Debajo, los avisos que el servidor guardó de tipo `pedido_diferido` (si el
 * servidor no los entrega a clientes, simplemente no aparecen).
 */
@Component({
  selector: 'app-pedidos-sin-conexion',
  standalone: true,
  imports: [DatePipe, RouterLink, IconoComponent, MiCuentaPestanasComponent],
  templateUrl: './pedidos-sin-conexion.component.html',
  styleUrl: './pedidos-sin-conexion.component.scss',
})
export class PedidosSinConexionComponent implements OnInit {
  protected readonly cola = inject(PedidosSinConexionService);
  private readonly conectividad = inject(ConectividadService);
  private readonly notificaciones = inject(NotificacionesService);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');
  /** Pedido cuyo descarte se está confirmando. */
  protected readonly confirmandoDescarte = signal<string | null>(null);
  protected readonly descartando = signal(false);
  protected readonly cargando = signal(true);

  /** Avisos del servidor sobre estos pedidos. */
  protected readonly avisos = computed(() => this.notificaciones.deTipo(TIPO_NOTIFICACION_PEDIDO));

  async ngOnInit(): Promise<void> {
    await this.cola.refrescar();
    this.cargando.set(false);
    // Verlos aquí es "haberlos visto": la franja de aviso de la tienda deja de contarlos como nuevos.
    await this.cola.marcarVistos();
    if (!this.sinConexion()) {
      // En silencio: si el servidor no entrega notificaciones a clientes, no hay error que mostrar.
      this.notificaciones.cargar(true).subscribe({ error: () => undefined });
    }
  }

  protected etiqueta(estado: EstadoPedidoLocal): string {
    return ETIQUETAS[estado];
  }

  protected clase(estado: EstadoPedidoLocal): string {
    return CLASES[estado];
  }

  protected cantidadPrendas(pedido: PedidoSinConexion): number {
    return pedido.lineas.reduce((suma, l) => suma + l.cantidad, 0);
  }

  /** "M · Azul" (o lo que haya); vacío si no hay talla ni color. */
  protected detalleDe(talla: string | null, color: string | null): string {
    return [talla, color].filter((parte) => !!parte).join(' · ');
  }

  protected dinero(valor: string | null): string {
    return textoDinero(aCentavos(valor));
  }

  protected pedirDescarte(operacionId: string): void {
    this.confirmandoDescarte.set(operacionId);
  }

  protected cancelarDescarte(): void {
    this.confirmandoDescarte.set(null);
  }

  protected async descartar(operacionId: string): Promise<void> {
    this.descartando.set(true);
    await this.cola.descartar(operacionId);
    this.descartando.set(false);
    this.confirmandoDescarte.set(null);
  }

  protected reintentar(): void {
    void this.cola.enviarAhora();
  }

  protected marcarLeida(notificacionId: number): void {
    this.notificaciones.marcarLeida(notificacionId).subscribe({ error: () => undefined });
  }
}
