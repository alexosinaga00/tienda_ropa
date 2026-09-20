import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import {
  CotizacionEnvio,
  CotizarEnvioRequest,
  DireccionCliente,
  DireccionClienteCrear,
  Envio,
  EnvioCrear,
  ZonaEnvio,
} from '../../../core/models/entregas.models';

@Injectable({ providedIn: 'root' })
export class DireccionesService {
  private readonly http = inject(HttpClient);

  listarMisDirecciones(): Observable<DireccionCliente[]> {
    return this.http.get<DireccionCliente[]>(`${environment.apiUrl}/clientes/direcciones`);
  }

  crearDireccion(datos: DireccionClienteCrear): Observable<DireccionCliente> {
    return this.http.post<DireccionCliente>(`${environment.apiUrl}/clientes/direcciones`, datos);
  }

  listarZonas(): Observable<ZonaEnvio[]> {
    return this.http.get<ZonaEnvio[]>(`${environment.apiUrl}/zonas-envio`, { params: { tamanio: 100 } });
  }

  cotizar(datos: CotizarEnvioRequest): Observable<CotizacionEnvio> {
    return this.http.post<CotizacionEnvio>(`${environment.apiUrl}/envios/cotizar`, datos);
  }

  crearEnvio(datos: EnvioCrear): Observable<Envio> {
    return this.http.post<Envio>(`${environment.apiUrl}/envios`, datos);
  }

  /** Seguimiento del envío de una compra (dueño de la compra o personal). */
  obtenerEnvioDeVenta(ventaId: number): Observable<Envio> {
    return this.http.get<Envio>(`${environment.apiUrl}/envios/venta/${ventaId}`);
  }
}
