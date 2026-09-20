# Plan de desarrollo — FashionStore

Plataforma inteligente de comercio electrónico con vestidores virtuales
Sistemas II — S2-2026 · Período: 28/08/2026 → 22/09/2026

---

## Stack y decisiones cerradas

| Componente | Decisión |
|---|---|
| Backend | Python + FastAPI, monolito modular en 13 paquetes |
| Base de datos | PostgreSQL (47 tablas, esquema ya definido) |
| Migraciones | Alembic desde el primer commit |
| Web | Angular + PrimeNG — back office (admin, encargado, cajero) |
| Móvil | Flutter + Dart, Material 3 — cliente |
| Hosting API + BD | Railway (sin Docker, autodetección) |
| Hosting web | Vercel o Netlify (estático, gratis) |
| Imágenes | Cloudinary |
| Probador AR | Modo espejo: `google_mlkit_pose_detection` on-device |
| Probador IA | Modo realista: Vertex AI Virtual Try-On (opcional) |
| Voz | STT nativo del dispositivo (`speech_to_text`) → Groq → JSON de filtros |
| Recomendador | Groq (Llama) sobre historial + reglas |
| Chatbot | Botpress: widget en la web Angular y, desde el 20/09, el mismo bot en la app móvil (WebView) |
| Pagos | Libélula (nacional) + PayPal (internacional), ambos en sandbox |
| Metodología | PUDS + UML 2.5 |
| Alcance del probador | Prendas superiores masculinas |

**Regla transversal**: por cada módulo, primero backend (modelo → migración → servicio → endpoints probados en `/docs`), después el cliente. Nunca todo el backend primero y todo el frontend después.

---

## ETAPA 0 — Preparación
**28/08 → 31/08 (4 días)**

### Objetivo
Eliminar todos los bloqueadores externos antes de escribir código de negocio.

### Tareas de infraestructura
1. Repositorio en GitHub con tres carpetas: `backend/`, `web/`, `mobile/`. Rama `main` protegida, trabajo en `develop`.
2. Crear cuentas y obtener credenciales: Railway, Cloudinary, Groq, Google Cloud (crédito de $300), Libélula sandbox, PayPal developer.
3. **Verificar la tarjeta internacional.** Railway la exige, Google Cloud también. Este es el bloqueador más probable del proyecto.
4. Proyecto en Railway con dos servicios: PostgreSQL y la API. Variables de entorno configuradas.
5. Proyecto en Vercel apuntando a `web/`.

### Pruebas de concepto (media jornada cada una)
- **PoC probador**: pantalla Flutter con cámara frontal, ML Kit detectando pose, un PNG cualquiera siguiendo los hombros. Resolver el espejado de la cámara frontal y la rotación del `InputImage`.
- **PoC try-on generativo**: script Python que llame a Vertex AI con una foto y un flat-lay. Confirma que la cuenta funciona.
- **PoC voz**: `speech_to_text` en Flutter transcribiendo una frase en español, y una llamada a Groq que devuelva JSON.

### Preparación de datos
- Descargar el Fashion Product Images Dataset (versión alta resolución).
- Filtrar por `gender = Men` + `subCategory = Topwear` → seleccionar 30 productos.
- **Agregar manualmente la columna `material`** a los 30 (el dataset no la trae y la búsqueda por voz la necesita).
- Apartar 8-10 productos con foto de prenda sola (sin modelo) para assets de probador.
- Fotografiar 4-5 prendas físicas propias para la demostración.

### Criterio de cierre
Todas las credenciales funcionando y las tres PoC respondiendo. Si la PoC generativa falla, el modo realista pasa a "deseable" en el documento.

### Riesgo principal
No conseguir tarjeta internacional. Plan B: modelo abierto en Hugging Face para el try-on y Railway pagado por otro medio.

---

## ETAPA 1 — Cimientos y esqueleto caminante
**01/09 → 05/09 (5 días) · ENTREGA 1: sábado 05/09 23:59**

### Objetivo
Un flujo completo funcionando de punta a punta en la nube. Todo lo demás es repetir este patrón.

### Backend
1. Estructura de paquetes:
   ```
   backend/app/
     core/          config, database, security, exceptions, crud_base, deps
     seguridad/     models schemas router service repository
     organizacion/
     ...
     main.py
   ```
