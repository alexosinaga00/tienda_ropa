import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { RUTA_LOGIN_PERSONAL } from '../../../core/auth.service';
import { PlanPublico } from '../../../core/models/plan.models';
import { acentoSobreOscuro, calcularPaletaAcento } from '../../../core/utils/color';
import { DIAS_PRUEBA } from '../../../core/utils/precio-plan';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { MarcaComponent } from '../../../shared/marca/marca.component';
import { MarcaDemo, PlanEscena, TiendaEscena } from '../escena-3d/contrato';
import { EscenaTiendaComponent } from '../escena-3d/escena-tienda.component';
import { PlanesComparativoComponent } from '../planes-comparativo/planes-comparativo.component';

/** Lo que la historia necesita de cada tienda de la lista (la tarjeta de la portada ya lo trae). */
export interface TiendaHistoria {
  codigo: string;
  nombre: string;
  /** "#rrggbb" del acento de la empresa ya resuelto para superficies oscuras; null si no definió uno. */
  acentoOscuro: string | null;
}

/** Un punto de navegación por sección del recorrido, más "Buscar tienda" (el inicio de la lista, en 6 * innerHeight). */
export const PUNTOS_RECORRIDO: readonly string[] = [
  'Inicio',
  'Caja y ventas',
  'Inventario',
  'Probador virtual',
  'Planes',
  'Calle de tiendas',
  'Buscar tienda',
];

export const MAX_CARACTERES_NOMBRE = 24;
export const NOMBRE_INICIAL = 'Mi Boutique';
const NOMBRE_VACIO = 'Tu tienda';

/** Colores de demostración: la tela de la polera y, si el contraste no alcanza, el acento ya probado. */
const COLORES: readonly { nombre: string; tela: string; acentoPrototipo: string }[] = [
  { nombre: 'Lima', tela: '#8FAE5B', acentoPrototipo: '#8FAE5B' },
  { nombre: 'Hueso', tela: '#D8D3C6', acentoPrototipo: '#D8D3C6' },
  { nombre: 'Terracota', tela: '#9A3E1F', acentoPrototipo: '#E27B55' },
  { nombre: 'Azul petróleo', tela: '#1F5F73', acentoPrototipo: '#58B0CC' },
  { nombre: 'Mostaza', tela: '#C99A2E', acentoPrototipo: '#E5B94F' },
  { nombre: 'Vino', tela: '#7A2638', acentoPrototipo: '#E0607A' },
];

export interface ColorDemo {
  nombre: string;
  tela: string;
  /** Acento sobre las superficies oscuras de la historia. */
  acento: string;
  acentoHover: string;
  textoSobreAcento: string;
}

function resolverColor(base: (typeof COLORES)[number]): ColorDemo {
  const acento = calcularPaletaAcento(base.tela)?.sobreOscuro.acento ?? base.acentoPrototipo;
  const sobre = acentoSobreOscuro(acento);
  return { nombre: base.nombre, tela: base.tela, acento: sobre.acento, acentoHover: sobre.hover, textoSobreAcento: sobre.textoSobreAcento };
}

export const COLORES_DEMO: readonly ColorDemo[] = COLORES.map(resolverColor);

/**
 * "Modo historia" de la portada: la escena 3D fija detrás y, encima, seis secciones de una pantalla de
 * alto (inicio, caja, inventario, probador, planes y calle) que la recorren con el scroll. La demo de
 * marca del inicio no guarda nada: el color solo cambia DENTRO de este elemento.
 *
 * Las seis secciones miden exactamente 100svh y no tienen margen entre ellas: el motor calcula el
 * progreso como scrollY / (5 * innerHeight). La lista de tiendas de la portada va justo después.
 */
@Component({
  selector: 'app-historia-tienda',
  standalone: true,
  imports: [RouterLink, EscenaTiendaComponent, PlanesComparativoComponent, IconoComponent, MarcaComponent],
  templateUrl: './historia-tienda.component.html',
  styleUrl: './historia-tienda.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[style]': 'estilosMarca()' },
})
export class HistoriaTiendaComponent {
  readonly planes = input.required<readonly PlanPublico[]>();
  readonly tiendas = input.required<readonly TiendaHistoria[]>();
  readonly cargandoPlanes = input(false);
  readonly errorPlanes = input(false);

