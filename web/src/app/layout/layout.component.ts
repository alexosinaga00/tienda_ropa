import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { PopoverModule } from 'primeng/popover';
import { filter } from 'rxjs';
import { AuthService } from '../core/auth.service';
import { NotificacionesService } from '../core/notificaciones.service';

const INTERVALO_NOTIFICACIONES_MS = 20_000;

interface ItemMenu {
  etiqueta: string;
  icono: string;
  ruta: string;
  permiso?: string;
}

interface GrupoMenu {
  id: string;
  etiqueta: string;
  icono: string;
  items: ItemMenu[];
}

const ITEMS_INICIO: ItemMenu[] = [
  { etiqueta: 'Dashboard', icono: 'pi pi-home', ruta: '/dashboard' },
  { etiqueta: 'Reportes', icono: 'pi pi-chart-bar', ruta: '/reportes', permiso: 'reportes.ver' },
];

const GRUPOS_MENU: GrupoMenu[] = [
  {
    id: 'organizacion',
    etiqueta: 'Organización',
    icono: 'pi pi-sitemap',
    items: [
      { etiqueta: 'Usuarios', icono: 'pi pi-users', ruta: '/usuarios', permiso: 'usuarios.gestionar' },
      { etiqueta: 'Roles', icono: 'pi pi-shield', ruta: '/roles', permiso: 'roles.gestionar' },
      { etiqueta: 'Empleados', icono: 'pi pi-id-card', ruta: '/empleados', permiso: 'organizacion.gestionar' },
      { etiqueta: 'Ciudades', icono: 'pi pi-map', ruta: '/ciudades', permiso: 'organizacion.gestionar' },
      { etiqueta: 'Sucursales', icono: 'pi pi-building', ruta: '/sucursales', permiso: 'organizacion.gestionar' },
    ],
  },
  {
    id: 'catalogo',
    etiqueta: 'Catálogo',
    icono: 'pi pi-tag',
    items: [
      { etiqueta: 'Productos', icono: 'pi pi-tag', ruta: '/productos', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Categorías', icono: 'pi pi-sitemap', ruta: '/categorias', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Tallas', icono: 'pi pi-tags', ruta: '/tallas', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Colores', icono: 'pi pi-palette', ruta: '/colores', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Temporadas', icono: 'pi pi-sun', ruta: '/temporadas', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Colecciones', icono: 'pi pi-images', ruta: '/colecciones', permiso: 'catalogo.gestionar' },
    ],
  },
  {
    id: 'ventas',
    etiqueta: 'Ventas',
    icono: 'pi pi-shopping-cart',
    items: [
      { etiqueta: 'Caja', icono: 'pi pi-shopping-cart', ruta: '/caja', permiso: 'ventas.presencial' },
      { etiqueta: 'Promociones', icono: 'pi pi-percentage', ruta: '/promociones', permiso: 'ventas.gestionar' },
      {
        etiqueta: 'Reservas',
        icono: 'pi pi-calendar-clock',
        ruta: '/reservas',
        permiso: 'reservas.gestionar_sucursal',
      },
    ],
  },
];

const ITEMS_FIN: ItemMenu[] = [
  { etiqueta: 'Inventario', icono: 'pi pi-box', ruta: '/inventario', permiso: 'inventario.ver' },
  { etiqueta: 'Proveedores', icono: 'pi pi-truck', ruta: '/proveedores', permiso: 'abastecimiento.gestionar' },
  { etiqueta: 'Envíos', icono: 'pi pi-map-marker', ruta: '/envios', permiso: 'entregas.gestionar' },
  { etiqueta: 'Zonas de envío', icono: 'pi pi-send', ruta: '/zonas-envio', permiso: 'entregas.gestionar' },
  { etiqueta: 'Probador', icono: 'pi pi-camera', ruta: '/probador', permiso: 'probador.gestionar' },
];

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, ButtonModule, PopoverModule],
  templateUrl: './layout.component.html',
  styleUrl: './layout.component.scss',
})
export class LayoutComponent implements OnInit, OnDestroy {
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly notificacionesService = inject(NotificacionesService);

  protected readonly usuario = this.authService.usuario;

  private readonly puedeVer = (item: ItemMenu) => !item.permiso || this.authService.tienePermiso(item.permiso);

  protected readonly itemsInicio = computed(() => ITEMS_INICIO.filter(this.puedeVer));
  protected readonly itemsFin = computed(() => ITEMS_FIN.filter(this.puedeVer));
  protected readonly gruposMenu = computed(() =>
    GRUPOS_MENU.map((grupo) => ({ ...grupo, items: grupo.items.filter(this.puedeVer) })).filter(
      (grupo) => grupo.items.length > 0,
    ),
  );

  private readonly gruposAbiertos = signal<ReadonlySet<string>>(new Set());

  private intervalo?: ReturnType<typeof setInterval>;

  ngOnInit(): void {
    this.notificacionesService.cargar().subscribe();
    // ~20s: "casi en tiempo real" sin WebSockets, mismo mecanismo de
    // polling que ya usa checkout-estado.component.ts para el pago.
    this.intervalo = setInterval(() => this.notificacionesService.cargar().subscribe(), INTERVALO_NOTIFICACIONES_MS);

    this.abrirGrupoDeRuta(this.router.url);
    this.router.events
      .pipe(
        filter((evento): evento is NavigationEnd => evento instanceof NavigationEnd),
        // Sin esto, cada vez que un usuario staff navega del back office a
        // la tienda pública y vuelve (LayoutComponent se destruye y se
        // recrea), esta suscripción vieja queda viva para siempre y sigue
        // ejecutando abrirGrupoDeRuta sobre un componente ya destruido.
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((evento) => this.abrirGrupoDeRuta(evento.urlAfterRedirects));
  }

  ngOnDestroy(): void {
    clearInterval(this.intervalo);
  }

  private abrirGrupoDeRuta(url: string): void {
    const grupo = GRUPOS_MENU.find((g) => g.items.some((item) => url.startsWith(item.ruta)));
    if (!grupo) return;
    this.gruposAbiertos.update((set) => new Set(set).add(grupo.id));
  }

  toggleGrupo(id: string): void {
    this.gruposAbiertos.update((set) => {
      const nuevo = new Set(set);
      nuevo.has(id) ? nuevo.delete(id) : nuevo.add(id);
      return nuevo;
    });
  }

  estaAbierto(id: string): boolean {
    return this.gruposAbiertos().has(id);
  }

  marcarLeida(notificacionId: number): void {
    this.notificacionesService.marcarLeida(notificacionId).subscribe();
  }

  cerrarSesion(): void {
    this.authService.logout();
  }
}