2. `core/config.py` con Pydantic Settings leyendo variables de entorno.
3. `core/database.py`: SQLAlchemy + sesión por request.
4. `core/security.py`: hash de contraseñas con bcrypt, generación y validación de JWT, dependencia `get_current_user` y `require_permission(codigo)`.
5. `core/crud_base.py`: clase genérica con `listar`, `obtener`, `crear`, `actualizar`, `desactivar`. De aquí heredan los 12 paquetes restantes. **Esta clase es la que te ahorra la mitad del trabajo repetitivo.**
6. Alembic inicializado. Primera migración con los paquetes `seguridad` y `organizacion`.
7. Seeds: roles, permisos, estados, tipos de movimiento, métodos de pago, tallas, materiales.
8. CORS configurado para el dominio de Vercel y para desarrollo local.

**Endpoints de esta etapa**
```
POST   /api/v1/auth/registro          CU-01
POST   /api/v1/auth/login             CU-02
POST   /api/v1/auth/refresh
GET    /api/v1/auth/yo
POST   /api/v1/auth/recuperar         CU-05
CRUD   /api/v1/roles                  CU-03, CU-04
CRUD   /api/v1/usuarios               CU-03
CRUD   /api/v1/ciudades               CU-07
CRUD   /api/v1/sucursales             CU-08
CRUD   /api/v1/sucursales/{id}/horarios   CU-10
CRUD   /api/v1/empleados              CU-09
GET    /api/v1/clientes/perfil        CU-06
```

### Web Angular
- Proyecto creado, PrimeNG instalado, tokens de diseño en `styles.scss`.
- Cliente HTTP generado desde el OpenAPI de FastAPI.
- Interceptor de JWT y de errores.
- Guardas de ruta por rol.
- Pantallas: login, layout con menú lateral, dashboard vacío, CRUD de usuarios, roles, ciudades y sucursales.
- **Componente de tabla genérica** reutilizable (filtro, orden, paginación, acciones). Igual que `crud_base` en el backend: se escribe una vez y sirve para veinte pantallas.

### Móvil Flutter
- Proyecto creado, `go_router`, `dio`, `flutter_riverpod`, tema Material 3 con los mismos tokens.
- Cliente HTTP con interceptor de token y almacenamiento seguro.
- Pantallas: splash, registro, login, home vacío.

### Despliegue
- API en Railway con la migración aplicada.
- Angular en Vercel.
- APK de depuración instalado en un teléfono real conectado contra Railway.

### Documentación (Entrega 1)
- Perfil: introducción, objetivo general, específicos, descripción del problema, alcance.
- Alcance con el reparto de módulos y responsables.
- **Parte I teórica completa**: e-commerce (Amazon, Alibaba, Shopify como usuario; Magento, PrestaShop, WooCommerce como desarrollador), pasarelas (débito, crédito, QR, transferencia, Libélula, PayPal, Stripe), deliverys (Yaigo, Yummy, PedidosYa y su cálculo por zonas, peso, volumen y frecuencia), PUDS, UML.
- Glosario del dominio.
- Modelo de dominio conceptual.
- Actores y catálogo de los 79 casos de uso.
- Especificación detallada de 10-12 casos de uso críticos.
- Diagrama de casos de uso general + por paquete.
- Wireframes (10 pantallas).
- Matriz de trazabilidad RF ↔ CU ↔ módulo.
- Justificación de la elección tecnológica del probador (descarte de SDKs comerciales y AR 3D).

### Criterio de cierre
Login desde el teléfono físico contra la API en Railway con la base de datos en la nube. Si esto funciona el 5, el proyecto es viable.

---

## ETAPA 2 — Catálogo y assets
**06/09 → 08/09 (3 días)**

### Objetivo
El corazón del sistema. Todo lo demás depende del catálogo.

### Backend
1. Migración de los paquetes `catalogo` y `abastecimiento`.
2. Servicio de Cloudinary en `core/storage.py`: subida firmada desde el backend, borrado, generación de URLs transformadas. El `api_secret` nunca sale de aquí.
3. Regla de negocio: al crear un producto, generar automáticamente las variantes del producto cargado (combinatoria talla × color seleccionadas), con SKU autogenerado.
4. Validación de assets del probador: PNG con canal alfa real, mínimo 512px, máximo 3MB, JSON con los tres anclajes obligatorios.
5. Script de carga masiva del dataset de Kaggle (30 productos con sus variantes).

