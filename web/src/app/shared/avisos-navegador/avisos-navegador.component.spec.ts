import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { EstadoAvisosPush, PushWebService } from '../../core/push/push-web.service';
import { AvisosNavegadorComponent } from './avisos-navegador.component';

describe('AvisosNavegadorComponent', () => {
  let fixture: ComponentFixture<AvisosNavegadorComponent>;
  const estado = signal<EstadoAvisosPush>('inactivo');
  const mensaje = signal<string | null>(null);
  const falso = {
    estado,
    mensaje,
    activar: vi.fn(),
    desactivar: vi.fn(),
    sincronizarSiActivo: vi.fn(async () => undefined),
  };

  function montar(contexto: 'cliente' | 'personal' = 'cliente') {
    TestBed.configureTestingModule({ providers: [{ provide: PushWebService, useValue: falso }] });
    fixture = TestBed.createComponent(AvisosNavegadorComponent);
    fixture.componentRef.setInput('contexto', contexto);
    fixture.detectChanges();
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const boton = (marca: string) => el().querySelector(`[data-estado="${marca}"]`) as HTMLButtonElement | null;
  const detalle = () => (el().querySelector('[data-estado="avisos-detalle"]')?.textContent ?? '').trim();

  beforeEach(() => {
    estado.set('inactivo');
    mensaje.set(null);
    vi.clearAllMocks();
  });

  it('al abrirse NO pide permiso: solo deja al día lo que ya estaba activado', () => {
    montar();

    expect(falso.sincronizarSiActivo).toHaveBeenCalledTimes(1);
    expect(falso.activar).not.toHaveBeenCalled();
  });

  it('apagado: ofrece "Activar avisos" y solo al tocarlo se activa', () => {
    montar();

    expect(boton('activar-avisos')?.textContent?.trim()).toBe('Activar avisos');
    expect(boton('desactivar-avisos')).toBeNull();
    boton('activar-avisos')!.click();
    expect(falso.activar).toHaveBeenCalledTimes(1);
  });

  it('activando: el botón se deshabilita y lo dice', () => {
    estado.set('activando');
    montar();

    expect(boton('activar-avisos')?.disabled).toBe(true);
    expect(boton('activar-avisos')?.textContent).toContain('Activando');
  });

  it('activo: ofrece desactivar', () => {
    estado.set('activo');
    montar();

    expect(boton('activar-avisos')).toBeNull();
    boton('desactivar-avisos')!.click();
    expect(falso.desactivar).toHaveBeenCalledTimes(1);
    expect(detalle()).toContain('Activados');
  });

  it.each<[EstadoAvisosPush, string]>([
    ['bloqueado', 'Bloqueaste los avisos'],
    ['no_soportado', 'no puede recibir avisos'],
    ['sin_https', 'https'],
  ])('%s: explica por qué y no ofrece ningún botón', (valor, texto) => {
    estado.set(valor);
    mensaje.set(texto);
    montar();

    expect(detalle()).toContain(texto);
    expect(boton('activar-avisos')).toBeNull();
    expect(boton('desactivar-avisos')).toBeNull();
  });

  it('el texto cambia según sea el cliente o el personal', () => {
    montar('personal');
    expect(detalle()).toContain('reservas');
    TestBed.resetTestingModule();
    montar('cliente');
    expect(detalle()).toContain('compra confirmada');
  });

  it('el botón es tocable (clases del sistema de diseño) y el ícono mide 24 px', () => {
    montar();

    expect(boton('activar-avisos')?.className).toContain('fs-btn');
    expect(el().querySelector('svg')?.getAttribute('width') ?? '24').toBe('24');
  });
});
