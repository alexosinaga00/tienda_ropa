import { HttpClient } from '@angular/common/http';
import { Component, OnInit, ViewChild, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { environment } from '../../../environments/environment';
import { Empleado } from '../../core/models/organizacion.models';
import { Sucursal } from '../../core/models/organizacion.models';
import { Usuario } from '../../core/models/seguridad.models';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Empleado>[] = [
  { campo: 'usuario_nombre', encabezado: 'Nombre' },
  { campo: 'usuario_apellido', encabezado: 'Apellido' },
  { campo: 'sucursal_nombre', encabezado: 'Sucursal' },
  { campo: 'cargo', encabezado: 'Cargo' },
  { campo: 'ci', encabezado: 'CI' },
  { campo: 'fecha_ingreso', encabezado: 'Ingreso', tipo: 'fecha' },
  { campo: 'activo', encabezado: 'Activo', tipo: 'booleano' },
];

interface OpcionUsuario {
  id: number;
  etiqueta: string;
}

@Component({
  selector: 'app-empleados',
  standalone: true,
  imports: [ReactiveFormsModule, ButtonModule, DialogModule, InputTextModule, SelectModule, TablaGenericaComponent],
  templateUrl: './empleados.component.html',
})
export class EmpleadosComponent implements OnInit {
  protected readonly columnas = COLUMNAS;
  protected readonly dialogoVisible = signal(false);
  protected readonly editando = signal<Empleado | null>(null);
  protected readonly sucursales = signal<Sucursal[]>([]);

  private readonly usuarios = signal<Usuario[]>([]);
  protected readonly opcionesUsuario = computed<OpcionUsuario[]>(() =>
    this.usuarios()
      .filter((u) => u.roles.includes('cajero') || u.roles.includes('encargado_sucursal'))
      .map((u) => ({ id: u.id, etiqueta: `${u.nombre} ${u.apellido} (${u.email})` })),
  );

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Empleado>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);

  protected readonly formulario = this.fb.nonNullable.group({
    usuario_id: [null as number | null, Validators.required],
    sucursal_id: [null as number | null],
    cargo: [''],
    ci: [''],
    fecha_ingreso: [''],
  });

  ngOnInit(): void {
    this.http
      .get<Usuario[]>(`${environment.apiUrl}/usuarios?pagina=1&tamanio=100`)
      .subscribe((usuarios) => this.usuarios.set(usuarios));
    this.http
      .get<Sucursal[]>(`${environment.apiUrl}/sucursales?pagina=1&tamanio=100`)
      .subscribe((sucursales) => this.sucursales.set(sucursales));
  }

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({ usuario_id: null, sucursal_id: null, cargo: '', ci: '', fecha_ingreso: '' });
    this.formulario.controls.usuario_id.enable();
    this.dialogoVisible.set(true);
  }

  abrirEditar(empleado: Empleado): void {
    this.editando.set(empleado);
    this.formulario.reset({
      usuario_id: empleado.usuario_id,
      sucursal_id: empleado.sucursal_id,
      cargo: empleado.cargo ?? '',
      ci: empleado.ci ?? '',
      fecha_ingreso: empleado.fecha_ingreso ?? '',
    });
    this.formulario.controls.usuario_id.disable(); // el empleado ya quedó vinculado a ese usuario al crearlo
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const empleado = this.editando();
    const valores = this.formulario.getRawValue();
    const peticion = empleado
      ? this.http.put(`${environment.apiUrl}/empleados/${empleado.id}`, {
          sucursal_id: valores.sucursal_id,
          cargo: valores.cargo || null,
          ci: valores.ci || null,
          fecha_ingreso: valores.fecha_ingreso || null,
        })
      : this.http.post(`${environment.apiUrl}/empleados`, {
          usuario_id: valores.usuario_id,
          sucursal_id: valores.sucursal_id,
          cargo: valores.cargo || null,
          ci: valores.ci || null,
          fecha_ingreso: valores.fecha_ingreso || null,
        });

    peticion.subscribe(() => {
      this.dialogoVisible.set(false);
      this.tabla.recargar();
    });
  }
}