**Endpoints**
```
CRUD   /api/v1/categorias             CU-11
CRUD   /api/v1/tallas                 CU-12
CRUD   /api/v1/colores                CU-13
CRUD   /api/v1/materiales             CU-14
CRUD   /api/v1/temporadas             CU-15
CRUD   /api/v1/colecciones            CU-16
CRUD   /api/v1/productos              CU-17
CRUD   /api/v1/productos/{id}/variantes        CU-18
CRUD   /api/v1/productos/{id}/medidas          CU-19
POST   /api/v1/productos/{id}/imagenes         CU-20
CRUD   /api/v1/proveedores            CU-25
POST   /api/v1/proveedores/{id}/productos      CU-26, CU-27
GET    /api/v1/catalogo               CU-21  (público, paginado)
GET    /api/v1/catalogo/buscar        CU-22  (filtros: categoría, talla,
                                              color, material, temporada,
                                              precio, género, sucursal)
GET    /api/v1/catalogo/{id}          CU-23
CRUD   /api/v1/favoritos              CU-24
POST   /api/v1/probador/assets        CU-48
PUT    /api/v1/probador/assets/{id}/anclajes   CU-48
PUT    /api/v1/probador/assets/{id}/validar    CU-48
```

### Web Angular
- CRUD de categorías, tallas, colores, materiales, temporadas, colecciones, proveedores (todos con el componente de tabla genérica).
- Formulario de producto con generador de variantes y carga de imágenes a Cloudinary.
- Formulario de tabla de medidas por talla.
- **Editor de anclajes**: se muestra el PNG, se hace clic en hombro izquierdo, hombro derecho y cadera, se guardan normalizados 0..1. Cuatro horas de trabajo que evitan calcular coordenadas a mano y es una pantalla lucida para la defensa.
- Plantilla de anclajes por tipo de prenda, precargada.

### Móvil Flutter
- Catálogo con grilla, imágenes desde Cloudinary con `cached_network_image`.
- Filtros por categoría, talla, color, material, temporada y precio.
- Detalle de prenda: galería, selector de talla y color, descripción, precio.
- Favoritos.
- **Registro de eventos de navegación** (`historial_navegacion`) desde el primer día: vistas, búsquedas, favoritos. Sin esto el recomendador no tiene datos en la defensa.

### Criterio de cierre
30 productos cargados con variantes, imágenes en Cloudinary, y 8-10 con assets de probador validados. El catálogo se navega y filtra desde el teléfono.

---

## ETAPA 3 — Inventario y abastecimiento
**09/09 → 10/09 (2 días)**

### Objetivo
El módulo con más reglas de negocio del sistema.

### Backend
1. Migración del paquete `inventario`.
2. **Servicio de movimientos** — el núcleo. Cada movimiento, dentro de una transacción:
   - inserta la fila en `movimiento_inventario` con su `saldo_post`;
   - actualiza `stock.cantidad_fisica`;
   - si el tipo `afecta_costo`, recalcula el costo promedio ponderado:
     ```
     nuevo_promedio = (stock_anterior * costo_anterior + cantidad_ingresada * costo_ingreso)
                      / (stock_anterior + cantidad_ingresada)
     ```
   - guarda `costo_promedio_post` en el movimiento (auditoría).
3. Recepción de mercadería: genera movimientos de tipo `recepcion` con costo unitario. Es la única entrada con costo.
4. Reserva y liberación de stock: mueven `cantidad_reservada`, nunca `cantidad_fisica`.
5. Transferencias entre sucursales: salida en origen, ingreso en destino, con costo del origen.
6. Ajustes por diferencia física.
7. Consulta de alertas: variantes con `cantidad_disponible <= stock_minimo`.

**Endpoints**
```
GET    /api/v1/inventario/consolidado          CU-31
GET    /api/v1/inventario/sucursal/{id}        CU-32
GET    /api/v1/inventario/disponibilidad       CU-30  (público, por variante)
POST   /api/v1/inventario/movimientos          CU-32
GET    /api/v1/inventario/movimientos          (kardex por variante)
PUT    /api/v1/inventario/stock/{id}/limites   CU-35
GET    /api/v1/inventario/alertas              CU-36
GET    /api/v1/inventario/valuacion            CU-37
CRUD   /api/v1/transferencias                  CU-33
POST   /api/v1/inventario/ajustes              CU-34
CRUD   /api/v1/ordenes-compra                  CU-28
POST   /api/v1/recepciones                     CU-29
```

