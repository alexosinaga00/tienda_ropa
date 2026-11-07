import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../environments/environment';
import { ColumnaTabla, TablaGenericaComponent } from './tabla-generica.component';

interface Fila {
  id: number;
  nombre: string;
  activo: boolean;
}

const COLUMNAS: ColumnaTabla<Fila>[] = [
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'activo', encabezado: 'Activo', tipo: 'booleano' },
];

const FILAS: Fila[] = [
  { id: 1, nombre: 'Camisas', activo: true },
  { id: 2, nombre: 'Calzado', activo: false },
];

describe('TablaGenericaComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [TablaGenericaComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function crear(entradas: Record<string, unknown> = {}, filas: Fila[] = FILAS) {
    const fixture = TestBed.createComponent(TablaGenericaComponent<Fila>);
    fixture.componentRef.setInput('endpoint', '/categorias');
    fixture.componentRef.setInput('columnas', COLUMNAS);
    for (const [nombre, valor] of Object.entries(entradas)) fixture.componentRef.setInput(nombre, valor);
    fixture.detectChanges();
    const tamanio = (entradas['tamanioPagina'] as number | undefined) ?? 20;
    http.expectOne(`${environment.apiUrl}/categorias?pagina=1&tamanio=${tamanio}`).flush(filas);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement, comp: fixture.componentInstance };
  }

  it('pide la primera página al endpoint', () => {
    const { fixture } = crear();
    expect(fixture.componentInstance).toBeTruthy();
  });

  describe('encabezado de la pantalla', () => {
    it('con título dibuja rótulo, h1 y el botón "Nuevo ..." del encabezado', () => {
      const { el } = crear({ titulo: 'Categorías', eyebrow: 'Catálogo', etiquetaNuevo: 'Nueva categoría' });

      const encabezado = el.querySelector('header.fs-pagina-encabezado') as HTMLElement;
      expect(encabezado.querySelector('.fs-eyebrow')?.textContent).toBe('Catálogo');
      expect(encabezado.querySelector('h1')?.textContent).toBe('Categorías');
      const boton = encabezado.querySelector('[data-testid="tabla-nuevo"]') as HTMLButtonElement;
      expect(boton.textContent).toContain('Nueva categoría');
      expect(boton.querySelector('svg')?.getAttribute('width')).toBe('24');
      expect(el.querySelectorAll('[data-testid="tabla-nuevo"]').length).toBe(1);
    });

    it('el botón del encabezado emite "crear"', () => {
      const { el, comp } = crear({ titulo: 'Categorías' });
      let emitido = 0;
      comp.crear.subscribe(() => emitido++);

      (el.querySelector('[data-testid="tabla-nuevo"]') as HTMLButtonElement).click();
      expect(emitido).toBe(1);
    });

    it('sin título (pantallas con su propio encabezado) el botón queda en la barra de búsqueda', () => {
      const { el } = crear();

      expect(el.querySelector('header.fs-pagina-encabezado')).toBeNull();
      const boton = el.querySelector('.tg-barra [data-testid="tabla-nuevo"]') as HTMLButtonElement;
      expect(boton.textContent).toContain('Nuevo');
    });

    it('en solo lectura no hay botón de crear ni columna de acciones', () => {
      const { el } = crear({ titulo: 'Categorías', soloLectura: true });

      expect(el.querySelector('[data-testid="tabla-nuevo"]')).toBeNull();
      expect(el.querySelector('.tg-th-acciones')).toBeNull();
    });
  });

  describe('tabla', () => {
    it('muestra las filas con el estado como chip Activo/Inactivo', () => {
      const { el } = crear();

      const filas = el.querySelectorAll('tbody tr');
      expect(filas.length).toBe(2);
      const chips = Array.from(el.querySelectorAll('tbody .fs-chip'));
      expect(chips.map((c) => c.textContent?.trim())).toEqual(['Activo', 'Inactivo']);
      expect(chips[0].classList).toContain('fs-chip--exito');
      expect(chips[1].classList).not.toContain('fs-chip--exito');
    });

    it('el contador dice que cuenta la página cargada', () => {
      const { el } = crear();
      expect(el.querySelector('.tg-conteo')?.textContent?.trim()).toBe('2 registros en esta página');
    });

    it('al buscar, el contador y las filas siguen la búsqueda', () => {
      vi.useFakeTimers();
      try {
        const { fixture, el } = crear();
        const buscador = el.querySelector('input[type="search"]') as HTMLInputElement;
        expect(buscador).not.toBeNull();

        buscador.value = 'camis';
        buscador.dispatchEvent(new Event('input'));
        vi.advanceTimersByTime(500);
        fixture.detectChanges();

        expect(el.querySelector('.tg-conteo')?.textContent?.trim()).toBe('1 de 2 en esta página');
        expect(el.querySelectorAll('tbody tr').length).toBe(1);

        buscador.value = '';
        buscador.dispatchEvent(new Event('input'));
        vi.advanceTimersByTime(500);
        fixture.detectChanges();
        expect(el.querySelector('.tg-conteo')?.textContent?.trim()).toBe('2 registros en esta página');
      } finally {
        vi.useRealTimers();
      }
    });

    it('el chip va en masculino por defecto y en femenino por tabla o por columna', () => {
      const chips = (el: HTMLElement) =>
        Array.from(el.querySelectorAll('tbody .fs-chip')).map((c) => c.textContent?.trim());

      const masculino = crear();
      expect(chips(masculino.el)).toEqual(['Activo', 'Inactivo']);
      masculino.fixture.destroy();

      const porTabla = crear({ femenino: true });
      expect(chips(porTabla.el)).toEqual(['Activa', 'Inactiva']);
      porTabla.fixture.destroy();

      const porColumna = crear({
        columnas: [COLUMNAS[0], { campo: 'activo', encabezado: 'Activa', tipo: 'booleano', femenino: true }],
      });
      expect(chips(porColumna.el)).toEqual(['Activa', 'Inactiva']);
    });

    it('sin datos muestra "Sin registros."', () => {
      const { el } = crear({}, []);
      expect(el.querySelector('.fs-estado-vacio')?.textContent).toContain('Sin registros.');
    });

    it('los botones de acción son de ícono, con nombre accesible y área de 44 px', () => {
      const { el } = crear();

      const acciones = Array.from(el.querySelectorAll('tbody tr:first-child .tg-accion'));
      expect(acciones.map((a) => a.getAttribute('aria-label'))).toEqual(['Editar', 'Desactivar']);
      for (const accion of acciones) expect(accion.querySelector('svg')?.getAttribute('width')).toBe('24');
    });

    it('"Editar" emite la fila', () => {
      const { el, comp } = crear();
      let recibida: Fila | undefined;
      comp.editar.subscribe((fila) => (recibida = fila));

      (el.querySelector('tbody tr:first-child [aria-label="Editar"]') as HTMLButtonElement).click();
      expect(recibida).toEqual(FILAS[0]);
    });

    it('la acción extra aparece solo si se pide, con un fs-icono o una clase de PrimeIcons', () => {
      const sin = crear();
      expect(sin.el.querySelectorAll('tbody tr:first-child .tg-accion').length).toBe(2);
      sin.fixture.destroy();

      const conNombre = crear({ accionExtraIcono: 'llave', accionExtraEtiqueta: 'Permisos del rol' });
      const boton = conNombre.el.querySelector('tbody tr:first-child [aria-label="Permisos del rol"]') as HTMLElement;
      expect(boton.querySelector('svg')).not.toBeNull();
      let fila: Fila | undefined;
      conNombre.comp.accionExtra.subscribe((f) => (fila = f));
      boton.click();
      expect(fila).toEqual(FILAS[0]);
      conNombre.fixture.destroy();

      const conPrime = crear({ accionExtraIcono: 'pi pi-key', accionExtraEtiqueta: 'Permisos' });
      expect(conPrime.el.querySelector('tbody tr:first-child [aria-label="Permisos"] i.pi-key')).not.toBeNull();
    });
  });

  describe('desactivar', () => {
    it('pide confirmación y, al aceptar, hace DELETE y recarga la página', () => {
      const { fixture, el } = crear();

      (el.querySelector('tbody tr:first-child [aria-label="Desactivar"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      http.expectNone((r) => r.method === 'DELETE');

      const aceptar = Array.from(document.body.querySelectorAll('button')).find((b) =>
        (b.textContent ?? '').includes('Sí, desactivar'),
      ) as HTMLButtonElement;
      expect(aceptar).toBeTruthy();
      aceptar.click();

      http.expectOne((r) => r.method === 'DELETE' && r.url === `${environment.apiUrl}/categorias/1`).flush(null);
      http.expectOne(`${environment.apiUrl}/categorias?pagina=1&tamanio=20`).flush(FILAS);
    });

    it('al cancelar no se borra nada', () => {
      const { fixture, el } = crear();

      (el.querySelector('tbody tr:first-child [aria-label="Desactivar"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      const cancelar = Array.from(document.body.querySelectorAll('button')).find(
        (b) => (b.textContent ?? '').trim() === 'Cancelar',
      ) as HTMLButtonElement;
      cancelar.click();

      http.expectNone((r) => r.method === 'DELETE');
    });
  });

  describe('error de carga', () => {
    it('muestra un estado de error propio con Reintentar (no "Sin registros.")', () => {
      const fixture = TestBed.createComponent(TablaGenericaComponent<Fila>);
      fixture.componentRef.setInput('endpoint', '/categorias');
      fixture.componentRef.setInput('columnas', COLUMNAS);
      fixture.detectChanges();
      http
        .expectOne(`${environment.apiUrl}/categorias?pagina=1&tamanio=20`)
        .flush('fallo', { status: 500, statusText: 'Error' });
      fixture.detectChanges();
      const el = fixture.nativeElement as HTMLElement;

      expect(el.querySelector('.fs-estado-vacio')?.textContent).toContain('No se pudo cargar la lista.');
      expect(el.querySelector('.fs-estado-vacio')?.textContent).not.toContain('Sin registros.');

      (el.querySelector('.tg-reintentar') as HTMLButtonElement).click();
      http.expectOne(`${environment.apiUrl}/categorias?pagina=1&tamanio=20`).flush(FILAS);
      fixture.detectChanges();

      expect(el.querySelector('.tg-reintentar')).toBeNull();
      expect(el.querySelectorAll('tbody tr').length).toBe(2);
    });
  });

  describe('paginación', () => {
    it('Anterior está deshabilitado en la primera página y Siguiente solo si la página vino llena', () => {
      const { el } = crear({ tamanioPagina: 2 });
      // La página trae 2 filas = tamanioPagina: hay otra.
      const anterior = el.querySelector('[aria-label="Anterior"]') as HTMLButtonElement;
      const siguiente = el.querySelector('[aria-label="Siguiente"]') as HTMLButtonElement;
      expect(anterior.disabled).toBe(true);
      expect(siguiente.disabled).toBe(false);

      siguiente.click();
      http.expectOne(`${environment.apiUrl}/categorias?pagina=2&tamanio=2`).flush([]);
    });
  });

  describe('búsqueda en el servidor', () => {
    const URL = `${environment.apiUrl}/categorias`;

    function escribir(el: HTMLElement, texto: string): void {
      const buscador = el.querySelector('input[type="search"]') as HTMLInputElement;
      buscador.value = texto;
      buscador.dispatchEvent(new Event('input'));
    }

    it('sin la opción, escribir no consulta al servidor (filtra la página cargada)', () => {
      vi.useFakeTimers();
      try {
        const { el } = crear();
        escribir(el, 'camis');
        vi.advanceTimersByTime(1000);
        http.expectNone((peticion) => peticion.url.includes('buscar='));
      } finally {
        vi.useRealTimers();
      }
    });

    it('con la opción, espera un momento y consulta al servidor con ?buscar= desde la página 1', () => {
      vi.useFakeTimers();
      try {
        const { fixture, el } = crear({ busquedaServidor: true });

        escribir(el, 'ana');
        vi.advanceTimersByTime(100);
        http.expectNone((peticion) => peticion.url.includes('buscar='));
        vi.advanceTimersByTime(400);
        http.expectOne(`${URL}?pagina=1&tamanio=20&buscar=ana`).flush([FILAS[0]]);
        fixture.detectChanges();

        expect(el.querySelectorAll('tbody tr').length).toBe(1);
        expect(el.querySelector('.tg-conteo')?.textContent?.trim()).toBe('1 registro con esa búsqueda en esta página');
      } finally {
        vi.useRealTimers();
      }
    });

    it('varias teclas seguidas hacen UNA sola consulta, con el texto codificado y sin espacios en los bordes', () => {
      vi.useFakeTimers();
      try {
        const { el } = crear({ busquedaServidor: true });

        escribir(el, 'a');
        vi.advanceTimersByTime(100);
        escribir(el, 'ana g');
        vi.advanceTimersByTime(100);
        escribir(el, '  ana gómez ');
        vi.advanceTimersByTime(400);

        http.expectOne(`${URL}?pagina=1&tamanio=20&buscar=ana%20g%C3%B3mez`).flush([]);
      } finally {
        vi.useRealTimers();
      }
    });

    it('al buscar vuelve a la página 1 y la paginación conserva el texto', () => {
      vi.useFakeTimers();
      try {
        const { fixture, el } = crear({ busquedaServidor: true, tamanioPagina: 2 });
        (el.querySelector('[aria-label="Siguiente"]') as HTMLButtonElement).click();
        http.expectOne(`${URL}?pagina=2&tamanio=2`).flush(FILAS);
        fixture.detectChanges();

        escribir(el, 'ca');
        vi.advanceTimersByTime(400);
        http.expectOne(`${URL}?pagina=1&tamanio=2&buscar=ca`).flush(FILAS);
        fixture.detectChanges();

        (el.querySelector('[aria-label="Siguiente"]') as HTMLButtonElement).click();
        http.expectOne(`${URL}?pagina=2&tamanio=2&buscar=ca`).flush([]);
      } finally {
        vi.useRealTimers();
      }
    });

    it('borrar el texto vuelve a la lista completa', () => {
      vi.useFakeTimers();
      try {
        const { fixture, el } = crear({ busquedaServidor: true });
        escribir(el, 'ana');
        vi.advanceTimersByTime(400);
        http.expectOne(`${URL}?pagina=1&tamanio=20&buscar=ana`).flush([]);

        escribir(el, '');
        vi.advanceTimersByTime(400);
        http.expectOne(`${URL}?pagina=1&tamanio=20`).flush(FILAS);
        fixture.detectChanges();

        expect(el.querySelectorAll('tbody tr').length).toBe(2);
        expect(el.querySelector('.tg-conteo')?.textContent?.trim()).toBe('2 registros en esta página');
      } finally {
        vi.useRealTimers();
      }
    });

    it('sin coincidencias dice "Sin resultados" con el texto buscado', () => {
      vi.useFakeTimers();
      try {
        const { fixture, el } = crear({ busquedaServidor: true });
        escribir(el, 'zzz');
        vi.advanceTimersByTime(400);
        http.expectOne(`${URL}?pagina=1&tamanio=20&buscar=zzz`).flush([]);
        fixture.detectChanges();

        expect(el.querySelector('.fs-estado-vacio')?.textContent).toContain('Sin resultados para «zzz».');
      } finally {
        vi.useRealTimers();
      }
    });

    it('una respuesta vieja que llega tarde no pisa a la más reciente', () => {
      vi.useFakeTimers();
      try {
        const { fixture, el } = crear({ busquedaServidor: true });
        escribir(el, 'a');
        vi.advanceTimersByTime(400);
        const vieja = http.expectOne(`${URL}?pagina=1&tamanio=20&buscar=a`);
        escribir(el, 'ana');
        vi.advanceTimersByTime(400);
        const nueva = http.expectOne(`${URL}?pagina=1&tamanio=20&buscar=ana`);

        nueva.flush([FILAS[0]]);
        vieja.flush(FILAS); // llega después, pero es de una búsqueda anterior
        fixture.detectChanges();

        expect(el.querySelectorAll('tbody tr').length).toBe(1);
      } finally {
        vi.useRealTimers();
      }
    });

    it('el buscador se nombra "Buscar" (no "en esta página") y no queda un temporizador al destruir', () => {
      vi.useFakeTimers();
      try {
        const { fixture, el } = crear({ busquedaServidor: true });
        expect(el.querySelector('input[type="search"]')?.getAttribute('aria-label')).toBe('Buscar');

        escribir(el, 'ana');
        fixture.destroy();
        vi.advanceTimersByTime(1000);
        http.expectNone((peticion) => peticion.url.includes('buscar='));
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
