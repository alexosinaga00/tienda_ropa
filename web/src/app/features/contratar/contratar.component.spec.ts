import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { CLAVE_PEDIDO_CONTRATACION, IR_A_PAYPAL } from '../../core/contratacion.service';
import { PlanPublico } from '../../core/models/plan.models';
import { ContratarComponent } from './contratar.component';

const URL_PLANES = `${environment.apiUrl}/public/planes`;
const URL_PRUEBA = `${environment.apiUrl}/public/contratacion/prueba`;
const URL_PEDIDOS = `${environment.apiUrl}/public/contratacion/pedidos`;

const BASICO: PlanPublico = {
  codigo: 'basico',
  nombre: 'Básico',
  max_sucursales: 2,
  max_copias_historial: 3,
  plazo_cambio_horas_defecto: 24,
  precio_mensual_bs: '120.00',
  gestion_productos: true,
  gestion_ventas: true,
  reservas: true,
  reportes_convencionales: true,
  reportes_ia: false,
  operacion_offline: true,
  analitica_ml: false,
  copias_seguridad: true,
};
const PROFESIONAL: PlanPublico = {
  ...BASICO,
  codigo: 'profesional',
  nombre: 'Profesional',
  max_sucursales: 10,
  max_copias_historial: 10,
  plazo_cambio_horas_defecto: 72,
  precio_mensual_bs: '590.00',
  reportes_ia: true,
  analitica_ml: true,
};
const SIN_PRECIO: PlanPublico = { ...BASICO, codigo: 'especial', nombre: 'Especial', precio_mensual_bs: null };

const RESPUESTA_PRUEBA = {
  empresa_codigo: 'mi-boutique',
  empresa_nombre: 'Mi Boutique',
  plan_codigo: 'basico',
  plan_nombre: 'Básico',
  es_prueba: true,
  fecha_inicio: '2026-11-04',
  fecha_vencimiento: '2026-11-17',
};

const PEDIDO_CREADO = {
  token: 'tok-secreto-1',
  url_aprobacion: 'https://www.sandbox.paypal.com/checkoutnow?token=ABC',
  plan_codigo: 'basico',
  plan_nombre: 'Básico',
  periodo: 'anual',
  monto_bs: '1152.00',
  monto_usd: '165.52',
  tipo_cambio: '6.9600',
  expira_en: '2026-11-04T15:00:00Z',
};