### Web Angular
- Inventario consolidado con filtros por sucursal, producto y estado.
- Kardex por variante (historial de movimientos con saldo y costo).
- Formulario de recepción de mercadería con costos unitarios.
- Configuración de stock mínimo y máximo.
- Panel de alertas de reposición.
- Reporte de valuación por promedio ponderado.
- Transferencias y ajustes.

### Móvil Flutter
- En el detalle de prenda: disponibilidad por sucursal con semáforo (disponible, últimas unidades, agotada, próxima a ingresar).

### Pruebas unitarias (obligatorias aquí)
- `test_promedio_ponderado`: tres recepciones a costos distintos, verificar el promedio resultante.
- `test_disponible_nunca_negativo`.
- `test_reserva_no_afecta_fisico`.

### Criterio de cierre
Una recepción de mercadería actualiza stock y costo promedio correctamente, y el kardex muestra la trazabilidad completa.

---

## ETAPA 4 — Reservas y vestidor virtual
**11/09 → 13/09 (3 días) · ENTREGA 2: domingo 13/09 23:59**

### Objetivo
Las dos funcionalidades más distintivas del proyecto.

### Backend — Reservas
1. Migración del paquete `reservas`.
2. Crear reserva: valida disponibilidad de cada variante en la sucursal, valida que la hora esté dentro del horario de la sucursal, incrementa `cantidad_reservada`, fija `fecha_expiracion`, genera notificación a los empleados de esa sucursal.
3. Transiciones de estado: pendiente → preparada → en_prueba → completada, con registro en `reserva_historial`.
4. **Liberación tras la prueba (CU-46)**: el encargado marca qué prendas seleccionó el cliente. Las no seleccionadas devuelven su stock reservado a disponible.
5. **Expiración automática (CU-47)**: tarea programada que libera reservas vencidas. En Railway se resuelve con un endpoint protegido llamado por un cron.

**Endpoints**
```
POST   /api/v1/reservas                        CU-39
GET    /api/v1/reservas/mis-reservas           CU-40
GET    /api/v1/reservas/{id}                   CU-40
DELETE /api/v1/reservas/{id}                   CU-41
GET    /api/v1/reservas/sucursal/{id}          CU-43
PUT    /api/v1/reservas/{id}/preparar          CU-44
PUT    /api/v1/reservas/{id}/confirmar-llegada CU-45
PUT    /api/v1/reservas/{id}/seleccion         CU-46
POST   /api/v1/tareas/expirar-reservas         CU-47
GET    /api/v1/notificaciones                  CU-42
```

### Backend — Probador
```
GET    /api/v1/probador/variante/{id}/assets   CU-49
POST   /api/v1/probador/generar                CU-50  (asíncrono)
GET    /api/v1/probador/generar/{id}           CU-50
POST   /api/v1/probador/sesion                 (métrica de uso)
POST   /api/v1/probador/talla                  CU-52
```

Reglas del modo generativo: buscar en caché por `(hash_foto, variante_id)` antes de llamar a Vertex; límite de 3 generaciones por cliente por día; una sola imagen por petición; estado `en_proceso` → `completado`/`fallido`.

### Móvil Flutter — Modo espejo
1. `CameraController` con cámara frontal + `PoseDetector` en modo `stream`.
2. Descarga del `overlay.png` y su JSON de anclajes; caché local.
3. `CustomPainter` que en cada frame:
   - descarta si `likelihood` de los hombros < 0.6;
   - calcula ancho, ángulo y centro entre hombros;
   - escala = (ancho detectado / ancho del asset) × `factor_ancho`;
   - aplica `translate` → `rotate` → `scale` → traslación negativa del punto medio de los anclajes.
4. Corrección del espejado de la cámara frontal y de la rotación del sensor.
5. Botón de captura y galería de pruebas.

### Móvil Flutter — Modo realista
- Selector de foto (cámara o galería) con **checkbox de consentimiento explícito** antes de capturar.
- Envío al backend, indicador de progreso, consulta por polling.
- Resultado con opción de guardar o compartir.

### Móvil — Reservas
- Selección múltiple de prendas, elección de sucursal, fecha y franja horaria.
- Mis reservas con estado y opción de cancelar.