  /** El visitante eligió un local de la calle (código de la tienda). */
  readonly tiendaElegida = output<string>();
  readonly reintentarPlanes = output<void>();
  /** La escena no pudo crearse: la portada vuelve al diseño clásico. */
  readonly sinEscena = output<void>();

  protected readonly rutaAccesoPersonal = RUTA_LOGIN_PERSONAL;
  protected readonly rutaContratar = '/contratar';
  protected readonly diasPrueba = DIAS_PRUEBA;
  protected readonly puntos = PUNTOS_RECORRIDO;
  protected readonly colores = COLORES_DEMO;
  protected readonly maxCaracteres = MAX_CARACTERES_NOMBRE;
  protected readonly esqueletosPlanes = [1, 2, 3];

  // ---- Demo de marca (no se guarda en ningún lado) ------------------------------------------------
  protected readonly nombre = signal(NOMBRE_INICIAL);
  protected readonly colorElegido = signal<ColorDemo>(COLORES_DEMO[0]);

  /** Lo que recibe la escena: la polera, los locales y los planes se redibujan con esto. */
  readonly marca = computed<MarcaDemo>(() => ({
    nombre: this.nombre().trim() || NOMBRE_VACIO,
    tela: this.colorElegido().tela,
    acento: this.colorElegido().acento,
  }));

  protected readonly planesEscena = computed<PlanEscena[]>(() =>
    this.planes().map((p) => ({ codigo: p.codigo, nombre: p.nombre, sucursales: p.max_sucursales })),
  );

  protected readonly tiendasEscena = computed<TiendaEscena[]>(() =>
    this.tiendas().map((t) => ({ codigo: t.codigo, nombre: t.nombre, acento: t.acentoOscuro })),
  );

  /**
   * El acento de la demo se redefine solo en este elemento (como hace `tienda-raiz`): el resto de la
   * página, el back office y `document.documentElement` no se tocan, y al destruirse desaparece.
   */
  protected readonly estilosMarca = computed<Record<string, string>>(() => {
    const color = this.colorElegido();
    return {
      '--fs-acento-oscuro': color.acento,
      '--fs-acento-oscuro-hover': color.acentoHover,
      '--fs-sobre-acento-oscuro': color.textoSobreAcento,
      '--fs-acento': color.acento,
      '--fs-acento-hover': color.acentoHover,
      '--fs-acento-suave': `color-mix(in srgb, ${color.acento} 20%, transparent)`,
    };
  });

  // ---- Posición en el recorrido -------------------------------------------------------------------
  /** Punto activo: Math.round(scrollY / innerHeight). */
  protected readonly indice = signal(0);
  /** La lista de tiendas ya está bajo la barra: la barra pasa a fondo sólido. */
  protected readonly sobreLista = signal(false);
  /** Ya se bajó de la lista: los puntos del recorrido se esconden. */
  protected readonly pasada = signal(false);

  constructor() {
    const destroyRef = inject(DestroyRef);
    afterNextRender(() => {
      const alScroll = (): void => this.leerScroll();
      window.addEventListener('scroll', alScroll, { passive: true });
      window.addEventListener('resize', alScroll, { passive: true });
      destroyRef.onDestroy(() => {
        window.removeEventListener('scroll', alScroll);
        window.removeEventListener('resize', alScroll);
      });
      alScroll();
    });
  }

  private leerScroll(): void {
    const alto = Math.max(1, window.innerHeight);
    const y = window.scrollY;
    this.indice.set(Math.min(PUNTOS_RECORRIDO.length - 1, Math.max(0, Math.round(y / alto))));
    this.sobreLista.set(y >= 6 * alto - 80);
    this.pasada.set(y > 6.6 * alto);
  }

  protected irAPaso(i: number): void {
    const reducir = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: i * window.innerHeight, behavior: reducir ? 'auto' : 'smooth' });
  }

  protected onNombre(valor: string): void {
    this.nombre.set(valor.slice(0, MAX_CARACTERES_NOMBRE));
  }

  protected elegirColor(color: ColorDemo): void {
    this.colorElegido.set(color);
  }
}
