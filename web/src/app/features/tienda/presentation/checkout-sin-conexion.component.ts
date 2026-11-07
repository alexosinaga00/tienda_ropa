import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ConectividadService } from '../../../core/conectividad.service';
import type { SucursalRecordada } from '../../../core/offline-cliente/cliente-offline.models';
import { MAX_LINEAS_PEDIDO } from '../../../core/offline-cliente/cliente-offline.config';
import { textoDinero } from '../../../core/offline-cliente/dinero';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { DisponibilidadService } from '../data/disponibilidad.service';
import { CarritoLocalService } from '../state/carrito-local.service';
import { MetodoPagoLocalService } from '../state/metodo-pago-local.service';
import { PedidosSinConexionService } from '../state/pedidos-sin-conexion.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { ResumenCompraComponent } from './resumen-compra.component';

/**
 * Pago SIN conexión con el PayPal guardado. Solo con retiro en sucursal (el costo de envío necesita la zona, que se
 * cotiza con conexión), con los precios que el cliente tenía guardados. Muestra el total, pide aceptar "Se cobrará
 * hasta Bs X" y deja el pedido en la cola; el carrito local queda vacío. Al volver la conexión la cola lo envía.
 */
@Component({
  selector: 'app-checkout-sin-conexion',
  standalone: true,
  imports: [RouterLink, IconoComponent, ResumenCompraComponent],
  templateUrl: './checkout-sin-conexion.component.html',
  styleUrl: './checkout-sin-conexion.component.scss',
})
export class CheckoutSinConexionComponent implements OnInit {
  protected readonly carrito = inject(CarritoLocalService);
  protected readonly metodoPago = inject(MetodoPagoLocalService);
  private readonly cola = inject(PedidosSinConexionService);
  private readonly disponibilidad = inject(DisponibilidadService);
  private readonly conectividad = inject(ConectividadService);
  private readonly router = inject(Router);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly cargando = signal(true);
  protected readonly sucursales = signal<SucursalRecordada[]>([]);
  protected readonly sucursalId = signal<number | null>(null);
  protected readonly acepto = signal(false);
  protected readonly guardando = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');
  /** Para retirar no sirve un depósito (no recibe clientes). */
  protected readonly retirables = computed(() => this.sucursales().filter((s) => !s.es_deposito));
  protected readonly sucursalElegida = computed(() => this.retirables().find((s) => s.id === this.sucursalId()) ?? null);
  /** Retiro en sucursal: sin costo de envío. */
  protected readonly costoEnvioCentavos = 0;
  protected readonly totalCentavos = computed(() => this.carrito.subtotalCentavos() + this.costoEnvioCentavos);
  protected readonly total = computed(() => this.totalCentavos() / 100);
  protected readonly totalTexto = computed(() => textoDinero(this.totalCentavos()));
  protected readonly demasiadasLineas = computed(() => this.carrito.cantidadLineas() > MAX_LINEAS_PEDIDO);

  protected readonly puedeConfirmar = computed(
    () =>
      !this.cargando() &&
      !this.guardando() &&
      this.carrito.cantidadLineas() > 0 &&
      !this.demasiadasLineas() &&
      this.metodoPago.tienePaypal() &&
      this.sucursalElegida() !== null &&
      this.acepto(),
  );

  async ngOnInit(): Promise<void> {
    await Promise.all([this.carrito.cargar(), this.metodoPago.cargar()]);
    let sucursales = await this.carrito.sucursalesRecordadas();
    if (sucursales.length === 0) {
      // Nunca se guardaron: se intenta con lo que el Service Worker tenga del catálogo público.
      try {
        const lista = await firstValueFrom(this.disponibilidad.sucursales());
        sucursales = lista.map((s) => ({ id: s.id, nombre: s.nombre, es_deposito: s.es_deposito }));
        void this.carrito.recordarSucursales(sucursales);
      } catch {
        sucursales = [];
      }
    }
    this.sucursales.set(sucursales);
    this.sucursalId.set(this.sucursalSugerida());
    this.cargando.set(false);
  }

  /** La sucursal donde se sabía que había stock de TODAS las prendas, si es una sola y se puede retirar. */
  private sucursalSugerida(): number | null {
    const conocidas = new Set(this.carrito.lineas().map((l) => l.sucursal_id));
    if (conocidas.size !== 1) return null;
    const [unica] = [...conocidas];
    return unica !== null && this.retirables().some((s) => s.id === unica) ? unica : null;
  }

  /** "M · Azul" (o lo que haya); vacío si no hay talla ni color. */
  protected detalleDe(talla: string | null, color: string | null): string {
    return [talla, color].filter((parte) => !!parte).join(' · ');
  }

  protected elegirSucursal(id: number): void {
    this.sucursalId.set(id);
  }

  protected alternarAceptacion(evento: Event): void {
    this.acepto.set((evento.target as HTMLInputElement).checked);
  }

  protected async confirmar(): Promise<void> {
    const sucursal = this.sucursalElegida();
    if (!this.puedeConfirmar() || sucursal === null) return;
    this.guardando.set(true);
    this.error.set(null);
    const pedido = await this.cola.encolar({
      sucursalId: sucursal.id,
      sucursalNombre: sucursal.nombre,
      costoEnvioCentavos: this.costoEnvioCentavos,
      lineas: this.carrito.lineas(),
    });
    this.guardando.set(false);
    if (pedido === null) {
      this.error.set('No pudimos guardar tu pedido en este equipo. Revisa que tengas espacio e inténtalo de nuevo.');
      return;
    }
    await this.router.navigate(this.tienda.ruta('mi-cuenta', 'pedidos-sin-conexion'), { queryParams: { nuevo: pedido.operacion_id } });
  }
}