describe('ContratarComponent', () => {
  let fixture: ComponentFixture<ContratarComponent>;
  let http: HttpTestingController;
  let irAPaypal: ReturnType<typeof vi.fn>;

  async function abrir(consulta = '', planes: PlanPublico[] = [BASICO, PROFESIONAL, SIN_PRECIO]): Promise<void> {
    irAPaypal = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{ path: 'contratar', children: [] }]),
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        { provide: IR_A_PAYPAL, useValue: irAPaypal },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    await TestBed.inject(Router).navigateByUrl(`/contratar${consulta}`);
    fixture = TestBed.createComponent(ContratarComponent);
    fixture.detectChanges();
    http.expectOne(URL_PLANES).flush(planes);
    fixture.detectChanges();
  }

  function html(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function escribir(id: string, valor: string): void {
    const campo = html().querySelector<HTMLInputElement>(`#${id}`)!;
    campo.value = valor;
    campo.dispatchEvent(new Event('input'));
  }

  function llenar(): void {
    escribir('ct-empresa', '  Mi Boutique  ');
    escribir('ct-nombre', 'Ana');
    escribir('ct-apellido', 'Rojas');
    escribir('ct-email', 'Ana@MiBoutique.bo');
    escribir('ct-password', 'clave-segura-1');
  }

  function enviarFormulario(): void {
    html().querySelector('form')!.dispatchEvent(new Event('submit'));
    fixture.detectChanges();
  }

  function botones(selector: string): HTMLButtonElement[] {
    return Array.from(html().querySelectorAll<HTMLButtonElement>(selector));
  }

  function botonConTexto(texto: string): HTMLButtonElement {
    const encontrado = botones('button').find((b) => b.textContent?.includes(texto));
    expect(encontrado, `botón "${texto}"`).toBeDefined();
    return encontrado!;
  }

  beforeEach(() => sessionStorage.clear());

  afterEach(() => {
    http.verify();
    sessionStorage.clear();
  });

  it('abre en prueba gratis por omisión y sin plan elegido pide elegir uno', async () => {
    await abrir();

    expect(botones('.elige--2 button').map((b) => b.getAttribute('aria-pressed'))).toEqual(['true', 'false']);
    expect(botones('.elige--planes button').length).toBe(3);
    expect(botones('.elige--planes button').every((b) => b.getAttribute('aria-pressed') === 'false')).toBe(true);
    expect(html().querySelector('app-resumen-plan')?.textContent).toContain('Elige un plan');

    llenar();
    enviarFormulario();
    http.expectNone(URL_PRUEBA);
    expect(html().querySelector('.aviso')?.textContent).toContain('Elige un plan para continuar');
  });

  it('?plan=profesional&modo=pago abre ese plan en "Contratar ahora" con su precio', async () => {
    await abrir('?plan=profesional&modo=pago');

    expect(botones('.elige--2 button').map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'true']);
    const resumen = html().querySelector('app-resumen-plan')!.textContent ?? '';
    expect(resumen).toContain('Profesional');
    expect(resumen).toContain('Bs 590');
    expect(botones('button[type="submit"]')[0].textContent).toContain('Continuar al pago');
  });

  it('un plan que no existe en la dirección avisa y deja elegir otro', async () => {
    await abrir('?plan=fantasma');
    expect(html().textContent).toContain('El plan que elegiste ya no está disponible');
    expect(html().querySelector('app-resumen-plan')?.textContent).toContain('Elige un plan');
  });

  it('prueba gratis: manda el cuerpo sin montos, recortado y sin teléfono vacío; muestra la tienda lista', async () => {
    await abrir('?plan=basico&modo=prueba');
    llenar();
    enviarFormulario();

    const req: TestRequest = http.expectOne(URL_PRUEBA);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      nombre: 'Mi Boutique',
      plan_codigo: 'basico',
      administrador: { nombre: 'Ana', apellido: 'Rojas', email: 'Ana@MiBoutique.bo', password: 'clave-segura-1' },
    });
    expect(Object.keys(req.request.body)).not.toContain('periodo');
    req.flush(RESPUESTA_PRUEBA);
    fixture.detectChanges();

    const texto = html().textContent ?? '';
    expect(texto).toContain('Tu tienda está lista');
    expect(texto).toContain('Mi Boutique');
    expect(texto).toContain('en prueba gratis hasta el 17 de noviembre de 2026');
    expect(texto).toContain('ana@miboutique.bo');
    expect(html().querySelector('a[href="/t/mi-boutique"]')).not.toBeNull();
    expect(html().querySelector('a[href="/admin/login"]')).not.toBeNull();
    // La contraseña no queda en pantalla ni en el almacenamiento.
    expect(texto).not.toContain('clave-segura-1');
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBeNull();
  });

  it('prueba gratis: el teléfono, si se escribe, se manda', async () => {
    await abrir('?plan=basico');
    llenar();
    escribir('ct-telefono', ' 70012345 ');
    enviarFormulario();

    const req = http.expectOne(URL_PRUEBA);
    expect(req.request.body.administrador.telefono).toBe('70012345');
    req.flush(RESPUESTA_PRUEBA);
  });

  it('un doble envío no duplica la petición', async () => {
    await abrir('?plan=basico');
    llenar();
    enviarFormulario();
    enviarFormulario();
    enviarFormulario();

    // expectOne falla si hay más de una petición abierta.
    const req = http.expectOne(URL_PRUEBA);
    expect(botones('button[type="submit"]')[0].disabled).toBe(true);
    req.flush(RESPUESTA_PRUEBA);
  });

  it('con datos inválidos no llama a la API y explica cada campo', async () => {
    await abrir('?plan=basico');
    escribir('ct-empresa', 'A');
    escribir('ct-email', 'no-es-correo');
    escribir('ct-password', 'corta');
    enviarFormulario();

    http.expectNone(URL_PRUEBA);
    const texto = html().textContent ?? '';
    expect(texto).toContain('Escribe al menos 2 caracteres');
    expect(texto).toContain('Escribe un correo válido');
    expect(texto).toContain('Usa al menos 8 caracteres');
    expect(texto).toContain('Este dato es obligatorio');
  });

  it('prueba_ya_usada: lo explica en la propia página, sin toast, y deja volver a enviar', async () => {
    await abrir('?plan=basico');
    llenar();
    enviarFormulario();
    http
      .expectOne(URL_PRUEBA)
      .flush(
        { detail: 'prueba_ya_usada', codigo: 'prueba_ya_usada', mensaje: 'Este correo ya usó su prueba gratuita' },
        { status: 409, statusText: 'Conflict' },
      );
    fixture.detectChanges();

    expect(html().querySelector('.aviso--error')?.textContent).toContain('ya usó su prueba gratuita');
    expect(html().textContent).not.toContain('prueba_ya_usada');
    expect(botones('button[type="submit"]')[0].disabled).toBe(false);
  });

  it('nombre de empresa repetido (409 solo con detail) se muestra como aviso claro', async () => {
    await abrir('?plan=basico');
    llenar();
    enviarFormulario();
    http.expectOne(URL_PRUEBA).flush({ detail: 'Ya existe una empresa con ese nombre' }, { status: 409, statusText: 'Conflict' });
    fixture.detectChanges();

    expect(html().querySelector('.aviso--error')?.textContent).toContain('Ya existe una empresa con ese nombre');
  });

  it('cambiar de modo y de plan actualiza el texto del botón y el resumen', async () => {
    await abrir('?plan=basico');
    expect(botones('button[type="submit"]')[0].textContent).toContain('Empezar mi prueba gratis');

    botonConTexto('Contratar ahora').click();
    fixture.detectChanges();
    expect(botones('button[type="submit"]')[0].textContent).toContain('Continuar al pago');
    expect(html().querySelector('.periodo')).not.toBeNull();

    botones('.elige--planes button')[1].click();
    fixture.detectChanges();
    expect(html().querySelector('app-resumen-plan')?.textContent).toContain('Profesional');
    expect(html().querySelector('app-resumen-plan')?.textContent).toContain('Bs 590');
  });

  it('el resumen muestra el plan anual con 20 % menos y lo que se ahorra', async () => {
    await abrir('?plan=basico&modo=pago');
    expect(html().querySelector('.lado__monto')?.textContent).toContain('Bs 120');

    botones('.periodo__op')[1].click();
    fixture.detectChanges();
    expect(html().querySelector('.lado__monto')?.textContent).toContain('Bs 1.152');
    expect(html().querySelector('.lado__nota')?.textContent).toContain('Bs 96 al mes');
    expect(html().querySelector('.lado__nota')?.textContent).toContain('Bs 288');
  });

  it('pagar: pasa a revisar, crea el pedido SIN montos, guarda el token y redirige a PayPal', async () => {
    await abrir('?plan=basico&modo=pago&periodo=anual');
    llenar();
    enviarFormulario();

    // Paso de revisión: nada se pidió todavía.
    http.expectNone(URL_PEDIDOS);
    const revision = html().textContent ?? '';
    expect(revision).toContain('Revisa y paga');
    expect(revision).toContain('Mi Boutique');
    expect(revision).toContain('Anual (12 meses)');
    expect(revision).toContain('Bs 1.152');

    botonConTexto('Pagar con PayPal').click();
    fixture.detectChanges();

    const req = http.expectOne(URL_PEDIDOS);
    expect(req.request.body).toEqual({
      nombre: 'Mi Boutique',
      plan_codigo: 'basico',
      administrador: { nombre: 'Ana', apellido: 'Rojas', email: 'Ana@MiBoutique.bo', password: 'clave-segura-1' },
      periodo: 'anual',
    });
    expect(JSON.stringify(req.request.body)).not.toMatch(/monto|usd|moneda/i);

    req.flush(PEDIDO_CREADO);
    // El token se guardó ANTES de salir, y se salió a la dirección que dio el servidor.
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBe('tok-secreto-1');
    expect(irAPaypal).toHaveBeenCalledTimes(1);
    expect(irAPaypal).toHaveBeenCalledWith(PEDIDO_CREADO.url_aprobacion);
  });

  it('pagar: un doble clic no crea dos pedidos y el botón queda bloqueado al salir', async () => {
    await abrir('?plan=basico&modo=pago');
    llenar();
    enviarFormulario();

    const pagar = botonConTexto('Pagar con PayPal');
    pagar.click();
    pagar.click();
    pagar.click();
    const req = http.expectOne(URL_PEDIDOS);
    req.flush({ ...PEDIDO_CREADO, periodo: 'mensual' });
    fixture.detectChanges();

    expect(irAPaypal).toHaveBeenCalledTimes(1);
    expect(botones('button.enviar')[0].disabled).toBe(true);
  });

  it('pagar: una dirección de aprobación que no es https no se visita y no se guarda el token', async () => {
    await abrir('?plan=basico&modo=pago');
    llenar();
    enviarFormulario();
    botonConTexto('Pagar con PayPal').click();

    http.expectOne(URL_PEDIDOS).flush({ ...PEDIDO_CREADO, url_aprobacion: 'javascript:alert(1)' });
    fixture.detectChanges();

    expect(irAPaypal).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBeNull();
    expect(html().querySelector('.aviso--error')?.textContent).toContain('PayPal no responde');
    expect(botonConTexto('Pagar con PayPal').disabled).toBe(false);
  });

  it('pagar: si PayPal no responde (503) avisa, no guarda nada y permite reintentar', async () => {
    await abrir('?plan=basico&modo=pago');
    llenar();
    enviarFormulario();
    botonConTexto('Pagar con PayPal').click();

    http
      .expectOne(URL_PEDIDOS)
      .flush(
        { detail: 'paypal_no_disponible', codigo: 'paypal_no_disponible', mensaje: 'x' },
        { status: 503, statusText: 'Service Unavailable' },
      );
    fixture.detectChanges();

    expect(html().querySelector('.aviso--error')?.textContent).toContain('No se cobró nada');
    expect(irAPaypal).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBeNull();
    expect(html().textContent).toContain('Revisa y paga');
    expect(botonConTexto('Pagar con PayPal').disabled).toBe(false);
  });

  it('pagar: un error de datos (nombre repetido) devuelve al primer paso', async () => {
    await abrir('?plan=basico&modo=pago');
    llenar();
    enviarFormulario();
    botonConTexto('Pagar con PayPal').click();

    http.expectOne(URL_PEDIDOS).flush({ detail: 'Ya existe una empresa con ese nombre' }, { status: 409, statusText: 'Conflict' });
    fixture.detectChanges();

    expect(html().querySelector('form')).not.toBeNull();
    expect(html().querySelector('.aviso--error')?.textContent).toContain('Ya existe una empresa con ese nombre');
  });

  it('un plan sin precio no se puede contratar (sí probar) y no pasa al pago', async () => {
    await abrir('?plan=especial&modo=pago');
    expect(html().querySelector('app-resumen-plan')?.textContent).toContain('A consultar');
    llenar();
    enviarFormulario();

    http.expectNone(URL_PEDIDOS);
    expect(html().textContent).not.toContain('Revisa y paga');
    expect(html().querySelector('.aviso--error')?.textContent).toContain('no tiene precio publicado');
  });

  it('"Volver a mis datos" regresa al formulario con lo escrito', async () => {
    await abrir('?plan=basico&modo=pago');
    llenar();
    enviarFormulario();
    botonConTexto('Volver a mis datos').click();
    fixture.detectChanges();

    expect(html().querySelector<HTMLInputElement>('#ct-empresa')?.value).toBe('  Mi Boutique  ');
  });

  it('el ojo muestra y oculta la contraseña', async () => {
    await abrir('?plan=basico');
    const campo = html().querySelector<HTMLInputElement>('#ct-password')!;
    expect(campo.type).toBe('password');
    html().querySelector<HTMLButtonElement>('.fs-campo__accion')!.click();
    fixture.detectChanges();
    expect(campo.type).toBe('text');
  });

  it('si los planes no cargan, avisa y Reintentar vuelve a pedirlos', async () => {
    irAPaypal = vi.fn();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ContratarComponent);
    fixture.detectChanges();
    http.expectOne(URL_PLANES).flush('boom', { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(html().textContent).toContain('No pudimos cargar los planes');
    botonConTexto('Reintentar').click();
    http.expectOne(URL_PLANES).flush([BASICO]);
    fixture.detectChanges();
    expect(html().textContent).not.toContain('No pudimos cargar los planes');
    expect(botones('.elige--planes button').length).toBe(1);
  });
});
