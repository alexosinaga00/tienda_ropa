import { DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';import { DireccionCliente, ZonaEnvio } from '../../../core/models/entregas.models';
import { Sucursal } from '../../../core/models/organizacion.models';
import { CarritoService } from '../data/carrito.service';
import { DireccionesService } from '../data/direcciones.service';
import { DisponibilidadService } from '../data/disponibilidad.service';
import { CheckoutService, TipoEntrega } from '../state/checkout.service';

@Component({
  selector: 'app-checkout-entrega',
  standalone: true,
  imports: [ReactiveFormsModule, ButtonModule, DialogModule, InputTextModule, SelectModule, DecimalPipe],
  templateUrl: './checkout-entrega.component.html',
  styleUrl: './checkout-entrega.component.scss',
})
export class CheckoutEntregaComponent implements OnInit {
  protected readonly checkoutService = inject(CheckoutService);
  private readonly carritoService = inject(CarritoService);
  private readonly disponibilidadService = inject(DisponibilidadService);
  private readonly direccionesService = inject(DireccionesService);
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);

  private readonly todasConStock = signal<Sucursal[]>([]);
  /** Para retirar no sirve un depósito (no recibe clientes); un envío sí lo puede despachar. */
  protected readonly sucursales = computed(() =>
    this.checkoutService.tipoEntrega() === 'retiro'
      ? this.todasConStock().filter((s) => !s.es_deposito)
      : this.todasConStock(),
  );
  protected readonly direcciones = signal<DireccionCliente[]>([]);
  protected readonly zonas = signal<ZonaEnvio[]>([]);
  protected readonly cargandoSucursales = signal(true);
  protected readonly cargandoDirecciones = signal(false);
  protected readonly cotizando = signal(false);
  protected readonly dialogoVisible = signal(false);

  protected readonly formulario = this.fb.nonNullable.group({
    zonaEnvioId: this.fb.control<number | null>(null),
    alias: [''],
    direccion: ['', Validators.required],
    referencia: [''],
  });

  ngOnInit(): void {
    if (this.carritoService.lineas().length === 0) {
      this.router.navigate(['/carrito']);
      return;
    }
    this.cargarSucursales();
  }

  elegirTipoEntrega(tipo: TipoEntrega): void {
    this.checkoutService.elegirTipoEntrega(tipo);
    if (tipo === 'domicilio' && this.direcciones().length === 0 && !this.cargandoDirecciones()) {
      this.cargarDirecciones();
    }
  }

  elegirDireccion(direccionId: number): void {
    this.checkoutService.elegirDireccion(direccionId);
    this.cotizando.set(true);
    this.direccionesService.cotizar({ direccion_id: direccionId, cantidad_prendas: this.totalPrendas() }).subscribe({
      next: (cotizacion) => {
        this.checkoutService.fijarCotizacion(cotizacion);
        this.cotizando.set(false);
      },
      error: () => this.cotizando.set(false),
    });
  }

  elegirSucursal(id: number): void {
    this.checkoutService.elegirSucursal(id);
  }

  abrirDialogoDireccion(): void {
    this.formulario.reset({ zonaEnvioId: null, alias: '', direccion: '', referencia: '' });
    if (this.zonas().length === 0) {
      this.direccionesService.listarZonas().subscribe((zonas) => this.zonas.set(zonas));
    }
    this.dialogoVisible.set(true);
  }

  guardarDireccion(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }
    const { zonaEnvioId, alias, direccion, referencia } = this.formulario.getRawValue();
    this.direccionesService
      .crearDireccion({
        zona_envio_id: zonaEnvioId ?? undefined,
        alias: alias || undefined,
        direccion,
        referencia: referencia || undefined,
      })
      .subscribe((nueva) => {
        this.dialogoVisible.set(false);
        this.direcciones.update((actual) => [...actual, nueva]);
        this.elegirDireccion(nueva.id);
      });
  }

  continuar(): void {
    if (this.checkoutService.listoParaPagar()) {
      this.router.navigate(['/checkout/pago']);
    }
  }

  private cargarSucursales(): void {
    const lineas = this.carritoService.lineas().map((l) => ({ varianteId: l.variante_id, cantidad: l.cantidad }));
    this.cargandoSucursales.set(true);
    this.disponibilidadService.sucursalesConStock(lineas).subscribe({
      next: (sucursales) => {
        this.todasConStock.set(sucursales);
        this.cargandoSucursales.set(false);
      },
      error: () => this.cargandoSucursales.set(false),
    });
  }

  private cargarDirecciones(): void {
    this.cargandoDirecciones.set(true);
    this.direccionesService.listarMisDirecciones().subscribe({
      next: (direcciones) => {
        this.direcciones.set(direcciones);
        this.cargandoDirecciones.set(false);
      },
      error: () => this.cargandoDirecciones.set(false),
    });
  }

  private totalPrendas(): number {
    return this.carritoService.lineas().reduce((acumulado, linea) => acumulado + linea.cantidad, 0);
  }
}
