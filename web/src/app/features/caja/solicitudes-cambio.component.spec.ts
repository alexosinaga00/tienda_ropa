import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import type { SolicitudCambio } from '../../core/models/ventas.models';
import { SolicitudesCambioComponent } from './solicitudes-cambio.component';

const API = environment.apiUrl;
const URL_LISTA = `${API}/solicitudes-cambio/sucursal/4`;

function solicitud(extra: Partial<SolicitudCambio> = {}): SolicitudCambio {
  return {
    id: 11,
    codigo: 'SOL-0011',
    venta_id: 70,
    venta_codigo: 'V-0070',
    sucursal_id: 4,
    cliente_nombre: 'Ana Pérez',
    fecha: '2026-11-04T15:00:00Z',
    estado: 'pendiente',
    motivo: 'Me queda grande',
    motivo_rechazo: null,
    resuelta_en: null,
    atender_hasta: '2026-11-07T15:00:00Z',
    detalle: [
      {
        venta_detalle_id: 9,
        cantidad: 2,
        variante_devuelta_id: 7,
        prenda_devuelta: 'Polera Nike · talla M · Blanco',
        variante_nueva_id: 8,
        prenda_nueva: 'Polera Nike · talla L · Blanco',
        disponible_nueva: 5,
      },
    ],
    ...extra,
  };
}

