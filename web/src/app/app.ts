import { Component, inject } from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';
import { MessageService, ToastMessageOptions } from 'primeng/api';
import { ToastModule } from 'primeng/toast';
import { CLAVE_TOAST_AVISO } from './core/push/push-comun';
import { AvisoPwaComponent } from './shared/aviso-pwa/aviso-pwa.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, ToastModule, AvisoPwaComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly router = inject(Router);
  private readonly mensajes = inject(MessageService);

  /** Los avisos push con la pestaña abierta salen en su propio toast (con botón "Ver"). */
  protected readonly claveToastAviso = CLAVE_TOAST_AVISO;

  /** "Ver" en un aviso push: va a la pantalla del aviso y lo cierra. */
  protected verAviso(mensaje: ToastMessageOptions): void {
    const ruta = (mensaje.data as { ruta?: string | null } | undefined)?.ruta;
    this.mensajes.clear(CLAVE_TOAST_AVISO);
    if (ruta) void this.router.navigateByUrl(ruta);
  }
}
