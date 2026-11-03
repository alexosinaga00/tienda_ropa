import { Type } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { AuthService } from '../core/auth.service';
import { CiudadesComponent } from './ciudades/ciudades.component';
import { ColeccionesComponent } from './colecciones/colecciones.component';
import { ColoresComponent } from './colores/colores.component';
import { EmpleadosComponent } from './empleados/empleados.component';
import { ProveedoresComponent } from './proveedores/proveedores.component';
import { PromocionesComponent } from './promociones/promociones.component';
import { RolesComponent } from './roles/roles.component';
import { SucursalesComponent } from './sucursales/sucursales.component';
import { TallasComponent } from './tallas/tallas.component';
import { TemporadasComponent } from './temporadas/temporadas.component';
import { UsuariosComponent } from './usuarios/usuarios.component';
import { ZonasEnvioComponent } from './zonas-envio/zonas-envio.component';

interface Caso {
  nombre: string;
  componente: Type<unknown>;
  eyebrow: string;
  titulo: string;
  nuevo: string;
  tituloDialogo: string;
  formId: string;
  /** Campo obligatorio que, vacío, debe mostrar su error al guardar. */
  campo: string;
  /** Texto del error de ese campo. */
  mensaje: string;
}

const CASOS: Caso[] = [
  { nombre: 'ciudades', componente: CiudadesComponent, eyebrow: 'Organización', titulo: 'Ciudades', nuevo: 'Nueva ciudad', tituloDialogo: 'Nueva ciudad', formId: 'form-ciudad', campo: 'nombre', mensaje: 'Ingresa el nombre.' },
  { nombre: 'sucursales', componente: SucursalesComponent, eyebrow: 'Organización', titulo: 'Sucursales', nuevo: 'Nueva sucursal', tituloDialogo: 'Nueva sucursal', formId: 'form-sucursal', campo: 'ciudad_id', mensaje: 'Selecciona una ciudad.' },
  { nombre: 'empleados', componente: EmpleadosComponent, eyebrow: 'Organización', titulo: 'Empleados', nuevo: 'Nuevo empleado', tituloDialogo: 'Nuevo empleado', formId: 'form-empleado', campo: 'usuario_id', mensaje: 'Selecciona un usuario.' },
  { nombre: 'usuarios', componente: UsuariosComponent, eyebrow: 'Organización', titulo: 'Usuarios', nuevo: 'Nuevo usuario', tituloDialogo: 'Nuevo usuario', formId: 'form-usuario', campo: 'nombre', mensaje: 'Ingresa el nombre.' },
  { nombre: 'roles', componente: RolesComponent, eyebrow: 'Organización', titulo: 'Roles', nuevo: 'Nuevo rol', tituloDialogo: 'Nuevo rol', formId: 'form-rol', campo: 'nombre', mensaje: 'Ingresa el nombre.' },
  { nombre: 'tallas', componente: TallasComponent, eyebrow: 'Catálogo', titulo: 'Tallas', nuevo: 'Nueva talla', tituloDialogo: 'Nueva talla', formId: 'form-talla', campo: 'codigo', mensaje: 'Ingresa el código.' },
  { nombre: 'colores', componente: ColoresComponent, eyebrow: 'Catálogo', titulo: 'Colores', nuevo: 'Nuevo color', tituloDialogo: 'Nuevo color', formId: 'form-color', campo: 'nombre', mensaje: 'Ingresa el nombre.' },
  { nombre: 'temporadas', componente: TemporadasComponent, eyebrow: 'Catálogo', titulo: 'Temporadas', nuevo: 'Nueva temporada', tituloDialogo: 'Nueva temporada', formId: 'form-temporada', campo: 'nombre', mensaje: 'Ingresa el nombre.' },
  { nombre: 'colecciones', componente: ColeccionesComponent, eyebrow: 'Catálogo', titulo: 'Colecciones', nuevo: 'Nueva colección', tituloDialogo: 'Nueva colección', formId: 'form-coleccion', campo: 'nombre', mensaje: 'Ingresa el nombre.' },
  { nombre: 'proveedores', componente: ProveedoresComponent, eyebrow: 'Catálogo', titulo: 'Proveedores', nuevo: 'Nuevo proveedor', tituloDialogo: 'Nuevo proveedor', formId: 'form-proveedor', campo: 'nombre', mensaje: 'Ingresa el nombre.' },
  { nombre: 'promociones', componente: PromocionesComponent, eyebrow: 'Comercial', titulo: 'Promociones', nuevo: 'Nueva promoción', tituloDialogo: 'Nueva promoción', formId: 'form-promocion', campo: 'nombre', mensaje: 'Ingresa el nombre.' },
  { nombre: 'zonas de envío', componente: ZonasEnvioComponent, eyebrow: 'Comercial', titulo: 'Zonas de envío', nuevo: 'Nueva zona', tituloDialogo: 'Nueva zona de envío', formId: 'form-zona-envio', campo: 'ciudad_id', mensaje: 'Selecciona una ciudad.' },
];

/**
 * Patrón de las pantallas CRUD simples (canvas Crud). Categorías tiene su
 * propia prueba más detallada (categorias.component.spec.ts); estas cubren el
 * resto con el mismo recorrido: encabezado, diálogo con formId, error de campo.
 */
