import { Component, DestroyRef, ElementRef, HostListener, computed, effect, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, NavigationStart, Router, RouterLink, RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { PushWebService } from '../../core/push/push-web.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { IndicadorConexionComponent } from '../../shared/indicador-conexion/indicador-conexion.component';
import { MarcaComponent } from '../../shared/marca/marca.component';
import { AvisoPedidosSinConexionComponent } from './aviso-pedidos-sin-conexion.component';
import { CarritoService } from './data/carrito.service';
import { irAColeccion } from './ir-a-coleccion';
import { PedidosSinConexionService } from './state/pedidos-sin-conexion.service';
import { ReservaCarritoService } from './state/reserva-carrito.service';
import { TiendaActualService } from './state/tienda-actual.service';

/** Por debajo de este ancho la cabecera pasa a menú desplegable (ver el .scss). */
const ANCHO_MOVIL = '(max-width: 960px)';

@Component({
  selector: 'app-tienda-shell',
  standalone: true,
  imports: [
    RouterLink,
    RouterOutlet,
    MarcaComponent,
    IconoComponent,
    IndicadorConexionComponent,
    AvisoPedidosSinConexionComponent,
  ],
  templateUrl: './tienda-shell.component.html',
  styleUrl: './tienda-shell.component.scss',
})
export class TiendaShellComponent {
  protected readonly authService = inject(AuthService);
  protected readonly carritoService = inject(CarritoService);
  protected readonly reservaCarritoService = inject(ReservaCarritoService);
  protected readonly tienda = inject(TiendaActualService);
  private readonly router = inject(Router);
  private readonly push = inject(PushWebService);

  // La sesión vale para UNA empresa: un usuario de otra tienda ve esta como visitante.
  protected readonly sesionDeEstaTienda = computed(
    () => this.authService.estaAutenticado() && this.authService.empresaCodigo() === this.tienda.codigo(),
  );

  protected readonly nombreTienda = computed(() => this.tienda.empresa()?.nombre ?? 'FashionStore');

  // Solo se pasa a la marca un logo http(s); si no carga, `fs-marca` cae al monograma.
  protected readonly logoUrl = computed(() => {
    const url = this.tienda.empresa()?.logo_url;
    return url && /^https?:\/\//i.test(url) ? url : null;
  });

  // Ruta actual sin query ni fragmento: decide qué cabecera se muestra.
  private readonly rutaActual = signal(this.sinParametros(this.router.url));
  private readonly base = computed(() => this.tienda.ruta().join('/'));

  /** La portada es el catálogo (la raíz de la tienda): cabecera oscura que continúa el hero. */
  protected readonly esPortada = computed(() => {
    const ruta = this.rutaActual().replace(/\/+$/, '');
    return ruta === this.base();
  });

  /** En los pasos de compra la cabecera se reduce a la marca y "Compra segura". */
  protected readonly esCheckout = computed(() => this.rutaActual().startsWith(`${this.base()}/checkout`));

  protected readonly enlacePortada = computed(() => this.base());

  /** En la pantalla de pedidos sin conexión no hace falta la franja que ya cuenta lo mismo. */
  protected readonly enPedidosSinConexion = computed(() => this.rutaActual().endsWith('/pedidos-sin-conexion'));

  // El monograma y el nombre de la marca no caben en 390 px: versión pequeña en celular.
  protected readonly esMovil = signal(this.coincideMovil());

  // Menú colapsado en celular (ver el .scss): en escritorio los enlaces van en la fila.
  protected readonly menuAbierto = signal(false);
  private readonly botonMenu = viewChild<ElementRef<HTMLButtonElement>>('botonMenu');

  // Diálogo de salida con pedidos sin enviar.
  protected readonly cola = inject(PedidosSinConexionService);
  protected readonly dialogoSalida = signal(false);
  protected readonly saliendo = signal(false);
  private readonly botonConservar = viewChild<ElementRef<HTMLButtonElement>>('botonConservar');

  constructor() {
    // "Conservarlos" es lo predeterminado: el foco cae ahí al abrir el diálogo.
    effect(() => {
      const boton = this.botonConservar();
      if (this.dialogoSalida() && boton) boton.nativeElement.focus();
    });

    effect(() => {
      if (this.sesionDeEstaTienda()) {
        this.carritoService.cargar().subscribe({ error: () => undefined });
        // Si los avisos del navegador ya estaban activados, quedan al día y escuchando (jamás pide permiso).
        void this.push.sincronizarSiActivo();
      } else {
        this.carritoService.limpiar();
      }
    });

    // Sin esto, el menú se queda abierto al navegar (tocas "Mi cuenta" y la
    // próxima pantalla arranca con el menú tapando el contenido).
    this.router.events.pipe(takeUntilDestroyed()).subscribe((evento) => {
      if (evento instanceof NavigationStart) this.menuAbierto.set(false);
      if (evento instanceof NavigationEnd) this.rutaActual.set(this.sinParametros(evento.urlAfterRedirects));
    });

    if (typeof matchMedia === 'function') {
      const consulta = matchMedia(ANCHO_MOVIL);
      const alCambiar = (e: MediaQueryListEvent) => this.esMovil.set(e.matches);
      consulta.addEventListener?.('change', alCambiar);
      inject(DestroyRef).onDestroy(() => consulta.removeEventListener?.('change', alCambiar));
    }
  }

  /** Escape cierra el menú de celular y devuelve el foco al botón que lo abrió. */
  @HostListener('document:keydown.escape')
  protected cerrarMenuConEscape(): void {
    if (this.dialogoSalida()) {
      this.cancelarSalida();
      return;
    }
    if (!this.menuAbierto()) return;
    this.menuAbierto.set(false);
    this.botonMenu()?.nativeElement.focus();
  }

  alternarMenu(): void {
    this.menuAbierto.update((abierto) => !abierto);
  }

  /**
   * "Salir" del cliente. Si hay pedidos hechos sin conexión que todavía no salieron, pregunta qué hacer con ellos; sin
   * pedidos sin enviar, sale directo. El cierre FORZADO (401, sesión vencida) no pasa por aquí: llama a `logout()` del
   * servicio de sesión y ahí los pedidos se conservan sin preguntar.
   */
  cerrarSesion(): void {
    this.menuAbierto.set(false);
    if (this.cola.pendientes().length > 0) {
      this.dialogoSalida.set(true);
      return;
    }
    this.authService.logout();
  }

  /** "Conservarlos": salir dejando los pedidos; se envían cuando vuelva a entrar la misma cuenta. */
  conservarYSalir(): void {
    this.dialogoSalida.set(false);
    this.authService.logout();
  }

  /** "Borrarlos y salir": los pedidos sin enviar se borran del equipo junto con el resto. */
  async borrarYSalir(): Promise<void> {
    if (this.saliendo()) return;
    this.saliendo.set(true);
    await this.cola.borrarTodoDeEstaCuenta();
    this.saliendo.set(false);
    this.dialogoSalida.set(false);
    this.authService.logout();
  }

  /** Cerrar el diálogo sin salir (Escape o tocar fuera): se sigue con la sesión abierta. */
  cancelarSalida(): void {
    if (!this.saliendo()) this.dialogoSalida.set(false);
  }

  /** "Colección" y la lupa de la portada: bajan a la sección del catálogo (y enfocan el buscador). */
  irAColeccion(evento: Event, enfocarBuscador = false): void {
    this.menuAbierto.set(false);
    irAColeccion(evento, enfocarBuscador);
  }

  private sinParametros(url: string): string {
    return url.split(/[?#]/)[0];
  }

  private coincideMovil(): boolean {
    return typeof matchMedia === 'function' && matchMedia(ANCHO_MOVIL).matches;
  }
}
