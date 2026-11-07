import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { AuthService } from '../../core/auth.service';
import { ConectividadService } from '../../core/conectividad.service';
import { nuevoEntorno, pedido } from '../../core/offline-cliente/ayudas-prueba';
import { ClienteOfflineService } from '../../core/offline-cliente/cliente-offline.service';
import { TiendaShellComponent } from './tienda-shell.component';
import { TiendaActualService } from './state/tienda-actual.service';

@Component({ template: '' })
class PaginaVacia {}

/** El diálogo "Tienes N pedidos sin enviar" al tocar "Salir" (solo la salida que elige el cliente). */
describe('TiendaShellComponent: salir con pedidos sin enviar', () => {
  let entorno: ReturnType<typeof nuevoEntorno>;
  let fixture: ComponentFixture<TiendaShellComponent>;
  let el: HTMLElement;
  const logout = vi.fn();

  async function esperar(): Promise<void> {
    for (let i = 0; i < 30; i++) await new Promise<void>((r) => setTimeout(r, 0));
    fixture.detectChanges();
  }

  async function montar(pedidos: ReturnType<typeof pedido>[]): Promise<void> {
    for (const p of pedidos) await entorno.repo().registrarPedido(p);
    TestBed.configureTestingModule({
      imports: [TiendaShellComponent],
      providers: [
        provideRouter([{ path: '**', component: PaginaVacia }]),
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        {
          provide: AuthService,
          useValue: { estaAutenticado: () => true, empresaCodigo: () => 'acme', logout },
        },
        { provide: ClienteOfflineService, useValue: entorno.cliente },
        { provide: ConectividadService, useValue: entorno.conectividad },
      ],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', { codigo: 'acme', nombre: 'Acme', logo_url: null, color_acento: null });
    fixture = TestBed.createComponent(TiendaShellComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    await esperar();
  }

  const q = (estado: string) => el.querySelector<HTMLElement>(`[data-estado="${estado}"]`);
  const salir = () => Array.from(el.querySelectorAll<HTMLButtonElement>('button.cab__enlace')).find((b) => b.textContent?.includes('Salir'))!;

  beforeEach(() => {
    logout.mockReset();
    entorno = nuevoEntorno();
    // Sin conexión: la cola no intenta enviar nada mientras se prueba el diálogo.
    entorno.enLinea.set(false);
  });

  afterEach(async () => {
    for (let i = 0; i < 20; i++) await new Promise<void>((r) => setTimeout(r, 0));
    TestBed.resetTestingModule();
    await entorno.cerrar();
  });

  it('sin pedidos sin enviar sale directo, sin diálogo', async () => {
    await montar([]);

    salir().click();
    fixture.detectChanges();

    expect(q('dialogo-salida')).toBeNull();
    expect(logout).toHaveBeenCalledTimes(1);
  });

  it('con pedidos sin enviar pregunta primero: "Tienes N pedidos sin enviar", y todavía no sale', async () => {
    await montar([pedido(1), pedido(2, { estado: 'enviando', ultimo_intento_en: new Date().toISOString() })]);

    salir().click();
    fixture.detectChanges();

    expect(logout).not.toHaveBeenCalled();
    const dialogo = q('dialogo-salida')!;
    expect(dialogo.getAttribute('role')).toBe('alertdialog');
    expect(dialogo.querySelector('h2')?.textContent).toContain('Tienes 2 pedidos sin enviar');
    expect(q('conservar-pedidos')?.textContent).toContain('Conservarlos');
    expect(q('borrar-pedidos')?.textContent).toContain('Borrarlos y salir');
  });

  it('con un solo pedido lo dice en singular', async () => {
    await montar([pedido(1)]);

    salir().click();
    fixture.detectChanges();

    expect(q('dialogo-salida')?.querySelector('h2')?.textContent).toContain('Tienes 1 pedido sin enviar');
  });

  it('"Conservarlos" sale y deja los pedidos en el equipo', async () => {
    await montar([pedido(1)]);
    salir().click();
    fixture.detectChanges();

    (q('conservar-pedidos') as HTMLButtonElement).click();
    fixture.detectChanges();
    await esperar();

    expect(logout).toHaveBeenCalledTimes(1);
    expect(q('dialogo-salida')).toBeNull();
    expect(await entorno.repo().pedidos()).toHaveLength(1);
  });

  it('"Borrarlos y salir" borra los pedidos del dispositivo y luego sale', async () => {
    await montar([pedido(1), pedido(2)]);
    await entorno.repo(1, 9).registrarPedido(pedido(3, { usuario_id: 9 }));
    salir().click();
    fixture.detectChanges();

    (q('borrar-pedidos') as HTMLButtonElement).click();
    await esperar();

    expect(await entorno.repo().pedidos()).toEqual([]);
    expect(logout).toHaveBeenCalledTimes(1);
    expect(q('dialogo-salida')).toBeNull();
    // Los de otra cuenta del mismo equipo no se tocan.
    expect(await entorno.repo(1, 9).pedidos()).toHaveLength(1);
  });

  it('Escape o tocar fuera cierra el diálogo SIN salir', async () => {
    await montar([pedido(1)]);
    salir().click();
    fixture.detectChanges();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();

    expect(q('dialogo-salida')).toBeNull();
    expect(logout).not.toHaveBeenCalled();

    salir().click();
    fixture.detectChanges();
    el.querySelector<HTMLElement>('.salida-fondo')!.click();
    fixture.detectChanges();
    expect(q('dialogo-salida')).toBeNull();
    expect(logout).not.toHaveBeenCalled();
  });

  it('los pedidos vencidos o ya resueltos no cuentan: sale directo', async () => {
    await montar([pedido(1, { estado: 'vencido' }), pedido(2, { estado: 'cobrado' }), pedido(3, { estado: 'rechazado' })]);

    salir().click();
    fixture.detectChanges();

    expect(q('dialogo-salida')).toBeNull();
    expect(logout).toHaveBeenCalledTimes(1);
  });
});
