import { isPlatformBrowser } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Title } from '@angular/platform-browser';
import { ActivatedRoute } from '@angular/router';
import { ContratacionService, IR_A_PAYPAL, esUrlHttps } from '../../core/contratacion.service';
import { ErrorContratacion, errorDeContratacion, mensajeDeContratacion } from '../../core/mensajes-contratacion';
import { PedidoSolicitud, PruebaRespuesta, PruebaSolicitud } from '../../core/models/contratacion.models';
import { PlanesPublicosService } from '../../core/planes-publicos.service';
import {
  DIAS_PRUEBA,
  PeriodoPlan,
  aNumeroBs,
  formatearBs,
  montoDelPeriodo,
  tienePrecio,
} from '../../core/utils/precio-plan';
import { IconoComponent } from '../../shared/icono/icono.component';
import { ContratacionListoComponent } from './contratacion-listo.component';
import { ContratarMarcoComponent } from './contratar-marco.component';
import { ModoContratacion, ResumenPlanComponent } from './resumen-plan.component';

type Paso = 'datos' | 'pago' | 'listo';

type CampoFormulario = 'empresa' | 'nombre' | 'apellido' | 'email' | 'telefono' | 'password';

/** Errores del servidor que se corrigen en el primer paso (los datos), no en el de pago. */
const ERRORES_DE_DATOS: ReadonlySet<string> = new Set([
  'plan_sin_precio',
  'plan_no_encontrado',
  'nombre_empresa_reservado',
  'nombre_repetido',
  'prueba_ya_usada',
  'datos_invalidos',
]);

/**
 * `/contratar`: el comprador elige plan y modo (prueba gratis de 14 días o contratar ahora), escribe el nombre de su
 * empresa y los datos del administrador, y:
 * - en prueba, la empresa se crea de inmediato (`POST /contratacion/prueba`);
 * - al contratar, se crea un pedido, se guarda su token en sessionStorage y se lleva al comprador a PayPal. La empresa
 *   se crea al volver (`/contratar/retorno`), cuando el servidor confirma el pago.
 *
 * Nunca se manda un monto: el servidor recalcula todo desde el precio del plan. Los errores se muestran aquí.
 */