describe.each(CASOS)('Patrón CRUD: $nombre', (caso) => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [caso.componente],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        // Roles solo se edita con plataforma.gestionar; sin él la pantalla es de consulta (ver roles.component.spec.ts).
        ...(caso.nombre === 'roles' ? [{ provide: AuthService, useValue: { tienePermiso: () => true } }] : []),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.match(() => true));

  function crear() {
    const fixture = TestBed.createComponent(caso.componente);
    fixture.detectChanges();
    http.match(() => true).forEach((r) => r.flush([]));
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  it('dibuja el encabezado con rótulo, título y botón "Nuevo ..." y un buscador', () => {
    const { fixture, el } = crear();

    expect(el.querySelector('header.fs-pagina-encabezado .fs-eyebrow')?.textContent).toBe(caso.eyebrow);
    expect(el.querySelector('header.fs-pagina-encabezado h1')?.textContent).toBe(caso.titulo);
    expect(el.querySelector('[data-testid="tabla-nuevo"]')?.textContent).toContain(caso.nuevo);
    expect(el.querySelector('input[type="search"]')).not.toBeNull();
    fixture.destroy();
  });

  it('el botón abre el diálogo con su título, el formulario y Guardar asociado por formId', () => {
    const { fixture, el } = crear();

    (el.querySelector('[data-testid="tabla-nuevo"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(document.body.querySelector('.p-dialog-title')?.textContent).toContain(caso.tituloDialogo);
    expect(document.body.querySelector(`form#${caso.formId}`)).not.toBeNull();
    const guardar = document.body.querySelector('[data-testid="dialogo-guardar"]') as HTMLButtonElement;
    expect(guardar.getAttribute('form')).toBe(caso.formId);
    expect(guardar.disabled).toBe(false);
    fixture.destroy();
  });

  it('guardar vacío no envía nada y muestra el error del campo obligatorio, enlazado con aria', () => {
    const { fixture, el } = crear();
    (el.querySelector('[data-testid="tabla-nuevo"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    (document.body.querySelector(`form#${caso.formId}`) as HTMLFormElement).dispatchEvent(new Event('submit'));
    fixture.detectChanges();

    http.expectNone((r) => r.method === 'POST' || r.method === 'PUT');
    const error = document.body.querySelector(`#err-${caso.campo}`) as HTMLElement;
    expect(error.getAttribute('role')).toBe('alert');
    expect(error.textContent).toContain(caso.mensaje);
    const control = document.body.querySelector(`[aria-describedby="err-${caso.campo}"]`);
    expect(control?.getAttribute('aria-invalid')).toBe('true');
    fixture.destroy();
  });
});

describe('Errores de campo que antes fallaban en silencio', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.match(() => true));

  function abrir<T>(componente: Type<T>, formId: string) {
    const fixture = TestBed.createComponent(componente);
    fixture.detectChanges();
    http.match(() => true).forEach((r) => r.flush([]));
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('[data-testid="tabla-nuevo"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    return { fixture, form: document.body.querySelector(`form#${formId}`) as HTMLFormElement };
  }

  it('temporadas: un año fuera de 2000-2100 muestra su error', () => {
    const { fixture, form } = abrir(TemporadasComponent, 'form-temporada');
    const comp = fixture.componentInstance as unknown as { formulario: { patchValue(v: object): void } };
    comp.formulario.patchValue({ nombre: 'Verano', anio: 1999 });

    form.dispatchEvent(new Event('submit'));
    fixture.detectChanges();

    expect(document.body.querySelector('#err-anio')?.textContent).toContain('año entre 2000 y 2100');
    http.expectNone((r) => r.method === 'POST');
    fixture.destroy();
  });

  it('zonas de envío: un anillo menor que 1 muestra su error', () => {
    const { fixture, form } = abrir(ZonasEnvioComponent, 'form-zona-envio');
    const comp = fixture.componentInstance as unknown as { formulario: { patchValue(v: object): void } };
    comp.formulario.patchValue({ ciudad_id: 1, nombre: 'Centro', anillo_desde: 0, anillo_hasta: 0, tarifa_base: 10 });

    form.dispatchEvent(new Event('submit'));
    fixture.detectChanges();

    expect(document.body.querySelector('#err-anillo_desde')?.textContent).toContain('desde 1');
    expect(document.body.querySelector('#err-anillo_hasta')?.textContent).toContain('desde 1');
    http.expectNone((r) => r.method === 'POST');
    fixture.destroy();
  });

  it('promociones: cada línea de alcance sin ID muestra su error', () => {
    const { fixture, form } = abrir(PromocionesComponent, 'form-promocion');
    const comp = fixture.componentInstance as unknown as { formulario: { patchValue(v: object): void } };
    comp.formulario.patchValue({ nombre: 'Rebaja', valor: 10, fecha_inicio: new Date(), fecha_fin: new Date() });

    form.dispatchEvent(new Event('submit'));
    fixture.detectChanges();

    expect(document.body.querySelector('#err-alcance-0')?.textContent).toContain('Ingresa el ID del alcance 1.');
    http.expectNone((r) => r.method === 'POST');
    fixture.destroy();
  });

  it('guardar deshabilita el botón mientras la petición está en vuelo', () => {
    const { fixture, form } = abrir(CiudadesComponent, 'form-ciudad');
    const comp = fixture.componentInstance as unknown as { formulario: { patchValue(v: object): void } };
    comp.formulario.patchValue({ nombre: 'Sucre' });

    form.dispatchEvent(new Event('submit'));
    fixture.detectChanges();
    const guardar = document.body.querySelector('[data-testid="dialogo-guardar"]') as HTMLButtonElement;
    expect(guardar.disabled).toBe(true);

    http.expectOne((r) => r.method === 'POST').flush({});
    http.match(() => true).forEach((r) => r.flush([]));
    fixture.detectChanges();
    expect(guardar.disabled).toBe(false);
    fixture.destroy();
  });
});
