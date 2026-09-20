import { Routes } from '@angular/router';
import { authGuard, permisoGuard, staffGuard } from './core/guards';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./features/login/login.component').then((m) => m.LoginComponent),
  },
  {
    path: 'registro',
    loadComponent: () => import('./features/registro/registro.component').then((m) => m.RegistroComponent),
  },
  {
    path: 'recuperar',
    loadComponent: () =>
      import('./features/recuperar-password/solicitar-recuperacion.component').then(
        (m) => m.SolicitarRecuperacionComponent,
      ),
  },
  {
    path: 'restablecer',
    loadComponent: () =>
      import('./features/recuperar-password/restablecer-password.component').then(
        (m) => m.RestablecerPasswordComponent,
      ),
  },
  {
    // Tienda pública: catálogo, detalle, carrito y checkout -- ver
    // auth.interceptor.ts (RUTAS_SIN_TOKEN) para por qué también hay que
    // tocar el interceptor cuando se agrega una ruta pública nueva acá
    // (catalogo/producto lo son; carrito/checkout/mis-compras exigen
    // login vía authGuard, así que sí llevan token).
    path: '',
    loadComponent: () => import('./features/tienda/tienda-shell.component').then((m) => m.TiendaShellComponent),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'catalogo' },
      {
        path: 'catalogo',
        loadComponent: () =>
          import('./features/catalogo-publico/catalogo-publico.component').then((m) => m.CatalogoPublicoComponent),
      },
      {
        path: 'producto/:id',
        loadComponent: () =>
          import('./features/tienda/presentation/producto-detalle.component').then(
            (m) => m.ProductoDetalleComponent,
          ),
      },
      {
        path: 'carrito',
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/tienda/presentation/carrito.component').then((m) => m.CarritoComponent),
      },
      {
        path: 'reserva/confirmar',
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/tienda/presentation/reserva-confirmar.component').then(
            (m) => m.ReservaConfirmarComponent,
          ),
      },
      {
        path: 'mis-reservas',
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/tienda/presentation/mis-reservas.component').then((m) => m.MisReservasComponent),
      },
      {
        path: 'mis-reservas/:id',
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/tienda/presentation/reserva-detalle.component').then(
            (m) => m.ReservaDetalleComponent,
          ),
      },
      {
        path: 'checkout/entrega',
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/tienda/presentation/checkout-entrega.component').then(
            (m) => m.CheckoutEntregaComponent,
          ),
      },
      {
        path: 'checkout/pago',
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/tienda/presentation/checkout-pago.component').then((m) => m.CheckoutPagoComponent),
      },
      {
        path: 'checkout/estado/:pagoId',
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/tienda/presentation/checkout-estado.component').then(
            (m) => m.CheckoutEstadoComponent,
          ),
      },
      {
        path: 'mis-compras',
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/tienda/presentation/mis-compras.component').then((m) => m.MisComprasComponent),
      },
      {
        path: 'mis-compras/:id',
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/tienda/presentation/compra-detalle.component').then((m) => m.CompraDetalleComponent),
      },
    ],
  },
  {
    // Back office: admin, encargado, cajero. `staffGuard` (no `authGuard`)
    // frena acá a un cliente autenticado antes de que vea cualquier
    // pantalla de administración, aunque escriba la URL a mano.
    path: '',
    loadComponent: () => import('./layout/layout.component').then((m) => m.LayoutComponent),
    canActivate: [staffGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'usuarios',
        canActivate: [permisoGuard('usuarios.gestionar')],
        loadComponent: () =>
          import('./features/usuarios/usuarios.component').then((m) => m.UsuariosComponent),
      },
      {
        path: 'roles',
        canActivate: [permisoGuard('roles.gestionar')],
        loadComponent: () => import('./features/roles/roles.component').then((m) => m.RolesComponent),
      },
      {
        path: 'ciudades',
        canActivate: [permisoGuard('organizacion.gestionar')],
        loadComponent: () =>
          import('./features/ciudades/ciudades.component').then((m) => m.CiudadesComponent),
      },
      {
        path: 'sucursales',
        canActivate: [permisoGuard('organizacion.gestionar')],
        loadComponent: () =>
          import('./features/sucursales/sucursales.component').then((m) => m.SucursalesComponent),
      },
      {
        path: 'empleados',
        canActivate: [permisoGuard('organizacion.gestionar')],
        loadComponent: () =>
          import('./features/empleados/empleados.component').then((m) => m.EmpleadosComponent),
      },
      {
        path: 'probador',
        canActivate: [permisoGuard('probador.gestionar')],
        loadComponent: () =>
          import('./features/probador/anclajes-editor.component').then((m) => m.AnclajesEditorComponent),
      },
      {
        path: 'inventario',
        canActivate: [permisoGuard('inventario.ver')],
        loadComponent: () =>
          import('./features/inventario/inventario.component').then((m) => m.InventarioComponent),
      },
      {
        path: 'productos',
        canActivate: [permisoGuard('catalogo.gestionar')],
        loadComponent: () =>
          import('./features/productos/productos.component').then((m) => m.ProductosComponent),
      },
      {
        path: 'categorias',
        canActivate: [permisoGuard('catalogo.gestionar')],
        loadComponent: () =>
          import('./features/categorias/categorias.component').then((m) => m.CategoriasComponent),
      },
      {
        path: 'tallas',
        canActivate: [permisoGuard('catalogo.gestionar')],
        loadComponent: () => import('./features/tallas/tallas.component').then((m) => m.TallasComponent),
      },
      {
        path: 'colores',
        canActivate: [permisoGuard('catalogo.gestionar')],
        loadComponent: () => import('./features/colores/colores.component').then((m) => m.ColoresComponent),
      },
      {
        path: 'temporadas',
        canActivate: [permisoGuard('catalogo.gestionar')],
        loadComponent: () =>
          import('./features/temporadas/temporadas.component').then((m) => m.TemporadasComponent),
      },
      {
        path: 'colecciones',
        canActivate: [permisoGuard('catalogo.gestionar')],
        loadComponent: () =>
          import('./features/colecciones/colecciones.component').then((m) => m.ColeccionesComponent),
      },
      {
        path: 'proveedores',
        canActivate: [permisoGuard('abastecimiento.gestionar')],
        loadComponent: () =>
          import('./features/proveedores/proveedores.component').then((m) => m.ProveedoresComponent),
      },
      {
        path: 'reservas',
        canActivate: [permisoGuard('reservas.gestionar_sucursal')],
        loadComponent: () =>
          import('./features/reservas/reservas.component').then((m) => m.ReservasComponent),
      },
      {
        path: 'reportes',
        canActivate: [permisoGuard('reportes.ver')],
        loadComponent: () =>
          import('./features/reportes/reportes.component').then((m) => m.ReportesComponent),
      },
      {
        path: 'caja',
        canActivate: [permisoGuard('ventas.presencial')],
        loadComponent: () => import('./features/caja/caja.component').then((m) => m.CajaComponent),
      },
      {
        path: 'promociones',
        canActivate: [permisoGuard('ventas.gestionar')],
        loadComponent: () =>
          import('./features/promociones/promociones.component').then((m) => m.PromocionesComponent),
      },
      {
        path: 'envios',
        canActivate: [permisoGuard('entregas.gestionar')],
        loadComponent: () => import('./features/envios/envios.component').then((m) => m.EnviosComponent),
      },
      {
        path: 'zonas-envio',
        canActivate: [permisoGuard('entregas.gestionar')],
        loadComponent: () =>
          import('./features/zonas-envio/zonas-envio.component').then((m) => m.ZonasEnvioComponent),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