@Component({
  selector: 'app-contratar',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    IconoComponent,
    ContratarMarcoComponent,
    ResumenPlanComponent,
    ContratacionListoComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './contratar.component.html',
  styleUrl: './contratar.component.scss',
})
export class ContratarComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly ruta = inject(ActivatedRoute);
  private readonly servicio = inject(ContratacionService);
  private readonly irAPaypal = inject(IR_A_PAYPAL);
  private readonly titulo = inject(Title);
  private readonly esNavegador = isPlatformBrowser(inject(PLATFORM_ID));
  protected readonly planesPublicos = inject(PlanesPublicosService);

  protected readonly diasPrueba = DIAS_PRUEBA;

  // ---- Estado (lo que la dirección trae: ?plan=<codigo>&modo=prueba|pago&periodo=mensual|anual) --------------------
  protected readonly modo = signal<ModoContratacion>(this.ruta.snapshot.queryParamMap.get('modo') === 'pago' ? 'pago' : 'prueba');
  protected readonly periodo = signal<PeriodoPlan>(this.ruta.snapshot.queryParamMap.get('periodo') === 'anual' ? 'anual' : 'mensual');
  protected readonly codigoPlan = signal<string | null>(this.ruta.snapshot.queryParamMap.get('plan'));
  protected readonly paso = signal<Paso>('datos');

  protected readonly enviando = signal(false);
  protected readonly error = signal<ErrorContratacion | null>(null);
  protected readonly verClave = signal(false);
  protected readonly resultado = signal<PruebaRespuesta | null>(null);
  protected readonly correoListo = signal<string | null>(null);

  protected readonly plan = computed(
    () => this.planesPublicos.planes().find((p) => p.codigo === this.codigoPlan()) ?? null,
  );
  /** Vino un plan en la dirección pero no está entre los activos (ya se cargaron). */
  protected readonly planNoDisponible = computed(
    () =>
      this.codigoPlan() !== null &&
      this.plan() === null &&
      !this.planesPublicos.cargando() &&
      !this.planesPublicos.error() &&
      this.planesPublicos.planes().length > 0,
  );
  protected readonly alPagar = computed(() => this.modo() === 'pago');

  protected readonly pasos = computed<{ id: Paso; nombre: string }[]>(() =>
    this.alPagar()
      ? [
          { id: 'datos', nombre: 'Datos' },
          { id: 'pago', nombre: 'Pago' },
          { id: 'listo', nombre: 'Listo' },
        ]
      : [
          { id: 'datos', nombre: 'Datos' },
          { id: 'listo', nombre: 'Listo' },
        ],
  );

  /** Lo que se mostrará como total en la revisión (solo para mirar: el servidor lo recalcula). */
  protected readonly totalMostrado = computed(() => {
    const mensual = aNumeroBs(this.plan()?.precio_mensual_bs);
    if (mensual === null) return '';
    return formatearBs(montoDelPeriodo(mensual, this.periodo()));
  });
  protected readonly textoPeriodo = computed(() => (this.periodo() === 'anual' ? 'Anual (12 meses)' : 'Mensual (30 días)'));

  protected readonly formulario = this.fb.nonNullable.group({
    empresa: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(120)]],
    nombre: ['', [Validators.required, Validators.maxLength(60)]],
    apellido: ['', [Validators.required, Validators.maxLength(60)]],
    email: ['', [Validators.required, Validators.email, Validators.maxLength(120)]],
    telefono: ['', [Validators.maxLength(20)]],
    password: ['', [Validators.required, Validators.minLength(8), Validators.maxLength(72)]],
  });

  ngOnInit(): void {
    this.titulo.setTitle('Contratar un plan | FashionStore');
    if (this.esNavegador && this.planesPublicos.planes().length === 0 && !this.planesPublicos.cargando()) {
      this.planesPublicos.cargar();
    }
  }

  // ---- Elecciones ---------------------------------------------------------------------------------------------

  protected elegirModo(modo: ModoContratacion): void {
    if (this.enviando() || this.paso() === 'listo') return;
    this.modo.set(modo);
    this.paso.set('datos');
    this.error.set(null);
  }

  protected elegirPlan(codigo: string): void {
    if (this.enviando()) return;
    this.codigoPlan.set(codigo);
    this.error.set(null);
  }

  protected elegirPeriodo(periodo: PeriodoPlan): void {
    if (this.enviando()) return;
    this.periodo.set(periodo);
  }

  protected conPrecio(precio: string | null): boolean {
    return tienePrecio(precio);
  }

  protected precioDe(precio: string | null): string {
    return tienePrecio(precio) ? `${formatearBs(precio)} al mes` : 'A consultar';
  }

  protected reintentarPlanes(): void {
    this.planesPublicos.cargar();
  }

  // ---- Formulario ---------------------------------------------------------------------------------------------

  protected errorDe(campo: CampoFormulario): string | null {
    const control = this.formulario.controls[campo];
    if (!control.invalid || !(control.touched || control.dirty)) return null;
    if (control.hasError('required')) {
      return campo === 'email' ? 'Escribe tu correo.' : 'Este dato es obligatorio.';
    }
    if (control.hasError('email')) return 'Escribe un correo válido, por ejemplo ana@miboutique.bo.';
    if (control.hasError('minlength')) {
      const minimo = control.getError('minlength').requiredLength as number;
      return campo === 'password'
        ? `Usa al menos ${minimo} caracteres.`
        : `Escribe al menos ${minimo} caracteres.`;
    }
    if (control.hasError('maxlength')) {
      return `Es demasiado largo (máximo ${control.getError('maxlength').requiredLength as number} caracteres).`;
    }
    return 'Revisa este dato.';
  }

  /** "Continuar" del primer paso: prueba -> crea la empresa; pago -> pasa a revisar y pagar. */
  protected enviar(): void {
    if (this.enviando()) return;
    this.error.set(null);
    this.formulario.markAllAsTouched();

    const plan = this.plan();
    if (plan === null) {
      this.error.set({
        codigo: 'sin_plan',
        status: 0,
        mensaje: 'Elige un plan para continuar.',
        reintentable: false,
      });
      return;
    }
    if (this.formulario.invalid) return;

    if (this.alPagar()) {
      if (!tienePrecio(plan.precio_mensual_bs)) {
        this.error.set(this.errorPropio('plan_sin_precio'));
        return;
      }
      this.paso.set('pago');
      return;
    }
    this.empezarPrueba(this.solicitud(plan.codigo));
  }

  protected volverADatos(): void {
    if (this.enviando()) return;
    this.error.set(null);
    this.paso.set('datos');
  }

  /** "Pagar con PayPal": crea el pedido, guarda su token y manda al comprador a PayPal. */
  protected pagar(): void {
    const plan = this.plan();
    if (this.enviando() || plan === null || this.formulario.invalid) return;
    this.enviando.set(true);
    this.error.set(null);

    const pedido: PedidoSolicitud = { ...this.solicitud(plan.codigo), periodo: this.periodo() };
    this.servicio.crearPedido(pedido).subscribe({
      next: (creado) => {
        if (!esUrlHttps(creado.url_aprobacion)) {
          // Un pedido sin un enlace seguro a PayPal no se puede pagar: se avisa y no se redirige.
          this.enviando.set(false);
          this.error.set(this.errorPropio('paypal_no_disponible'));
          return;
        }
        // El token se guarda ANTES de salir: es lo que permite cerrar el pedido al volver de PayPal.
        this.servicio.guardarToken(creado.token);
        // `enviando` queda en true: el botón no se puede volver a pulsar mientras el navegador sale.
        this.irAPaypal(creado.url_aprobacion);
      },
      error: (falla: unknown) => this.fallar(falla),
    });
  }

  // ---- Internos -----------------------------------------------------------------------------------------------

  private empezarPrueba(solicitud: PruebaSolicitud): void {
    this.enviando.set(true);
    this.servicio.iniciarPrueba(solicitud).subscribe({
      next: (respuesta) => {
        this.correoListo.set(solicitud.administrador.email.toLowerCase());
        this.resultado.set(respuesta);
        this.paso.set('listo');
        this.enviando.set(false);
        // Ya no hace falta la contraseña en la página.
        this.formulario.reset();
      },
      error: (falla: unknown) => this.fallar(falla),
    });
  }

  private solicitud(planCodigo: string): PruebaSolicitud {
    const v = this.formulario.getRawValue();
    const telefono = v.telefono.trim();
    return {
      nombre: v.empresa.trim(),
      plan_codigo: planCodigo,
      administrador: {
        nombre: v.nombre.trim(),
        apellido: v.apellido.trim(),
        email: v.email.trim(),
        ...(telefono !== '' ? { telefono } : {}),
        password: v.password,
      },
    };
  }

  private fallar(falla: unknown): void {
    const error = errorDeContratacion(falla);
    this.enviando.set(false);
    this.error.set(error);
    if (ERRORES_DE_DATOS.has(error.codigo)) this.paso.set('datos');
  }

  private errorPropio(codigo: string): ErrorContratacion {
    return { codigo, status: 0, mensaje: mensajeDeContratacion(codigo) ?? '', reintentable: false };
  }
}