### Web Angular
- Bandeja de reservas de la sucursal con filtro por fecha y estado.
- Checklist de preparación de prendas.
- Confirmación de llegada del cliente.
- Registro de selección tras la prueba.

### Documentación (Entrega 2)
- Clases de análisis (frontera, control, entidad) de los casos de uso críticos.
- Diagramas de comunicación.
- Paquetes de análisis y de diseño.
- Diagrama de clases de diseño completo.
- **Modelo físico de datos** con tipos, llaves e índices.
- Diagramas de secuencia: reservar, probar prenda, comprar digital, vender en caja, recibir mercadería.
- Diagramas de estados: reserva, venta, pago, prenda.
- Diagrama de actividades del proceso completo de negocio.
- Diagrama de componentes y de despliegue.
- Diseño de la API REST y de la arquitectura de seguridad.

### Criterio de cierre
Una reserva creada desde el móvil aparece en la web de la sucursal, se prepara, se confirma y libera correctamente lo no seleccionado. El modo espejo funciona con al menos 5 prendas.

### Riesgo principal
El tracking de pose inestable. Mitigación: umbral de `likelihood`, suavizado exponencial de las coordenadas entre frames, y mensaje en pantalla pidiendo al usuario alejarse o mejorar la iluminación.

---

## ETAPA 5 — Ventas, pagos y entregas
**14/09 → 17/09 (4 días)**

### Objetivo
Cerrar el ciclo comercial completo en sus dos canales.

### Backend — Ventas
1. Migración de los paquetes `ventas`, `pagos` y `entregas`.
2. Carrito persistente por cliente.
3. **Venta como transacción atómica**: crea venta y detalle, congela `costo_unitario` desde el costo promedio actual, genera movimientos de inventario de tipo `venta`, registra el pago, y si viene de una reserva la marca como completada. Todo en un solo commit o nada.
4. Aplicación de promociones vigentes al carrito.
5. Devoluciones: reingreso de stock y reversión parcial del pago.
6. Cálculo de envío: zona por anillo + recargo por peso según `regla_tarifa_envio`.

**Endpoints**
```
CRUD   /api/v1/carrito                         CU-53
POST   /api/v1/ventas/digital                  CU-54
POST   /api/v1/ventas/presencial               CU-55
GET    /api/v1/ventas/{id}/comprobante         CU-56
GET    /api/v1/ventas/mis-compras              CU-57
GET    /api/v1/ventas/sucursal/{id}            CU-58
POST   /api/v1/devoluciones                    CU-59
CRUD   /api/v1/promociones                     CU-60
POST   /api/v1/carrito/aplicar-promocion       CU-61
POST   /api/v1/pagos/iniciar                   CU-62
POST   /api/v1/pagos/caja                      CU-63
POST   /api/v1/pagos/webhook/{pasarela}        CU-64
GET    /api/v1/pagos/{id}/estado               CU-65
POST   /api/v1/pagos/{id}/anular               CU-66
CRUD   /api/v1/zonas-envio                     CU-67
POST   /api/v1/envios/cotizar                  CU-68
POST   /api/v1/envios                          CU-69
PUT    /api/v1/envios/{id}/estado              CU-70
```

### Backend — Pasarelas
- Adaptador común `PasarelaBase` con implementaciones `Libelula` y `PayPal`. Así el resto del sistema no sabe cuál está usando.
- Registro completo en `transaccion_pasarela` de payload enviado y recibido: es la evidencia de las pruebas de integración.
- Webhook para confirmación asíncrona, con verificación de firma.
- Manejo de idempotencia: un webhook repetido no debe generar dos ventas.

### Web Angular — Punto de caja
- Búsqueda de producto por código de barras o nombre.
- Carrito de caja, selección de método de pago (efectivo, QR, tarjeta, transferencia).
- Cálculo de cambio para efectivo.
- Generación e impresión del comprobante.
- Venta a partir de una reserva atendida.
- Devoluciones y cambios.
- Gestión de promociones y de zonas de envío con tarifas.

### Móvil Flutter
- Carrito con edición de cantidades.
- Checkout: dirección de entrega o retiro en sucursal, cotización de envío en vivo.
- Pago con redirección a la pasarela y retorno a la app.
- Historial de compras con detalle y comprobante.

### Pruebas
- `test_tarifa_envio_por_anillo` con recargo por peso.
- `test_venta_descuenta_stock`.
- `test_webhook_idempotente`.
- Evidencia de una transacción aprobada y una rechazada en sandbox.