describe('SolicitudesCambioComponent', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<SolicitudesCambioComponent>;
  let el: HTMLElement;
  let avisos: MessageService;
  let pendientes: number[];

  function abrir(lista: SolicitudCambio[]): void {
    TestBed.configureTestingModule({
      imports: [SolicitudesCambioComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
    avisos = TestBed.inject(MessageService);
    fixture = TestBed.createComponent(SolicitudesCambioComponent);
    fixture.componentRef.setInput('sucursalId', 4);
    pendientes = [];
    fixture.componentInstance.pendientes.subscribe((n: number) => pendientes.push(n));
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    const peticion = http.expectOne((r) => r.url === URL_LISTA);
    expect(peticion.request.params.get('estado')).toBe('pendiente');
    peticion.flush(lista);
    fixture.detectChanges();
  }

  const boton = (estado: string) => el.querySelector<HTMLButtonElement>(`[data-estado="${estado}"]`);

  afterEach(() => http.match(() => true));

  it('muestra lo que devuelve el cliente, lo que quiere y cuánto hay de la prenda nueva', () => {
    abrir([solicitud()]);

    const texto = el.textContent ?? '';
    expect(texto).toContain('SOL-0011');
    expect(texto).toContain('V-0070');
    expect(texto).toContain('Ana Pérez');
    expect(texto).toContain('Polera Nike · talla M · Blanco');
    expect(texto).toContain('Polera Nike · talla L · Blanco');
    expect(texto).toContain('Me queda grande');
    expect(el.querySelector('[data-estado="disponible-nueva"]')?.textContent).toContain('Hay 5 en la sucursal');
    expect(pendientes).toEqual([1]);
  });

  it('sin solicitudes lo dice', () => {
    abrir([]);

    expect(el.querySelector('[data-estado="sin-solicitudes"]')?.textContent).toContain('No hay solicitudes');
    expect(pendientes).toEqual([0]);
  });

  it('aprueba, avisa que se entregó la prenda y vuelve a leer la bandeja', () => {
    abrir([solicitud()]);
    const toast = vi.spyOn(avisos, 'add');

    boton('aprobar')!.click();
    const peticion = http.expectOne(`${API}/solicitudes-cambio/11/aprobar`);
    expect(peticion.request.method).toBe('POST');
    peticion.flush(solicitud({ estado: 'aprobada', correo_programado: true }));

    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'success', summary: 'Cambio aprobado', detail: expect.stringContaining('comprobante') }),
    );
    http.expectOne((r) => r.url === URL_LISTA).flush([]);
    fixture.detectChanges();
    expect(pendientes.at(-1)).toBe(0);
  });

  it('sin stock de la prenda nueva no deja aprobar, y lo explica', () => {
    abrir([solicitud({ detalle: [{ ...solicitud().detalle[0], disponible_nueva: 1 }] })]);

    expect(el.querySelector('[data-estado="disponible-nueva"]')?.textContent).toContain('Solo hay 1 en la sucursal');
    expect(boton('aprobar')!.disabled).toBe(true);
    expect(boton('aprobar')!.getAttribute('title')).toContain('No hay stock');
    expect(boton('rechazar')!.disabled).toBe(false);
  });

  it('si el servidor rechaza la aprobación (409) muestra su motivo en esa solicitud y se vuelve a leer', () => {
    abrir([solicitud()]);

    boton('aprobar')!.click();
    http
      .expectOne(`${API}/solicitudes-cambio/11/aprobar`)
      .flush(
        { detail: 'No hay stock disponible de la talla o el color elegido en esta sucursal: el cambio no se registró.' },
        { status: 409, statusText: 'Conflict' },
      );
    http.expectOne((r) => r.url === URL_LISTA).flush([solicitud()]);
    fixture.detectChanges();

    // Sigue pendiente (no se movió nada) y el aviso explica por qué no se aprobó, aunque la bandeja se haya vuelto a leer.
    expect(el.querySelector('[data-solicitud="SOL-0011"]')).not.toBeNull();
    expect(el.querySelector('[data-estado="error-solicitud"]')?.textContent).toContain('el cambio no se registró');
  });

  it('"Actualizar" vuelve a leer y olvida los avisos anteriores', () => {
    abrir([solicitud()]);
    boton('aprobar')!.click();
    http.expectOne(`${API}/solicitudes-cambio/11/aprobar`).flush({ detail: 'Sin stock' }, { status: 409, statusText: 'Conflict' });
    http.expectOne((r) => r.url === URL_LISTA).flush([solicitud()]);
    fixture.detectChanges();
    expect(el.querySelector('[data-estado="error-solicitud"]')).not.toBeNull();

    boton('actualizar')!.click();
    http.expectOne((r) => r.url === URL_LISTA).flush([solicitud()]);
    fixture.detectChanges();

    expect(el.querySelector('[data-estado="error-solicitud"]')).toBeNull();
  });

  it('un error al aprobar que no es de conflicto deja el mensaje en la solicitud', () => {
    abrir([solicitud()]);

    boton('aprobar')!.click();
    http
      .expectOne(`${API}/solicitudes-cambio/11/aprobar`)
      .flush({ detail: 'El cambio tiene diferencia de precio: todavía no se puede registrar' }, { status: 400, statusText: 'Bad Request' });
    fixture.detectChanges();

    expect(el.querySelector('[data-estado="error-solicitud"]')?.textContent).toContain('diferencia de precio');
    expect(boton('aprobar')!.disabled).toBe(false); // puede reintentar o rechazar
  });

  it('rechazar pide un motivo de al menos 3 letras y lo envía', () => {
    abrir([solicitud()]);

    boton('rechazar')!.click();
    fixture.detectChanges();
    const motivo = el.querySelector<HTMLTextAreaElement>('[data-estado="motivo-rechazo"]')!;
    expect(boton('confirmar-rechazo')!.disabled).toBe(true);

    motivo.value = 'ab';
    motivo.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(boton('confirmar-rechazo')!.disabled).toBe(true);

    motivo.value = 'La prenda llegó usada';
    motivo.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(boton('confirmar-rechazo')!.disabled).toBe(false);

    boton('confirmar-rechazo')!.click();
    const peticion = http.expectOne(`${API}/solicitudes-cambio/11/rechazar`);
    expect(peticion.request.body).toEqual({ motivo: 'La prenda llegó usada' });
    peticion.flush(solicitud({ estado: 'rechazada', motivo_rechazo: 'La prenda llegó usada' }));
    http.expectOne((r) => r.url === URL_LISTA).flush([]);
  });

  it('"Todas" pide todos los estados y muestra el motivo del rechazo y el estado de cada una', () => {
    abrir([solicitud()]);

    boton('filtro-todas')!.click();
    const peticion = http.expectOne((r) => r.url === URL_LISTA);
    expect(peticion.request.params.get('estado')).toBe('todas');
    peticion.flush([
      solicitud({ id: 12, codigo: 'SOL-0012', estado: 'rechazada', motivo_rechazo: 'La prenda llegó usada', resuelta_en: '2026-11-04T16:00:00Z' }),
      solicitud({ id: 13, codigo: 'SOL-0013', estado: 'vencida', resuelta_en: '2026-11-08T00:00:00Z' }),
    ]);
    fixture.detectChanges();

    const texto = el.textContent ?? '';
    expect(texto).toContain('Rechazada');
    expect(texto).toContain('La prenda llegó usada');
    expect(texto).toContain('Vencida');
    expect(el.querySelector('[data-estado="aprobar"]')).toBeNull(); // solo las pendientes se resuelven
    expect(pendientes.at(-1)).toBe(0);
  });

  it('si no se pudo cargar avisa y deja reintentar', () => {
    TestBed.configureTestingModule({
      imports: [SolicitudesCambioComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SolicitudesCambioComponent);
    fixture.componentRef.setInput('sucursalId', 4);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();

    http.expectOne((r) => r.url === URL_LISTA).flush({}, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(el.querySelector('[data-estado="error-solicitudes"]')).not.toBeNull();
  });
});
