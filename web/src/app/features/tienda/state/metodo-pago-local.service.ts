import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { MetodoPagoPaypal } from '../../../core/models/metodo-pago.models';
import { META_METODO_PAGO } from '../../../core/offline-cliente/cliente-offline.config';
import type { MetodoPagoRecordado } from '../../../core/offline-cliente/cliente-offline.models';
import { ClienteOfflineService } from '../../../core/offline-cliente/cliente-offline.service';
import { MetodoPagoService } from '../data/metodo-pago.service';

/**
 * Lo que el navegador recuerda del método de pago para decidir SIN red: solo "tiene PayPal guardado" y el correo
 * enmascarado que devolvió el servidor (nunca un token de PayPal ni datos de tarjeta). Se actualiza cada vez que se
 * consulta, guarda o quita con conexión; se borra al cerrar sesión.
 */
@Injectable({ providedIn: 'root' })
export class MetodoPagoLocalService {
  private readonly cliente = inject(ClienteOfflineService);
  private readonly api = inject(MetodoPagoService);

  private readonly recordadoState = signal<MetodoPagoRecordado | null>(null);
  readonly recordado = this.recordadoState.asReadonly();
  /** Verdadero solo si el servidor confirmó, alguna vez, que hay un PayPal guardado. */
  readonly tienePaypal = computed(() => this.recordadoState()?.guardado === true);

  constructor() {
    effect(() => {
      this.cliente.alcance();
      untracked(() => void this.cargar());
    });
  }

  async cargar(): Promise<void> {
    const repo = this.cliente.repositorio();
    if (repo === null) {
      this.recordadoState.set(null);
      return;
    }
    try {
      const valor = (await repo.leerMeta<MetodoPagoRecordado>(META_METODO_PAGO)) ?? null;
      if (this.cliente.repositorio()?.alcance.usuarioId === repo.alcance.usuarioId) this.recordadoState.set(valor);
    } catch (error) {
      console.warn('No se pudo leer el método de pago recordado.', error);
    }
  }

  /** Recuerda el estado que acaba de dar el servidor. Nunca lanza. */
  async recordar(estado: MetodoPagoPaypal): Promise<void> {
    const recordado: MetodoPagoRecordado = {
      guardado: estado.guardado,
      correo_paypal: estado.guardado ? estado.correo_paypal : null,
      guardado_en: estado.guardado ? estado.guardado_en : null,
      verificado_en: new Date().toISOString(),
    };
    this.recordadoState.set(recordado);
    const repo = this.cliente.repositorio();
    if (repo === null) return;
    try {
      await repo.guardarMeta(META_METODO_PAGO, recordado);
    } catch (error) {
      console.warn('No se pudo recordar el método de pago.', error);
    }
  }

  /** Con conexión, pregunta al servidor y recuerda la respuesta. Si falla, queda lo que ya se recordaba. */
  async refrescar(): Promise<MetodoPagoPaypal | null> {
    try {
      const estado = await firstValueFrom(this.api.estado());
      await this.recordar(estado);
      return estado;
    } catch {
      return null;
    }
  }
}