### Criterio de cierre
Compra completa desde el móvil con pago en sandbox, stock descontado, comprobante emitido. Venta presencial completa desde la caja.

---

## ETAPA 6 — Inteligencia artificial y reportes
**18/09 → 19/09 (2 días)**

### Objetivo
Las funcionalidades obligatorias de IA y el tablero de decisión.

### Backend — Búsqueda por voz (CU-72)
Flujo: el móvil transcribe con el STT nativo → envía el texto a `/api/v1/ia/voz` → el backend arma un prompt para Groq pidiendo **JSON estricto** con los filtros → se valida con Pydantic → se ejecuta la consulta del catálogo que ya existe → se devuelven los resultados y se registra en `consulta_voz`.

Esquema de salida esperado:
```json
{ "categoria": "blusa", "temporada": "primavera", "material": "algodón",
  "color": "amarillo", "talla": null, "precio_max": null, "sucursal": null }
```
Cualquier campo no mencionado va en `null`. Si el JSON no valida, se cae a búsqueda por texto plano.

### Backend — Recomendador (CU-71)
Híbrido, y así se documenta:
1. Capa de reglas: variantes de la misma categoría y temporada, con stock disponible, excluyendo lo ya comprado.
2. Capa de historial: pondera por vistas, favoritos y usos del probador desde `historial_navegacion`.
3. Capa Groq: ordena y redacta el motivo en lenguaje natural ("porque viste camisas de lino esta semana").
4. Persistencia en `recomendacion` con puntaje y motivo.

### Backend — Reportes
```
GET    /api/v1/reportes/ventas                 CU-76
GET    /api/v1/reportes/inventario             CU-77
GET    /api/v1/reportes/dashboard              CU-78
GET    /api/v1/reportes/reservas               CU-79
POST   /api/v1/ia/reporte-voz                  CU-75
POST   /api/v1/ia/recomendaciones              CU-71
POST   /api/v1/ia/voz                          CU-72
POST   /api/v1/ia/chat                         CU-74
```

Las consultas se apoyan en las vistas `vw_inventario_consolidado` y `vw_ventas_detalle`.

### Web Angular
- Dashboard con indicadores: ventas del período, ticket promedio, productos más vendidos, valor del inventario, reservas por estado, alertas de stock.
- Gráficos con los componentes de PrimeNG.
- Reportes exportables.
- **Widget de Botpress** embebido, conectado por HTTP a los endpoints públicos del catálogo y del inventario.

### Móvil Flutter
- Botón de micrófono en el catálogo con retroalimentación visual de escucha y transcripción en pantalla.
- Carrusel de recomendaciones en el home y en el detalle de prenda.
- **Asistente** (chatbot de Botpress) en la app: ícono de burbuja en la barra del catálogo, entre la campana y el muñeco del probador. Es el mismo bot que la web, cargado en un WebView (`mobile/lib/features/asistente/`). Sin backend ni llaves nuevas. Decisión del 20/09, posterior al plan original (que lo dejaba solo en la web); ver la nota en P6.4 de `prompts_claude_code_fashionstore.md`.

### Criterio de cierre
Decir "quiero una camisa de algodón azul de primavera" filtra el catálogo correctamente. El dashboard muestra datos reales.

---

## ETAPA 7 — Estabilización y entrega final
**20/09 (1 día) · ENTREGA FINAL: domingo 20/09 23:59**

### Tareas
1. Recorrido completo de los 34 casos de uso del MVP, anotando fallas.
2. Corrección de errores bloqueantes únicamente. Nada de funcionalidades nuevas.
3. Revisión de seguridad: ningún endpoint sin autenticación salvo los públicos, sin secretos en el repositorio, contraseñas hasheadas, HTTPS en todo.
4. Carga de datos de demostración realistas: 30 productos, 3 sucursales en 2 ciudades, 10 clientes, ventas históricas de las últimas semanas, reservas en distintos estados, movimientos de inventario con costos variados.
5. Verificación de rendimiento del catálogo (RNF02) con las transformaciones de Cloudinary.

### Documentación (Entrega final)
- Estructura del código y estándares aplicados.
- Manual de instalación y despliegue.
- Manual de usuario por rol.
- Evidencias: capturas de todas las pantallas funcionando.
- Plan de pruebas y casos de prueba derivados de los casos de uso.
- Resultados de las pruebas unitarias y de integración.
- Matriz de trazabilidad final: RF → CU → módulo → prueba → estado.
- Conclusiones y trabajo futuro.

