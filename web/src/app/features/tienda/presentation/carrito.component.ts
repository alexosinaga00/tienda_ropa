import { DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { CarritoResumen } from '../../../core/models/ventas.models';
import { CarritoService } from '../data/carrito.service';
import { CheckoutService } from '../state/checkout.service';

@Component({
  selector: 'app-carrito',
  standalone: true,
  imports: [RouterLink, DecimalPipe],
  templateUrl: './carrito.component.html',
  styleUrl: './carrito.component.scss',
})
export class CarritoComponent implements OnInit {
  protected readonly carritoService = inject(CarritoService);
  private readonly checkoutService = inject(CheckoutService);
  private readonly router = inject(Router);

  protected readonly cargando = signal(true);
  protected readonly resumen = signal<CarritoResumen | null>(null);
  /** El backend rechaza la compra mientras haya prendas dadas de baja en el carrito. */
  protected readonly hayNoDisponibles = computed(() => this.carritoService.lineas().some((l) => !l.disponible));

  ngOnInit(): void {
    this.recargar();
  }

  private recargar(): void {
    this.cargando.set(true);
    this.carritoService.cargar().subscribe({
      next: () => {
        this.cargando.set(false);
        this.cargarResumen();
      },
      error: () => this.cargando.set(false),
    });
  }

  private cargarResumen(): void {
    if (this.carritoService.lineas().length === 0) {
      this.resumen.set(null);
      return;
    }
    this.carritoService.resumen().subscribe({
      next: (resumen) => this.resumen.set(resumen),
      error: () => this.resumen.set(null),
    });
  }

  aumentar(varianteId: number, cantidadActual: number): void {
    this.carritoService.actualizarCantidad(varianteId, cantidadActual + 1).subscribe(() => this.cargarResumen());
  }

  disminuir(varianteId: number, cantidadActual: number): void {
    if (cantidadActual <= 1) {
      this.quitar(varianteId);
      return;
    }
    this.carritoService.actualizarCantidad(varianteId, cantidadActual - 1).subscribe(() => this.cargarResumen());
  }

  quitar(varianteId: number): void {
    this.carritoService.quitar(varianteId).subscribe(() => this.cargarResumen());
  }

  continuar(): void {
    if (this.hayNoDisponibles()) return;
    this.checkoutService.reiniciar();
    this.router.navigate(['/checkout/entrega']);
  }
}
