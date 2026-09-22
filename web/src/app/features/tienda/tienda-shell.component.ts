import { Component, effect, inject, signal } from '@angular/core';
import { NavigationStart, Router, RouterLink, RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { CarritoService } from './data/carrito.service';
import { ReservaCarritoService } from './state/reserva-carrito.service';

@Component({
  selector: 'app-tienda-shell',
  standalone: true,
  imports: [RouterLink, RouterOutlet],
  templateUrl: './tienda-shell.component.html',
  styleUrl: './tienda-shell.component.scss',
})
export class TiendaShellComponent {
  protected readonly authService = inject(AuthService);
  protected readonly carritoService = inject(CarritoService);
  protected readonly reservaCarritoService = inject(ReservaCarritoService);

  // Menú de "Iniciar sesión" / "Mis compras" etc. colapsado en celular: ver
  // tienda-shell.component.scss, se muestra en fila completa desde 760px y
  // no hace falta ni el botón ni este estado.
  protected readonly menuAbierto = signal(false);

  constructor() {
    effect(() => {
      if (this.authService.estaAutenticado()) {
        this.carritoService.cargar().subscribe({ error: () => undefined });
      } else {
        this.carritoService.limpiar();
      }
    });

    // Sin esto, el menú se queda abierto al navegar (tocás "Mis compras" y
    // la próxima pantalla arranca con el menú tapando el contenido).
    const router = inject(Router);
    router.events.subscribe((evento) => {
      if (evento instanceof NavigationStart) this.menuAbierto.set(false);
    });
  }

  alternarMenu(): void {
    this.menuAbierto.update((abierto) => !abierto);
  }

  cerrarSesion(): void {
    this.menuAbierto.set(false);
    this.authService.logout();
  }
}