---

## ETAPA 8 — Congelamiento y defensa
**21/09 → 22/09 · DEFENSA: martes 22/09**

**Regla absoluta: el código se congela el 20 a medianoche.** No se toca nada.

### Preparación
1. Guion de demostración de 15 minutos con orden fijo:
   catálogo → búsqueda por voz → probador modo espejo → probador modo realista → reserva → atención en sucursal → venta en caja → compra digital con pasarela → inventario y kardex → dashboard.
2. **Dos ensayos completos cronometrados**, con el teléfono físico y la prenda real en la mano.
3. Plan de contingencia: capturas y video de respaldo de cada funcionalidad crítica, por si falla internet o una API externa.
4. Preguntas previsibles ensayadas:
   - ¿Por qué no usaron un SDK comercial de AR?
   - ¿Cómo se calcula el promedio ponderado? (mostrar el kardex)
   - ¿Qué pasa si el cliente no compra las prendas reservadas?
   - ¿Por qué monolito y no microservicios?
   - ¿Cómo se integra el probador con el catálogo dinámico?
   - ¿Qué pasa si la pasarela no responde?
5. Verificar que la API en Railway esté encendida y con crédito, y que el APK instalado sea el de la versión final.

---

## Cobertura de requisitos

| RF | Descripción | Etapa |
|---|---|---|
| RF01 | Registrar clientes | 1 |
| RF02 | Usuarios y roles | 1 |
| RF03 | Ciudades y sucursales | 1 |
| RF04 | Productos de ropa | 2 |
| RF05 | Tallas, colores, categorías, temporadas | 2 |
| RF06 | Proveedores | 2 |
| RF07 | Catálogo web y móvil | 2 |
| RF08 | Disponibilidad por sucursal | 3 |
| RF09 | Selección múltiple para reserva | 4 |
| RF10 | Registrar y gestionar reservas | 4 |
| RF11 | Notificar reserva a sucursal | 4 |
| RF12 | Consultar estado de reserva | 4 |
| RF13 | Vestidor virtual en móvil | 4 |
| RF14 | Carrito | 5 |
| RF15 | Compra web | 5 |
| RF16 | Compra móvil | 5 |
| RF17 | Ventas presenciales | 5 |
| RF18 | Pago en caja | 5 |
| RF19 | Pasarela de pago | 5 |
| RF20 | Inventario tras venta | 3, 5 |
| RF21 | Existencias por sucursal | 3 |
| RF22 | Movimientos de inventario | 3 |
| RF23 | Temporadas y colecciones | 2 |
| RF24 | Reportes de ventas e inventario | 6 |
| RF25 | Funcionalidad de IA | 6 |

Requisitos del complemento en audio: QR, tarjeta y transferencia en caja (etapa 5), Libélula y PayPal (etapa 5), búsqueda por voz obligatoria (etapa 6), chatbot opcional en web (etapa 6), delivery por anillos (etapa 5), stock mínimo y máximo (etapa 3), promedio ponderado (etapa 3), categoría acotada y responsables por módulo (etapa 1).

Requisitos no funcionales: RNF01 y RNF09 en etapas 1 y 5, RNF02 en etapas 2 y 7, RNF03 y RNF04 en la arquitectura desde la etapa 1, RNF05 en el diseño de cada pantalla, RNF06 en la estructura de paquetes, RNF07 y RNF08 por decisión de stack.

---

## Reglas de supervivencia

1. **Rebanadas verticales.** Módulo completo antes de pasar al siguiente.
2. **Desplegar desde el día uno.** Cada etapa termina con algo funcionando en la nube.
3. **Alembic siempre.** Ningún cambio de esquema a mano.
4. **Los paquetes se hablan por servicios**, nunca por consultas directas a tablas ajenas.
5. **Congelar el 20.** Un sistema estable con menos funciones gana a uno completo que se cae.

### Orden de recorte si el tiempo aprieta
Se elimina de abajo hacia arriba: reportes por voz → chatbot → devoluciones → transferencias y ajustes → recomendación de talla → promociones → try-on generativo → delivery.

**Nunca se recorta**: catálogo, inventario, reservas, probador modo espejo, una forma de pago, búsqueda por voz.
