import { HttpClient } from '@angular/common/http';
import { Component, ViewChild, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { environment } from '../../../environments/environment';
import { Permiso, Rol } from '../../core/models/seguridad.models';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Rol>[] = [
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'descripcion', encabezado: 'Descripción' },
  { campo: 'activo', encabezado: 'Activo', tipo: 'booleano' },
];

/** Permisos de un módulo, para pintarlos agrupados en vez de como una lista
 * larga y plana. El backend ya los devuelve ordenados por módulo y código. */
interface GrupoPermisos {
  modulo: string;
  permisos: Permiso[];
}

@Component({
  selector: 'app-roles',
  standalone: true,
  imports: [ReactiveFormsModule, ButtonModule, DialogModule, InputTextModule, TablaGenericaComponent],
  templateUrl: './roles.component.html',
  styleUrl: './roles.component.scss',
})
export class RolesComponent {
  protected readonly columnas = COLUMNAS;
  protected readonly dialogoVisible = signal(false);
  protected readonly editando = signal<Rol | null>(null);

  // ---- Permisos por rol (RF03) ----
  protected readonly dialogoPermisos = signal(false);
  protected readonly rolPermisos = signal<Rol | null>(null);
  protected readonly grupos = signal<GrupoPermisos[]>([]);
  protected readonly seleccionados = signal<Set<string>>(new Set());
  protected readonly guardandoPermisos = signal(false);

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Rol>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly messageService = inject(MessageService);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', Validators.required],
    descripcion: [''],
  });

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({ nombre: '', descripcion: '' });
    this.dialogoVisible.set(true);
  }

  abrirEditar(rol: Rol): void {
    this.editando.set(rol);
    this.formulario.reset({ nombre: rol.nombre, descripcion: rol.descripcion ?? '' });
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const datos = this.formulario.getRawValue();
    const rol = this.editando();
    const peticion = rol
      ? this.http.put(`${environment.apiUrl}/roles/${rol.id}`, datos)
      : this.http.post(`${environment.apiUrl}/roles`, datos);

    peticion.subscribe(() => {
      this.dialogoVisible.set(false);
      this.tabla.recargar();
    });
  }

  /** Abre el diálogo de permisos del rol. Parte de los permisos que el rol ya
   * tiene (vienen en el propio Rol) y trae el catálogo completo para las
   * casillas. */
  abrirPermisos(rol: Rol): void {
    this.rolPermisos.set(rol);
    this.seleccionados.set(new Set((rol.permisos ?? []).map((p) => p.codigo)));
    this.grupos.set([]);
    this.dialogoPermisos.set(true);

    this.http.get<Permiso[]>(`${environment.apiUrl}/permisos`).subscribe({
      next: (permisos) => this.grupos.set(this.agrupar(permisos)),
      error: () => {
        // Sin catálogo no hay nada que tildar: se cierra en vez de dejar un
        // diálogo vacío que parezca "este rol no tiene permisos posibles".
        this.dialogoPermisos.set(false);
        this.messageService.add({
          severity: 'error',
          summary: 'No se pudieron cargar los permisos',
          detail: 'Probá de nuevo en un momento.',
        });
      },
    });
  }

  private agrupar(permisos: Permiso[]): GrupoPermisos[] {
    const porModulo = new Map<string, Permiso[]>();
    for (const permiso of permisos) {
      const actuales = porModulo.get(permiso.modulo) ?? [];
      actuales.push(permiso);
      porModulo.set(permiso.modulo, actuales);
    }
    return [...porModulo.entries()].map(([modulo, lista]) => ({ modulo, permisos: lista }));
  }

  protected estaMarcado(codigo: string): boolean {
    return this.seleccionados().has(codigo);
  }

  protected alternarPermiso(codigo: string): void {
    this.seleccionados.update((actuales) => {
      // Set nuevo, no mutado: si se muta el mismo objeto el signal no avisa
      // del cambio y las casillas no se repintan.
      const copia = new Set(actuales);
      if (copia.has(codigo)) {
        copia.delete(codigo);
      } else {
        copia.add(codigo);
      }
      return copia;
    });
  }

  protected alternarModulo(grupo: GrupoPermisos): void {
    const todosPuestos = grupo.permisos.every((p) => this.seleccionados().has(p.codigo));
    this.seleccionados.update((actuales) => {
      const copia = new Set(actuales);
      for (const permiso of grupo.permisos) {
        if (todosPuestos) {
          copia.delete(permiso.codigo);
        } else {
          copia.add(permiso.codigo);
        }
      }
      return copia;
    });
  }

  protected moduloCompleto(grupo: GrupoPermisos): boolean {
    return grupo.permisos.length > 0 && grupo.permisos.every((p) => this.seleccionados().has(p.codigo));
  }

  guardarPermisos(): void {
    const rol = this.rolPermisos();
    if (!rol || this.guardandoPermisos()) return;

    this.guardandoPermisos.set(true);
    // El endpoint REEMPLAZA la lista completa, no es incremental: se manda
    // todo lo tildado, y lo que no está se quita.
    const codigos_permiso = [...this.seleccionados()];

    this.http.put<Rol>(`${environment.apiUrl}/roles/${rol.id}/permisos`, { codigos_permiso }).subscribe({
      next: () => {
        this.guardandoPermisos.set(false);
        this.dialogoPermisos.set(false);
        this.tabla.recargar();
        this.messageService.add({
          severity: 'success',
          summary: 'Permisos actualizados',
          // El backend resuelve los permisos contra la base en cada petición
          // (core/security.py), no contra el token: por eso el cambio se nota
          // sin que nadie tenga que volver a iniciar sesión.
          detail: `El rol ${rol.nombre} quedó con ${codigos_permiso.length} permisos. Se aplica de inmediato.`,
        });
      },
      error: () => this.guardandoPermisos.set(false),
    });
  }
}
