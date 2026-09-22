import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, ElementRef, HostListener, OnInit, ViewChild, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TooltipModule } from 'primeng/tooltip';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { fechaLocalIso } from '../../core/date-utils';
import { VarianteBusqueda } from '../../core/models/catalogo.models';
import { Empleado } from '../../core/models/organizacion.models';
import { MetodoPagoCaja, Pago, PagoCajaRequest, PagoCajaRespuesta } from '../../core/models/pagos.models';
import { FilaVentasPorSucursal, ReporteVentas } from '../../core/models/reportes.models';
import { Reserva } from '../../core/models/reservas.models';
import { DevolucionCrear, Venta, VentaPresencialCrear } from '../../core/models/ventas.models';

interface LineaCarrito {
  variante_id: number;
  descripcion: string;
  precio_efectivo: number;
  cantidad: number;
}

type FaseVenta = 'armando' | 'cobrando';

const OPCIONES_METODO_PAGO: { label: string; value: MetodoPagoCaja }[] = [
  { label: 'Efectivo', value: 'efectivo' },
  { label: 'QR', value: 'qr' },
  { label: 'Tarjeta', value: 'tarjeta' },
  { label: 'Transferencia', value: 'transferencia' },
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
    SelectButtonModule,
    TableModule,
    TagModule,
    TooltipModule,
  ],
  templateUrl: './caja.component.html',
  styleUrl: './caja.component.scss',
})
export class CajaComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly messageService = inject(MessageService);
  private readonly authService = inject(AuthService);

  @ViewChild('inputBusqueda') private inputBusqueda?: ElementRef<HTMLInputElement>;
  @ViewChild('inputMontoRecibido') private inputMontoRecibido?: ElementRef<HTMLInputElement>;
  @ViewChild('inputReserva') private inputReserva?: ElementRef<HTMLInputElement>;

  protected readonly opcionesMetodoPago = OPCIONES_METODO_PAGO;

  protected readonly sucursalId = signal<number | null>(null);
  protected readonly cargandoSucursal = signal(true);
  protected readonly noEsEmpleado = signal(false);

  // ---- Resumen para el administrador (sin sucursal propia = alcance global) ----
  private readonly esAdministrador = computed(() => this.authService.roles().includes('administrador'));
  protected readonly vistaResumenGlobal = signal(false);
  protected readonly cargandoResumen = signal(false);
  protected readonly resumenPorSucursal = signal<FilaVentasPorSucursal[]>([]);

  protected readonly fase = signal<FaseVenta>('armando');

  // ---- Búsqueda de producto -------------------------------------------------

  protected readonly textoBusqueda = signal('');
  protected readonly resultados = signal<VarianteBusqueda[]>([]);
  protected readonly indiceResaltado = signal(0);
  protected readonly buscando = signal(false);

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
    if (venta === null || recibido === null) return null;
    return Math.max(0, redondear(recibido - venta.total));
  });

  // ---- Comprobante -------------------------------------------------------------

  protected readonly comprobanteVisible = signal(false);
  protected readonly ventaConfirmada = signal<Venta | null>(null);
  protected readonly pagoConfirmado = signal<Pago | null>(null);
  protected readonly cambioConfirmado = signal<number | null>(null);

  // ---- Historial de hoy --------------------------------------------------------

  protected readonly historialVisible = signal(false);
  protected readonly historialHoy = signal<Venta[]>([]);
  protected readonly cargandoHistorial = signal(false);

  // ---- Devoluciones --------------------------------------------------------------

  protected readonly devolucionVisible = signal(false);
  protected readonly ventaParaDevolucion = signal<Venta | null>(null);
  protected readonly cantidadesDevolucion = signal<Record<number, number>>({});
  protected readonly registrandoDevolucion = signal(false);

  ngOnInit(): void {
    this.http.get<Empleado>(`${environment.apiUrl}/empleados/yo`).subscribe({
      next: (empleado) => {
        this.cargandoSucursal.set(false);
        // Un administrador sin ficha de sucursal es alcance global, no un
        // error de configuración (ver organizacion.politicas.sucursal_asignada
        // en el backend) -- no puede cobrar sin elegir una sucursal, pero sí
        // puede ver cómo le está yendo a cada una.
        if (empleado.sucursal_id === null && this.esAdministrador()) {
          this.cargarResumenGlobal();
          return;
        }
        this.sucursalId.set(empleado.sucursal_id);
        if (empleado.sucursal_id === null) {
          this.messageService.add({
            severity: 'warn',
            summary: 'No tenés una sucursal asignada',
            detail: 'Pedile a un administrador que te asigne una sucursal para poder cobrar.',
          });
        } else {
          // #inputBusqueda recién existe en el DOM ahora: está detrás del
          // @if que depende de cargandoSucursal/sucursalId (ver el
          // template), así que enfocarlo desde ngAfterViewInit no sirve —
          // en ese momento todavía se está mostrando "Cargando...".
          this.enfocarBusqueda();
        }
      },
      error: () => {
        this.cargandoSucursal.set(false);
        if (this.esAdministrador()) {
          this.cargarResumenGlobal();
          return;
        }
        this.noEsEmpleado.set(true);
      },
    });
  }

  /** `/reportes/ventas` ya agrega por sucursal del lado del servidor (CU-33)
   * y con alcance global trae todas en una sola consulta -- nada de pedir
   * sucursal por sucursal y sumar acá. */
  private cargarResumenGlobal(): void {
    this.vistaResumenGlobal.set(true);
    this.cargandoResumen.set(true);
    const hoy = fechaLocalIso(new Date());
    this.http
      .get<ReporteVentas>(`${environment.apiUrl}/reportes/ventas`, { params: { desde: hoy, hasta: hoy } })
      .subscribe({
        next: (reporte) => {
          this.cargandoResumen.set(false);
          this.resumenPorSucursal.set(reporte.por_sucursal);
        },
        error: () => this.cargandoResumen.set(false),
      });
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
    if (this.comprobanteVisible() || this.historialVisible() || this.devolucionVisible()) {
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
    this.http
      .get<VarianteBusqueda[]>(`${environment.apiUrl}/catalogo/variantes/buscar`, { params: { q: texto } })
      .subscribe({
        next: (resultados) => {
          this.buscando.set(false);
          if (resultados.length === 0) {
            this.messageService.add({ severity: 'warn', summary: 'Sin resultados', detail: texto });
            return;
          }
          if (resultados.length === 1) {
            this.agregarResultado(resultados[0]);
            return;
          }
          this.resultados.set(resultados);
          this.indiceResaltado.set(0);
        },
        error: () => this.buscando.set(false),
      });
  }

  seleccionarResultado(indice: number): void {
    this.indiceResaltado.set(indice);
    this.agregarResultado(this.resultados()[indice]);
  }

  private agregarResultado(variante: VarianteBusqueda): void {
    this.lineas.update((lineas) => {
      const existente = lineas.find((l) => l.variante_id === variante.variante_id);
      if (existente) {
        return lineas.map((l) =>
          l.variante_id === variante.variante_id ? { ...l, cantidad: l.cantidad + 1 } : l,
        );
      }
      return [
        ...lineas,
        {
          variante_id: variante.variante_id,
          descripcion: `${variante.producto_nombre} · ${variante.talla_codigo} · ${variante.color_nombre}`,
          precio_efectivo: variante.precio_efectivo,
          cantidad: 1,
        },
      ];
    });
    this.limpiarBusqueda();
  }

  limpiarBusqueda(): void {
    this.textoBusqueda.set('');
    this.resultados.set([]);
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

  quitarLinea(varianteId: number): void {
    this.lineas.update((lineas) => lineas.filter((l) => l.variante_id !== varianteId));
    this.enfocarBusqueda();
  }

  // ---- Reserva atendida -> venta -----------------------------------------------

  cargarReserva(): void {
    const codigo = this.codigoReserva().trim();
    const sucursalId = this.sucursalId();
    if (!codigo || sucursalId === null) return;
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

  seleccionarMetodoPago(metodo: MetodoPagoCaja): void {
    this.metodoPago.set(metodo);
    if (metodo === 'efectivo') {
      setTimeout(() => this.inputMontoRecibido?.nativeElement.focus());
    }
  }

  // ---- Paso 2: confirmar el pago -------------------------------------------------

  confirmarPago(): void {
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
    this.enfocarBusqueda();
  }

  // ---- Historial de ventas de hoy -----------------------------------------------

  abrirHistorial(): void {
    const sucursalId = this.sucursalId();
    if (sucursalId === null) return;
    this.historialVisible.set(true);
    this.cargandoHistorial.set(true);
    this.http.get<Venta[]>(`${environment.apiUrl}/ventas/sucursal/${sucursalId}`).subscribe({
      next: (ventas) => {
        // `venta.fecha` viene del backend en hora LOCAL del servidor, sin
        // offset (server_default now() de Postgres) -- comparar contra
        // toISOString() (UTC) desalinea la fecha cerca de medianoche. Se
        // arma "hoy" con el mismo calendario local, no UTC.
        const hoy = fechaLocalIso(new Date());
        this.historialHoy.set(
          ventas.filter((v) => v.fecha.slice(0, 10) === hoy).sort((a, b) => b.id - a.id),
        );
        this.cargandoHistorial.set(false);
      },
      error: () => this.cargandoHistorial.set(false),
    });
  }

  // ---- Devoluciones --------------------------------------------------------------

  abrirDevolucion(venta: Venta): void {
    this.ventaParaDevolucion.set(venta);
    this.cantidadesDevolucion.set(Object.fromEntries(venta.detalle.map((d) => [d.id, 0])));
    this.devolucionVisible.set(true);
  }

  actualizarCantidadDevolucion(detalleId: number, cantidad: number | null): void {
    this.cantidadesDevolucion.update((actual) => ({ ...actual, [detalleId]: cantidad ?? 0 }));
  }

  confirmarDevolucion(): void {
    const venta = this.ventaParaDevolucion();
    if (!venta) return;
    const detalle = Object.entries(this.cantidadesDevolucion())
      .filter(([, cantidad]) => cantidad > 0)
      .map(([id, cantidad]) => ({ venta_detalle_id: Number(id), cantidad }));
    if (detalle.length === 0) {
      this.messageService.add({ severity: 'warn', summary: 'Indicá al menos una cantidad a devolver' });
      return;
    }
    const payload: DevolucionCrear = { venta_id: venta.id, detalle };
    this.registrandoDevolucion.set(true);
    this.http.post(`${environment.apiUrl}/devoluciones`, payload).subscribe({
      next: () => {
        this.registrandoDevolucion.set(false);
        this.messageService.add({ severity: 'success', summary: 'Devolución registrada' });
        this.devolucionVisible.set(false);
        this.abrirHistorial();
      },
      error: () => this.registrandoDevolucion.set(false),
    });
  }
}

function redondear(valor: number): number {
  return Math.round(valor * 100) / 100;
}
