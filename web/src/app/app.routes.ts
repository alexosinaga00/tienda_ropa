import { Routes } from '@angular/router';
import {
  authGuard,
  cualquierPermisoGuard,
  permisoGuard,
  staffGuard,
  superadminGuard,
  tiendaSesionGuard,
  todosLosPermisosGuard,
} from './core/guards';
import { tiendaResolver } from './features/tienda/tienda.resolver';
import { RUTAS_LEGACY } from './features/tienda/rutas-legacy';

// Guards de las pantallas privadas de una tienda (carrito, checkout, mis-*).
const GUARDS_PRIVADOS_DE_TIENDA = [authGuard, tiendaSesionGuard];

export const routes: Routes = [
  {
    // PWA (E13): a donde lleva el enrutador una pantalla que no cargó sin conexión. Sin guardas.
    path: 'sin-conexion',
    loadComponent: () => import('./features/sin-conexion/sin-conexion.component').then((m) => m.SinConexionComponent),
  },
  {
    // Página de la plataforma: tarjetas de las tiendas activas y acceso del personal.
    path: '',
    pathMatch: 'full',
    loadComponent: () =>
      import('./features/plataforma-home/plataforma-home.component').then((m) => m.PlataformaHomeComponent),
  },
  {
    // Contratación de un plan (prueba gratis de 14 días o compra con PayPal). Pública y sin guardas: quien llega aún
    // no tiene empresa ni sesión. Query: ?plan=<codigo>&modo=prueba|pago&periodo=mensual|anual.
    path: 'contratar',
    pathMatch: 'full',
    loadComponent: () => import('./features/contratar/contratar.component').then((m) => m.ContratarComponent),
  },
  {
    // Adonde PayPal devuelve al comprador: ?pedido=<token> (y &cancelado=1 si canceló). Cierra el pedido una vez.
    path: 'contratar/retorno',
    pathMatch: 'full',
    loadComponent: () =>
      import('./features/contratar/retorno/contratar-retorno.component').then((m) => m.ContratarRetornoComponent),
  },
  {
    // Login del personal: empresa + correo + clave (o administrador de la plataforma).
    path: 'admin/login',
    data: { modo: 'personal' },
    loadComponent: () => import('./features/login/login.component').then((m) => m.LoginComponent),
  },
  // Dirección de antes: el returnTo y demás parámetros se conservan en la redirección.
  { path: 'login', pathMatch: 'full', redirectTo: 'admin/login' },
  {
    // Recuperar la contraseña del personal (pide también la empresa).
    path: 'admin/recuperar',
    loadComponent: () =>
      import('./features/recuperar-password/solicitar-recuperacion.component').then(
        (m) => m.SolicitarRecuperacionComponent,
      ),
  },
  {
    // Compatibilidad: el enlace del correo de recuperación trae el token, que
    // ya identifica a la empresa y al usuario. También existe /t/:codigo/restablecer.
    path: 'restablecer',
    loadComponent: () =>
      import('./features/recuperar-password/restablecer-password.component').then(
        (m) => m.RestablecerPasswordComponent,
      ),
  },
  // Direcciones de antes de las tiendas por empresa: llevan a la última tienda (o a "/").
  ...RUTAS_LEGACY,
  {
    // Tienda pública de una empresa: /t/<codigo>. El resolver busca la empresa
    // por su código; TiendaRaizComponent muestra "no encontrada" / "no disponible"
    // o la tienda. Las llamadas públicas (/public/{codigo}/...) no llevan token
    // -- ver auth.interceptor.ts (RUTAS_SIN_TOKEN); las privadas (carrito,
    // checkout, mis-*) exigen login vía authGuard y la empresa sale del JWT.
    path: 't/:codigo',
    loadComponent: () => import('./features/tienda/tienda-raiz.component').then((m) => m.TiendaRaizComponent),
    resolve: { tienda: tiendaResolver },
    children: [
      {
        path: 'login',
        data: { modo: 'cliente' },
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
        path: '',
        loadComponent: () =>
          import('./features/tienda/tienda-shell.component').then((m) => m.TiendaShellComponent),
        children: [
          {
            // La portada de la tienda es su catálogo (sin redirect a 'catalogo').
            path: '',
            pathMatch: 'full',
            loadComponent: () =>
              import('./features/catalogo-publico/catalogo-publico.component').then(
                (m) => m.CatalogoPublicoComponent,
              ),
          },
          // Enlaces viejos a /t/<codigo>/catalogo.
          { path: 'catalogo', pathMatch: 'full', redirectTo: '' },
          {
            path: 'producto/:id',
            loadComponent: () =>
              import('./features/tienda/presentation/producto-detalle.component').then(
                (m) => m.ProductoDetalleComponent,
              ),
          },
          {
            path: 'carrito',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/carrito.component').then((m) => m.CarritoComponent),
          },
          {
            path: 'reserva/confirmar',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/reserva-confirmar.component').then(
                (m) => m.ReservaConfirmarComponent,
              ),
          },
          {
            path: 'mis-reservas',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/mis-reservas.component').then((m) => m.MisReservasComponent),
          },
          {
            path: 'mis-reservas/:id',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/reserva-detalle.component').then(
                (m) => m.ReservaDetalleComponent,
              ),
          },
          {
            path: 'checkout/entrega',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/checkout-entrega.component').then(
                (m) => m.CheckoutEntregaComponent,
              ),
          },
          {
            path: 'checkout/pago',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/checkout-pago.component').then(
                (m) => m.CheckoutPagoComponent,
              ),
          },
          {
            // Pago con el PayPal guardado cuando no hay conexión (el pedido queda en cola y se cobra al volver la red).
            path: 'checkout/sin-conexion',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/checkout-sin-conexion.component').then(
                (m) => m.CheckoutSinConexionComponent,
              ),
          },
          {
            path: 'mi-cuenta',
            pathMatch: 'full',
            redirectTo: 'mi-cuenta/metodo-pago',
          },
          {
            path: 'mi-cuenta/metodo-pago',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/metodo-pago.component').then((m) => m.MetodoPagoComponent),
          },
          {
            // A donde PayPal devuelve al cliente tras autorizar (o cancelar) el guardado de su método de pago.
            path: 'mi-cuenta/paypal-guardado',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/paypal-guardado.component').then((m) => m.PaypalGuardadoComponent),
          },
          {
            path: 'mi-cuenta/pedidos-sin-conexion',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/pedidos-sin-conexion.component').then(
                (m) => m.PedidosSinConexionComponent,
              ),
          },
          {
            path: 'checkout/estado/:pagoId',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/checkout-estado.component').then(
                (m) => m.CheckoutEstadoComponent,
              ),
          },
          {
            path: 'mis-compras',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/mis-compras.component').then((m) => m.MisComprasComponent),
          },
          {
            path: 'mis-compras/:id',
            canActivate: GUARDS_PRIVADOS_DE_TIENDA,
            loadComponent: () =>
              import('./features/tienda/presentation/compra-detalle.component').then(
                (m) => m.CompraDetalleComponent,
              ),
          },
        ],
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
          import('./features/probador/assets-probador.component').then((m) => m.AssetsProbadorComponent),
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
        // Reportes en lenguaje natural (E17). El plan sin la función ve la pantalla en modo explicativo.
        path: 'reportes-ia',
        canActivate: [permisoGuard('reportes.ver')],
        loadComponent: () =>
          import('./features/reportes-ia/reportes-ia.component').then((m) => m.ReportesIaComponent),
      },
      {
        // Dashboard del Machine Learning (E17b): solo el administrador de una empresa con el plan que lo incluye.
        path: 'analitica',
        // Alcance global (`organizacion.gestionar`) además de reportes.ver: el servidor responde 403 a quien solo ve su sucursal.
        canActivate: [todosLosPermisosGuard('reportes.ver', 'organizacion.gestionar')],
        loadComponent: () => import('./features/analitica/analitica.component').then((m) => m.AnaliticaComponent),
      },
      {
        path: 'caja',
        canActivate: [permisoGuard('ventas.presencial')],
        loadComponent: () => import('./features/caja/caja.component').then((m) => m.CajaComponent),
      },
      {
        // Modo sin conexión (E14): el catálogo descargado en este equipo. Lo usa quien vende o gestiona reservas.
        path: 'catalogo-local',
        canActivate: [cualquierPermisoGuard('ventas.presencial', 'reservas.gestionar_sucursal')],
        loadComponent: () =>
          import('./features/catalogo-local/catalogo-local.component').then((m) => m.CatalogoLocalComponent),
      },
      {
        // Modo sin conexión (E14b): lo que se registró en este equipo y en qué va cada operación.
        path: 'operaciones-pendientes',
        canActivate: [cualquierPermisoGuard('ventas.presencial', 'reservas.gestionar_sucursal')],
        loadComponent: () =>
          import('./features/operaciones-pendientes/operaciones-pendientes.component').then(
            (m) => m.OperacionesPendientesComponent,
          ),
      },
      {
        // Operaciones que llegaron de los dispositivos y sus conflictos (E16). Quien supervisa las ve.
        path: 'sincronizacion',
        canActivate: [permisoGuard('sincronizacion.supervisar')],
        loadComponent: () =>
          import('./features/sincronizacion/operaciones-sincronizadas.component').then(
            (m) => m.OperacionesSincronizadasComponent,
          ),
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
      {
        // Panel del superadministrador de la plataforma (sin empresa).
        path: 'plataforma',
        canActivate: [superadminGuard],
        children: [
          { path: '', pathMatch: 'full', redirectTo: 'empresas' },
          {
            path: 'empresas',
            loadComponent: () =>
              import('./features/plataforma/empresas/empresas.component').then((m) => m.EmpresasComponent),
          },
          {
            path: 'planes',
            loadComponent: () =>
              import('./features/plataforma/planes/planes.component').then((m) => m.PlanesComponent),
          },
          {
            path: 'suscripciones',
            loadComponent: () =>
              import('./features/plataforma/suscripciones/suscripciones.component').then(
                (m) => m.SuscripcionesComponent,
              ),
          },
          {
            // La misma pantalla de auditoría, con filtro y columna de empresa (`data.plataforma`).
            path: 'auditoria',
            data: { plataforma: true },
            loadComponent: () =>
              import('./features/auditoria/bitacora.component').then((m) => m.BitacoraComponent),
          },
        ],
      },
      {
        // Bitácora de auditoría de la empresa (solo lectura; el administrador).
        path: 'auditoria',
        canActivate: [permisoGuard('bitacora.ver')],
        loadComponent: () =>
          import('./features/auditoria/bitacora.component').then((m) => m.BitacoraComponent),
      },
      {
        // Copias de seguridad de la empresa (E22): solo su administrador y un plan que las incluya.
        path: 'copias-seguridad',
        canActivate: [permisoGuard('copias.gestionar')],
        loadComponent: () =>
          import('./features/copias-seguridad/copias-seguridad.component').then((m) => m.CopiasSeguridadComponent),
      },
      {
        // Plan, límites y funcionalidades de la empresa (solo su administrador).
        path: 'mi-empresa',
        canActivate: [permisoGuard('empresa.gestionar')],
        loadComponent: () =>
          import('./features/mi-empresa/mi-empresa.component').then((m) => m.MiEmpresaComponent),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
