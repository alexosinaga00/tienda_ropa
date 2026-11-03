import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { RolesComponent } from './roles.component';

const API = environment.apiUrl;

const ROL = { id: 3, nombre: 'cajero', descripcion: 'Vende', activo: true, permisos: [{ id: 1, codigo: 'ventas.presencial' }] };
const PERMISOS = [{ id: 1, codigo: 'ventas.presencial', modulo: 'ventas', descripcion: 'Vender en caja' }];

/**
 * Crear, editar o desactivar roles y asignarles permisos exige `plataforma.gestionar` en el servidor (los roles son
 * globales). Quien no lo tiene, como el administrador de una empresa, solo consulta: sin botones que den 403.
 */
describe('RolesComponent: quién puede modificar', () => {
  let http: HttpTestingController;

  function montar(tienePermiso: (permiso: string) => boolean) {
    TestBed.configureTestingModule({
      imports: [RolesComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        { provide: AuthService, useValue: { tienePermiso } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(RolesComponent);
    fixture.detectChanges();
    http.expectOne((r) => r.url.startsWith(`${API}/roles`)).flush([ROL]);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  afterEach(() => http.match(() => true));

  it('sin plataforma.gestionar no hay "Nuevo rol", ni editar, ni desactivar; queda "Ver permisos del rol"', () => {
    const { fixture, el } = montar((p) => p === 'roles.gestionar');

    expect(el.querySelector('[data-testid="tabla-nuevo"]')).toBeNull();
    expect(el.querySelector('button[aria-label="Editar"]')).toBeNull();
    expect(el.querySelector('button[aria-label="Desactivar"]')).toBeNull();
    expect(el.querySelector('button[aria-label="Ver permisos del rol"]')).not.toBeNull();
    fixture.destroy();
  });

  it('sin plataforma.gestionar los permisos se ven pero no se pueden cambiar ni guardar', () => {
    const { fixture, el } = montar((p) => p === 'roles.gestionar');

    (el.querySelector('button[aria-label="Ver permisos del rol"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    http.expectOne(`${API}/permisos`).flush(PERMISOS);
    fixture.detectChanges();

    const casilla = document.body.querySelector('.permisos-item input[type="checkbox"]') as HTMLInputElement;
    expect(casilla.checked).toBe(true);
    expect(casilla.disabled).toBe(true);
    expect(document.body.textContent).toContain('solo los cambia el administrador de la plataforma');
    expect(document.body.querySelector('.permisos-botones .fs-btn--primario')).toBeNull();
    expect(document.body.querySelector('.permisos-botones')?.textContent).toContain('Cerrar');
    http.expectNone((r) => r.method === 'PUT');
    fixture.destroy();
  });

  it('con plataforma.gestionar sí se crea, se edita y se guardan los permisos', () => {
    const { fixture, el } = montar(() => true);

    expect(el.querySelector('[data-testid="tabla-nuevo"]')?.textContent).toContain('Nuevo rol');
    expect(el.querySelector('button[aria-label="Editar"]')).not.toBeNull();
    expect(el.querySelector('button[aria-label="Desactivar"]')).not.toBeNull();

    (el.querySelector('button[aria-label="Permisos del rol"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    http.expectOne(`${API}/permisos`).flush(PERMISOS);
    fixture.detectChanges();

    const casilla = document.body.querySelector('.permisos-item input[type="checkbox"]') as HTMLInputElement;
    expect(casilla.disabled).toBe(false);
    expect(document.body.querySelector('.permisos-botones .fs-btn--primario')?.textContent).toContain('Guardar permisos');
    fixture.destroy();
  });
});
