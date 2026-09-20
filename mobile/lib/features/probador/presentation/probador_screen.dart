import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:camera/camera.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gal/gal.dart';
import 'package:google_mlkit_pose_detection/google_mlkit_pose_detection.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:share_plus/share_plus.dart';

import '../../../core/theme/app_theme.dart';
import '../../tracking/models/evento.dart';
import '../../tracking/state/tracking_service.dart';
import '../models/activo_probador.dart';
import '../state/probador_providers.dart';

/// Pantalla del probador: alterna entre modo espejo (cámara en vivo +
/// overlay, P4.4/P4.5) y modo realista (foto + generación por IA, P4.6).
/// Cada modo se dispone/reinicia solo con el cambio de pestaña: al no ser
/// `IndexedStack`, Flutter destruye por completo el widget que no está
/// activo (y con él, la cámara o el polling que tuviera en curso).
class ProbadorScreen extends StatefulWidget {
  const ProbadorScreen({this.varianteInicial, super.key});

  /// La prenda (variante) que el cliente eligió en el detalle o en el carrito: el probador abre con ella puesta.
  /// Sin ella (ícono del catálogo) abre con la primera de la lista.
  final int? varianteInicial;

  @override
  State<ProbadorScreen> createState() => _ProbadorScreenState();
}

enum _ModoProbador { espejo, realista }

class _ProbadorScreenState extends State<ProbadorScreen> {
  var _modo = _ModoProbador.espejo;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: const Text('Probador'),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: SegmentedButton<_ModoProbador>(
              style: SegmentedButton.styleFrom(
                backgroundColor: Colors.transparent,
                foregroundColor: Colors.white70,
                selectedForegroundColor: Colors.white,
                selectedBackgroundColor: AppColors.acento,
                side: const BorderSide(color: Colors.white38),
              ),
              segments: const [
                ButtonSegment(
                  value: _ModoProbador.espejo,
                  label: Text('Espejo'),
                  icon: Icon(Icons.accessibility_new_outlined),
                ),
                ButtonSegment(
                  value: _ModoProbador.realista,
                  label: Text('Realista'),
                  icon: Icon(Icons.auto_awesome_outlined),
                ),
              ],
              selected: {_modo},
              onSelectionChanged: (seleccion) => setState(() => _modo = seleccion.first),
            ),
          ),
        ),
      ),
      // SafeArea: desde que el edge-to-edge es obligatorio (Android 15+),
      // la barra de navegación del sistema se dibuja ENCIMA del contenido
      // en vez de reservarle espacio -- sin esto, cualquier control pegado
      // al borde inferior (el botón de captura, guardar/compartir del
      // resultado) queda tapado detrás de la barra y parece que no existe.
      body: SafeArea(
        child: _modo == _ModoProbador.espejo
            ? _ModoEspejo(varianteInicial: widget.varianteInicial)
            : _ModoRealista(
                onUsarModoEspejo: () => setState(() => _modo = _ModoProbador.espejo),
                varianteInicial: widget.varianteInicial,
              ),
      ),
    );
  }
}

class _ModoEspejo extends ConsumerStatefulWidget {
  const _ModoEspejo({this.varianteInicial});

  final int? varianteInicial;

  @override
  ConsumerState<_ModoEspejo> createState() => _ModoEspejoState();
}

enum _EstadoPermiso { pidiendo, concedido, denegado, denegadoPermanente }

class _ModoEspejoState extends ConsumerState<_ModoEspejo> with WidgetsBindingObserver {
  final _detectorPose = PoseDetector(options: PoseDetectorOptions(mode: PoseDetectionMode.stream));
  final _repaintKey = GlobalKey();

  static const _umbralLikelihood = 0.6;
  static const _factorSuavizado = 0.3;

  CameraController? _controller;
  CameraDescription? _camaraFrontal;
  _EstadoPermiso _estadoPermiso = _EstadoPermiso.pidiendo;
  bool _procesandoFrame = false;
  String? _errorCamara;

  Size? _tamanioImagenCamara;
  InputImageRotation _rotacion = InputImageRotation.rotation0deg;
  bool _poseValida = false;
  // Coordenadas suavizadas de los hombros, en el sistema de coordenadas
  // del buffer de la cámara (antes de trasladarX/Y): la suavización va acá
  // porque ese sistema no cambia de tamaño entre frames, a diferencia del
  // canvas donde se pinta.
  Offset? _hombroIzqSuavizado;
  Offset? _hombroDerSuavizado;

  PrendaProbador? _prendaActual;
  ui.Image? _imagenPrenda;
  bool _cargandoImagen = false;
  bool _sesionRegistrada = false;
  bool _capturando = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _pedirPermisoYArrancar();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState estado) {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) return;
    if (estado == AppLifecycleState.inactive || estado == AppLifecycleState.paused) {
      controller.dispose();
      _controller = null;
    } else if (estado == AppLifecycleState.resumed) {
      _iniciarCamara();
    }
  }

  Future<void> _pedirPermisoYArrancar() async {
    final resultado = await Permission.camera.request();
    if (!mounted) return;
    if (resultado.isGranted) {
      setState(() => _estadoPermiso = _EstadoPermiso.concedido);
      await _iniciarCamara();
    } else if (resultado.isPermanentlyDenied) {
      setState(() => _estadoPermiso = _EstadoPermiso.denegadoPermanente);
    } else {
      setState(() => _estadoPermiso = _EstadoPermiso.denegado);
    }
  }

  Future<void> _iniciarCamara() async {
    if (mounted) setState(() => _errorCamara = null);
    try {
      final camaras = await availableCameras();
      if (camaras.isEmpty) {
        if (!mounted) return;
        setState(() => _errorCamara = 'No se encontró ninguna cámara disponible en este equipo.');
        return;
      }
      final camaraFrontal = camaras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => camaras.first,
      );
      _camaraFrontal = camaraFrontal;

      final controller = CameraController(
        camaraFrontal,
        ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: Platform.isAndroid ? ImageFormatGroup.nv21 : ImageFormatGroup.bgra8888,
      );
      _controller = controller;
      await controller.initialize();
      if (!mounted) return;
      await controller.startImageStream(_procesarFrame);
      setState(() {});
    } catch (_) {
      // La cámara puede estar ocupada por otra app, no responder, o el
      // permiso puede haberse revocado justo en este momento -- sin este
      // catch, el Future queda sin manejar y la pantalla se queda
      // congelada en el spinner de carga para siempre (M-2 de la
      // auditoría).
      _controller = null;
      if (!mounted) return;
      setState(
        () => _errorCamara = 'No se pudo iniciar la cámara. Cerrá otras apps que puedan estar usándola e intentá de nuevo.',
      );
    }
  }

  void _procesarFrame(CameraImage imagen) {
    if (_procesandoFrame) return;
    _procesandoFrame = true;
    _detectar(imagen).whenComplete(() => _procesandoFrame = false);
  }

  Future<void> _detectar(CameraImage imagen) async {
    final inputImage = _construirInputImage(imagen);
    if (inputImage == null || inputImage.metadata == null) return;
    final poses = await _detectorPose.processImage(inputImage);
    if (!mounted) return;

    final pose = poses.isNotEmpty ? poses.first : null;
    final hombroIzq = pose?.landmarks[PoseLandmarkType.leftShoulder];
    final hombroDer = pose?.landmarks[PoseLandmarkType.rightShoulder];
    final valido =
        hombroIzq != null &&
        hombroDer != null &&
        hombroIzq.likelihood >= _umbralLikelihood &&
        hombroDer.likelihood >= _umbralLikelihood;

    setState(() {
      _tamanioImagenCamara = inputImage.metadata!.size;
      _rotacion = inputImage.metadata!.rotation;
      _poseValida = valido;
      if (valido) {
        _hombroIzqSuavizado = _suavizar(_hombroIzqSuavizado, Offset(hombroIzq.x, hombroIzq.y));
        _hombroDerSuavizado = _suavizar(_hombroDerSuavizado, Offset(hombroDer.x, hombroDer.y));
      } else {
        // Se reinicia (no se congela) para que, cuando vuelva a detectarse
        // una pose válida, no arranque suavizando desde una posición vieja.
        _hombroIzqSuavizado = null;
        _hombroDerSuavizado = null;
      }
    });
  }

  Offset _suavizar(Offset? anterior, Offset nuevo) {
    if (anterior == null) return nuevo;
    return Offset.lerp(anterior, nuevo, _factorSuavizado)!;
  }

  // Rotación real del sensor según orientación del dispositivo: la cámara
  // frontal en Android suma la compensación (en vez de restarla como la
  // trasera) porque su sensor está montado espejado respecto de la trasera.
  static const _orientaciones = {
    DeviceOrientation.portraitUp: 0,
    DeviceOrientation.landscapeLeft: 90,
    DeviceOrientation.portraitDown: 180,
    DeviceOrientation.landscapeRight: 270,
  };

  InputImage? _construirInputImage(CameraImage imagen) {
    final controller = _controller;
    final camara = _camaraFrontal;
    if (controller == null || camara == null) return null;

    InputImageRotation? rotacion;
    if (Platform.isIOS) {
      rotacion = InputImageRotationValue.fromRawValue(camara.sensorOrientation);
    } else if (Platform.isAndroid) {
      var compensacion = _orientaciones[controller.value.deviceOrientation];
      if (compensacion == null) return null;
      if (camara.lensDirection == CameraLensDirection.front) {
        compensacion = (camara.sensorOrientation + compensacion) % 360;
      } else {
        compensacion = (camara.sensorOrientation - compensacion + 360) % 360;
      }
      rotacion = InputImageRotationValue.fromRawValue(compensacion);
    }
    if (rotacion == null) return null;

    final formato = InputImageFormatValue.fromRawValue(imagen.format.raw);
    if (formato == null ||
        (Platform.isAndroid && formato != InputImageFormat.nv21) ||
        (Platform.isIOS && formato != InputImageFormat.bgra8888)) {
      return null;
    }

    // Con imageFormatGroup nv21/bgra8888 la cámara ya entrega un solo plano.
    if (imagen.planes.length != 1) return null;
    final plano = imagen.planes.first;

    return InputImage.fromBytes(
      bytes: plano.bytes,
      metadata: InputImageMetadata(
        size: Size(imagen.width.toDouble(), imagen.height.toDouble()),
        rotation: rotacion,
        format: formato,
        bytesPerRow: plano.bytesPerRow,
      ),
    );
  }

  Future<void> _elegirPrenda(PrendaProbador prenda, {bool esInicial = false}) async {
    if (_cargandoImagen) return;
    setState(() => _cargandoImagen = true);
    try {
      final bytes = await ref.read(probadorRepositoryProvider).obtenerImagenOverlay(prenda.assets.overlay);
      final codec = await ui.instantiateImageCodec(bytes);
      final frame = await codec.getNextFrame();
      if (!mounted) return;
      setState(() {
        _prendaActual = prenda;
        _imagenPrenda = frame.image;
        _cargandoImagen = false;
      });
      if (esInicial && !_sesionRegistrada) {
        _sesionRegistrada = true;
        unawaited(ref.read(probadorRepositoryProvider).registrarSesion(varianteId: prenda.varianteId, modo: 'espejo'));
        ref.read(trackingServiceProvider).track(tipo: TipoEvento.probador, varianteId: prenda.varianteId);
      }
    } catch (e, stack) {
      debugPrint('Error cargando overlay de la prenda ${prenda.varianteId}: $e\n$stack');
      if (!mounted) return;
      setState(() => _cargandoImagen = false);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No se pudo cargar la prenda.')));
    }
  }

  Future<void> _capturar() async {
    if (_capturando) return;
    setState(() => _capturando = true);
    try {
      final boundary = _repaintKey.currentContext?.findRenderObject() as RenderRepaintBoundary?;
      if (boundary == null) return;
      final imagen = await boundary.toImage(pixelRatio: 2.0);
      final bytes = await imagen.toByteData(format: ui.ImageByteFormat.png);
      if (bytes == null) return;

      final tienePermiso = await Gal.requestAccess();
      if (!tienePermiso) {
        if (!mounted) return;
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Sin permiso para guardar en la galería.')));
        return;
      }
      await Gal.putImageBytes(bytes.buffer.asUint8List());
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Foto guardada en la galería.')));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No se pudo guardar la foto.')));
    } finally {
      if (mounted) setState(() => _capturando = false);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller?.dispose();
    _detectorPose.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<AsyncValue<List<PrendaProbador>>>(prendasParaProbadorProvider(widget.varianteInicial), (previous, next) {
      next.whenData((prendas) {
        if (prendas.isNotEmpty && _prendaActual == null) {
          _elegirPrenda(prendas.first, esInicial: true);
        }
      });
    });
    final asyncPrendas = ref.watch(prendasParaProbadorProvider(widget.varianteInicial));
    return _cuerpo(asyncPrendas);
  }

  Widget _cuerpo(AsyncValue<List<PrendaProbador>> asyncPrendas) {
    switch (_estadoPermiso) {
      case _EstadoPermiso.pidiendo:
        return const Center(child: CircularProgressIndicator(color: Colors.white));
      case _EstadoPermiso.denegado:
        return _mensajePermiso(
          'Se necesita acceso a la cámara para el probador virtual.',
          textoBoton: 'Reintentar',
          onPressed: _pedirPermisoYArrancar,
        );
      case _EstadoPermiso.denegadoPermanente:
        return _mensajePermiso(
          'El acceso a la cámara está bloqueado. Habilitalo desde los ajustes del sistema.',
          textoBoton: 'Abrir ajustes',
          onPressed: openAppSettings,
        );
      case _EstadoPermiso.concedido:
        final errorCamara = _errorCamara;
        if (errorCamara != null) {
          return _mensajePermiso(errorCamara, textoBoton: 'Reintentar', onPressed: _iniciarCamara);
        }
        final controller = _controller;
        if (controller == null || !controller.value.isInitialized) {
          return const Center(child: CircularProgressIndicator(color: Colors.white));
        }
        return Stack(
          fit: StackFit.expand,
          children: [
            // Todo lo que tiene que quedar en la foto capturada (cámara +
            // prenda) va dentro de este RepaintBoundary; los controles de UI
            // (mensaje, selector, botón) van afuera, como hermanos en el Stack.
            RepaintBoundary(
              key: _repaintKey,
              child: Center(
                child: CameraPreview(
                  controller,
                  child: CustomPaint(
                    painter: _OverlayPainter(
                      imagenPrenda: _imagenPrenda,
                      activo: _prendaActual?.assets.overlay,
                      hombroIzqImg: _poseValida ? _hombroIzqSuavizado : null,
                      hombroDerImg: _poseValida ? _hombroDerSuavizado : null,
                      tamanioImagen: _tamanioImagenCamara,
                      rotacion: _rotacion,
                      direccionLente: _camaraFrontal?.lensDirection ?? CameraLensDirection.front,
                    ),
                  ),
                ),
              ),
            ),
            if (!_poseValida) _mensajeAcercate(),
            asyncPrendas.when(
              data: (prendas) => prendas.isEmpty ? _mensajeSinPrendas() : _selectorPrendas(prendas),
              loading: () => const SizedBox.shrink(),
              error: (error, stack) => const SizedBox.shrink(),
            ),
            _botonCaptura(),
          ],
        );
    }
  }

  Widget _mensajePermiso(String mensaje, {required String textoBoton, required VoidCallback onPressed}) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.no_photography_outlined, color: Colors.white54, size: 48),
            const SizedBox(height: AppSpacing.md),
            Text(mensaje, style: const TextStyle(color: Colors.white), textAlign: TextAlign.center),
            const SizedBox(height: AppSpacing.md),
            ElevatedButton(onPressed: onPressed, child: Text(textoBoton)),
          ],
        ),
      ),
    );
  }

  Widget _mensajeAcercate() {
    return Positioned(
      top: AppSpacing.xl,
      left: AppSpacing.md,
      right: AppSpacing.md,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.sm),
        decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(AppRadius.base)),
        child: const Text('Acércate a la cámara', textAlign: TextAlign.center, style: TextStyle(color: Colors.white)),
      ),
    );
  }

  Widget _mensajeSinPrendas() {
    return Positioned(
      left: AppSpacing.md,
      right: AppSpacing.md,
      bottom: AppSpacing.xxl + 64,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.sm),
        decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(AppRadius.base)),
        child: const Text(
          'Todavía no hay prendas listas para probar.',
          textAlign: TextAlign.center,
          style: TextStyle(color: Colors.white),
        ),
      ),
    );
  }

  Widget _selectorPrendas(List<PrendaProbador> prendas) {
    return Positioned(
      left: 0,
      right: 0,
      bottom: AppSpacing.xxl + 64,
      child: SizedBox(
        height: 72,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
          itemCount: prendas.length,
          separatorBuilder: (context, index) => const SizedBox(width: AppSpacing.sm),
          itemBuilder: (context, index) {
            final prenda = prendas[index];
            final seleccionada = prenda.varianteId == _prendaActual?.varianteId;
            return GestureDetector(
              onTap: () => _elegirPrenda(prenda),
              child: Container(
                width: 64,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppRadius.base),
                  border: Border.all(
                    color: seleccionada ? AppColors.exito : Colors.white54,
                    width: seleccionada ? 3 : 1,
                  ),
                ),
                clipBehavior: Clip.antiAlias,
                child: CachedNetworkImage(
                  imageUrl: prenda.assets.overlay.url,
                  fit: BoxFit.cover,
                  placeholder: (context, url) => Container(color: Colors.white24),
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _botonCaptura() {
    return Positioned(
      left: 0,
      right: 0,
      bottom: AppSpacing.xl,
      child: Center(
        child: FloatingActionButton(
          backgroundColor: AppColors.acento,
          onPressed: _capturar,
          child: _capturando
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2),
                )
              : const Icon(Icons.camera_alt, color: Colors.white),
        ),
      ),
    );
  }
}

enum _EstadoGeneracion { ninguna, enviando, enProceso, completado, fallido }

/// Modo realista (P4.6): foto (cámara o galería) -> POST /probador/generar
/// -> polling a GET /probador/generar/{id} cada 2s -> resultado a pantalla
/// completa. Nunca cuelga la app: cualquier falla de red, tanto al subir
/// como durante el polling, termina en un estado de error explícito con
/// un mensaje y la sugerencia de usar el modo espejo (ver "Revisar" de la
/// consigna: desconectar internet a propósito tiene que degradar con
/// elegancia, no colgarse).
class _ModoRealista extends ConsumerStatefulWidget {
  const _ModoRealista({required this.onUsarModoEspejo, this.varianteInicial});

  final VoidCallback onUsarModoEspejo;
  final int? varianteInicial;

  @override
  ConsumerState<_ModoRealista> createState() => _ModoRealistaState();
}

class _ModoRealistaState extends ConsumerState<_ModoRealista> {
  static const _intervaloPolling = Duration(seconds: 2);

  bool _consentimiento = false;
  PrendaProbador? _prenda;
  Uint8List? _fotoBytes;

  var _estado = _EstadoGeneracion.ninguna;
  int? _generacionId;
  String? _urlResultado;
  String? _mensajeError;

  Timer? _timerPolling;
  int _intentosFallidosSeguidos = 0;
  DateTime? _inicioPolling;

  bool get _puedeCapturar => _consentimiento && _prenda != null;
  bool get _puedeGenerar => _puedeCapturar && _fotoBytes != null && _estado == _EstadoGeneracion.ninguna;

  @override
  void initState() {
    super.initState();
    // Con una prenda inicial (elegida en el detalle o el carrito) el modo realista también empieza con ella, una
    // sola vez. Sin ella sigue como siempre: el cliente elige la prenda en el selector.
    final inicial = widget.varianteInicial;
    if (inicial != null) {
      ref.listenManual(prendasParaProbadorProvider(inicial), (previous, next) {
        next.whenData((prendas) {
          if (mounted && _prenda == null && prendas.isNotEmpty) setState(() => _prenda = prendas.first);
        });
      }, fireImmediately: true);
    }
  }

  @override
  void dispose() {
    _timerPolling?.cancel();
    super.dispose();
  }

  Future<void> _elegirFoto(ImageSource origen) async {
    try {
      final xfile = await ImagePicker().pickImage(source: origen, imageQuality: 85, maxWidth: 1600);
      if (xfile == null) return;
      final bytes = await xfile.readAsBytes();
      if (!mounted) return;
      setState(() {
        _fotoBytes = bytes;
        _estado = _EstadoGeneracion.ninguna;
        _urlResultado = null;
        _mensajeError = null;
      });
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No se pudo obtener la foto.')));
    }
  }

  Future<void> _generar() async {
    final prenda = _prenda;
    final foto = _fotoBytes;
    if (prenda == null || foto == null) return;

    setState(() {
      _estado = _EstadoGeneracion.enviando;
      _mensajeError = null;
    });

    try {
      final repo = ref.read(probadorRepositoryProvider);
      final resultado = await repo.iniciarGeneracion(
        varianteId: prenda.varianteId,
        fotoBytes: foto,
        nombreArchivo: 'foto.jpg',
        contentType: DioMediaType('image', 'jpeg'),
      );
      if (!mounted) return;

      if (resultado.completado) {
        _terminarConExito(resultado.urlResultado);
        return;
      }
      if (resultado.fallido) {
        _terminarConError(resultado.mensajeError ?? 'No se pudo generar la imagen.');
        return;
      }

      setState(() => _estado = _EstadoGeneracion.enProceso);
      _generacionId = resultado.id;
      _intentosFallidosSeguidos = 0;
      _inicioPolling = DateTime.now();
      _programarPolling();
    } on DioException catch (e) {
      if (!mounted) return;
      _terminarConError(_mensajeParaError(e));
    } catch (_) {
      if (!mounted) return;
      _terminarConError('No se pudo generar la imagen.');
    }
  }

  void _programarPolling() {
    _timerPolling?.cancel();
    _timerPolling = Timer(_intervaloPolling, _consultarEstado);
  }

  Future<void> _consultarEstado() async {
    final id = _generacionId;
    final inicio = _inicioPolling;
    if (id == null || inicio == null || !mounted) return;

    final transcurrido = DateTime.now().difference(inicio);
    if (debeAbandonarPolling(intentosFallidosSeguidos: _intentosFallidosSeguidos, transcurridoDesdeElInicio: transcurrido)) {
      _terminarConError(
        _intentosFallidosSeguidos > 0
            ? 'Se perdió la conexión. Revisá tu internet e intentá de nuevo.'
            : 'La generación está tardando demasiado. Probá de nuevo más tarde.',
      );
      return;
    }

    try {
      final repo = ref.read(probadorRepositoryProvider);
      final resultado = await repo.consultarGeneracion(id);
      if (!mounted) return;
      _intentosFallidosSeguidos = 0;

      if (resultado.completado) {
        _terminarConExito(resultado.urlResultado);
        return;
      }
      if (resultado.fallido) {
        _terminarConError(resultado.mensajeError ?? 'No se pudo generar la imagen.');
        return;
      }
      _programarPolling();
    } catch (_) {
      // Se reintenta unas cuantas veces (podría ser un corte de red
      // momentáneo): recién después de varios intentos seguidos fallidos,
      // el próximo _consultarEstado la abandona por debeAbandonarPolling.
      // Nunca se queda esperando para siempre (ver "Revisar").
      _intentosFallidosSeguidos++;
      if (!mounted) return;
      _programarPolling();
    }
  }

  void _terminarConExito(String? url) {
    final prenda = _prenda;
    setState(() {
      _estado = _EstadoGeneracion.completado;
      _urlResultado = url;
    });
    if (prenda != null) {
      unawaited(ref.read(probadorRepositoryProvider).registrarSesion(varianteId: prenda.varianteId, modo: 'generativo'));
      ref.read(trackingServiceProvider).track(tipo: TipoEvento.probador, varianteId: prenda.varianteId);
    }
  }

  void _terminarConError(String mensaje) {
    setState(() {
      _estado = _EstadoGeneracion.fallido;
      _mensajeError = mensaje;
    });
  }

  String _mensajeParaError(DioException e) {
    final data = e.response?.data;
    final detalle = data is Map ? data['detail'] as String? : null;
    if (detalle != null && detalle.isNotEmpty) return detalle;
    switch (e.type) {
      case DioExceptionType.connectionError:
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return 'Sin conexión a internet. Probá el modo espejo mientras tanto.';
      default:
        return 'No se pudo generar la imagen. Probá de nuevo más tarde.';
    }
  }

  void _reiniciar() {
    _timerPolling?.cancel();
    setState(() {
      _estado = _EstadoGeneracion.ninguna;
      _fotoBytes = null;
      _urlResultado = null;
      _mensajeError = null;
      _generacionId = null;
    });
  }

  Future<void> _guardar() async {
    final url = _urlResultado;
    if (url == null) return;
    try {
      final bytes = await ref.read(probadorRepositoryProvider).descargarBytes(url);
      final tienePermiso = await Gal.requestAccess();
      if (!tienePermiso) {
        if (!mounted) return;
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Sin permiso para guardar en la galería.')));
        return;
      }
      await Gal.putImageBytes(bytes);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Imagen guardada en la galería.')));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No se pudo guardar la imagen.')));
    }
  }

  Future<void> _compartir() async {
    final url = _urlResultado;
    if (url == null) return;
    try {
      final bytes = await ref.read(probadorRepositoryProvider).descargarBytes(url);
      final dir = await getTemporaryDirectory();
      final archivo = File('${dir.path}/probador_resultado.png');
      await archivo.writeAsBytes(bytes);
      await SharePlus.instance.share(
        ShareParams(files: [XFile(archivo.path)], text: 'Así me queda esta prenda en FashionStore'),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No se pudo compartir la imagen.')));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_estado == _EstadoGeneracion.completado && _urlResultado != null) {
      return _vistaResultado();
    }
    if (_estado == _EstadoGeneracion.fallido) {
      return _vistaError();
    }
    if (_estado == _EstadoGeneracion.enviando || _estado == _EstadoGeneracion.enProceso) {
      return _vistaProgreso();
    }

    final asyncPrendas = ref.watch(prendasParaProbadorProvider(widget.varianteInicial));
    return asyncPrendas.when(
      data: (prendas) => _vistaPreparacion(prendas),
      loading: () => const Center(child: CircularProgressIndicator(color: Colors.white)),
      error: (error, stack) =>
          const Center(child: Text('No se pudo cargar el catálogo.', style: TextStyle(color: Colors.white))),
    );
  }

  Widget _vistaPreparacion(List<PrendaProbador> prendas) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CheckboxListTile(
            value: _consentimiento,
            onChanged: (valor) => setState(() => _consentimiento = valor ?? false),
            controlAffinity: ListTileControlAffinity.leading,
            contentPadding: EdgeInsets.zero,
            activeColor: AppColors.exito,
            checkColor: Colors.white,
            title: const Text('Acepto enviar mi foto', style: TextStyle(color: Colors.white)),
            subtitle: const Text(
              'Tu foto se envía a un servicio externo de generación de imágenes (Vertex AI) '
              'solo para crear el resultado. No se guarda en ningún lado: ni la app ni el '
              'servidor la almacenan.',
              style: TextStyle(color: Colors.white70, fontSize: 12),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          if (prendas.isEmpty)
            const Text('Todavía no hay prendas listas para probar.', style: TextStyle(color: Colors.white70))
          else ...[
            const Text('Elegí una prenda', style: TextStyle(color: Colors.white70, fontSize: 12)),
            const SizedBox(height: AppSpacing.xs),
            _selectorPrendasRealista(prendas),
          ],
          const SizedBox(height: AppSpacing.lg),
          if (_fotoBytes != null) ...[
            ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.base),
              child: Image.memory(_fotoBytes!, height: 240, width: double.infinity, fit: BoxFit.cover),
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.white,
                    side: const BorderSide(color: Colors.white54),
                  ),
                  onPressed: _puedeCapturar ? () => _elegirFoto(ImageSource.camera) : null,
                  icon: const Icon(Icons.camera_alt_outlined),
                  label: const Text('Sacar foto'),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.white,
                    side: const BorderSide(color: Colors.white54),
                  ),
                  onPressed: _puedeCapturar ? () => _elegirFoto(ImageSource.gallery) : null,
                  icon: const Icon(Icons.photo_library_outlined),
                  label: const Text('Galería'),
                ),
              ),
            ],
          ),
          if (!_puedeCapturar) ...[
            const SizedBox(height: AppSpacing.xs),
            const Text(
              'Aceptá el envío de tu foto y elegí una prenda para poder sacar o elegir una foto.',
              style: TextStyle(color: Colors.white38, fontSize: 12),
            ),
          ],
          if (_fotoBytes != null) ...[
            const SizedBox(height: AppSpacing.md),
            ElevatedButton(onPressed: _puedeGenerar ? _generar : null, child: const Text('Generar')),
          ],
        ],
      ),
    );
  }

  Widget _selectorPrendasRealista(List<PrendaProbador> prendas) {
    return SizedBox(
      height: 72,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: prendas.length,
        separatorBuilder: (context, index) => const SizedBox(width: AppSpacing.sm),
        itemBuilder: (context, index) {
          final prenda = prendas[index];
          final seleccionada = prenda.varianteId == _prenda?.varianteId;
          return GestureDetector(
            onTap: () => setState(() => _prenda = prenda),
            child: Container(
              width: 64,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(AppRadius.base),
                border: Border.all(color: seleccionada ? AppColors.exito : Colors.white54, width: seleccionada ? 3 : 1),
              ),
              clipBehavior: Clip.antiAlias,
              child: CachedNetworkImage(
                imageUrl: prenda.assets.overlay.url,
                fit: BoxFit.cover,
                placeholder: (context, url) => Container(color: Colors.white24),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _vistaProgreso() {
    final texto = _estado == _EstadoGeneracion.enviando
        ? 'Enviando tu foto...'
        : 'Generando la imagen... puede tardar unos segundos.';
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(color: Colors.white),
            const SizedBox(height: AppSpacing.md),
            Text(texto, style: const TextStyle(color: Colors.white), textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }

  Widget _vistaError() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, color: Colors.white54, size: 48),
            const SizedBox(height: AppSpacing.md),
            Text(
              _mensajeError ?? 'No se pudo generar la imagen.',
              style: const TextStyle(color: Colors.white),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.md),
            ElevatedButton(onPressed: _reiniciar, child: const Text('Intentar de nuevo')),
            const SizedBox(height: AppSpacing.sm),
            TextButton(
              onPressed: widget.onUsarModoEspejo,
              child: const Text('Usar modo espejo', style: TextStyle(color: Colors.white70)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _vistaResultado() {
    return Stack(
      fit: StackFit.expand,
      children: [
        ColoredBox(
          color: Colors.black,
          child: CachedNetworkImage(
            imageUrl: _urlResultado!,
            fit: BoxFit.contain,
            placeholder: (context, url) => const Center(child: CircularProgressIndicator(color: Colors.white)),
            errorWidget: (context, url, error) =>
                const Center(child: Icon(Icons.broken_image_outlined, color: Colors.white54, size: 48)),
          ),
        ),
        Positioned(
          top: AppSpacing.sm,
          left: AppSpacing.sm,
          child: IconButton(
            icon: const Icon(Icons.close, color: Colors.white),
            tooltip: 'Sacar otra foto',
            onPressed: _reiniciar,
          ),
        ),
        Positioned(
          left: 0,
          right: 0,
          bottom: AppSpacing.xl,
          // Positioned con left/right pero sin top deja la altura sin
          // acotar (0..infinito); un SizedBox con altura fija le da al
          // Row -- y a los ElevatedButton adentro -- una restricción
          // concreta en vez de eso (si no, tira BoxConstraints(unconstrained)).
          child: SizedBox(
            height: 48,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _botonResultado(icon: Icons.download_outlined, label: 'Guardar', onPressed: _guardar),
                const SizedBox(width: AppSpacing.lg),
                _botonResultado(icon: Icons.share_outlined, label: 'Compartir', onPressed: _compartir),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _botonResultado({required IconData icon, required String label, required VoidCallback onPressed}) {
    return ElevatedButton.icon(
      // El tema global (app_theme.dart) fija minimumSize en Size.fromHeight(52)
      // -- ancho infinito -- pensado para botones de una sola columna. Acá
      // van dos uno al lado del otro dentro de un Row sin Expanded, así que
      // ese ancho infinito hay que pisarlo o tira BoxConstraints inválido.
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.acento,
        foregroundColor: Colors.white,
        minimumSize: Size.zero,
      ),
      onPressed: onPressed,
      icon: Icon(icon),
      label: Text(label),
    );
  }
}

class _OverlayPainter extends CustomPainter {
  _OverlayPainter({
    required this.imagenPrenda,
    required this.activo,
    required this.hombroIzqImg,
    required this.hombroDerImg,
    required this.tamanioImagen,
    required this.rotacion,
    required this.direccionLente,
  });

  final ui.Image? imagenPrenda;
  final ActivoProbador? activo;
  final Offset? hombroIzqImg;
  final Offset? hombroDerImg;
  final Size? tamanioImagen;
  final InputImageRotation rotacion;
  final CameraLensDirection direccionLente;

  // Factor de ajuste entre el ancho detectado de hombros y el ancho total
  // del asset (no el ancho entre sus propios anclajes): valor a ojo, se
  // afina mirando cómo queda puesta la prenda con overlays reales.
  static const _factorAncho = 2.6;

  @override
  void paint(Canvas canvas, Size size) {
    final imagen = imagenPrenda;
    final anclajes = activo?.anclajes;
    final anchoAssetPx = activo?.anchoPx;
    final altoAssetPx = activo?.altoPx;
    final izqImg = hombroIzqImg;
    final derImg = hombroDerImg;
    final tamanioImg = tamanioImagen;

    if (imagen == null ||
        anclajes == null ||
        anchoAssetPx == null ||
        altoAssetPx == null ||
        anchoAssetPx <= 0 ||
        altoAssetPx <= 0 ||
        izqImg == null ||
        derImg == null ||
        tamanioImg == null) {
      return;
    }

    final pIzq = Offset(
      trasladarX(izqImg.dx, size, tamanioImg, rotacion, direccionLente),
      trasladarY(izqImg.dy, size, tamanioImg, rotacion, direccionLente),
    );
    final pDer = Offset(
      trasladarX(derImg.dx, size, tamanioImg, rotacion, direccionLente),
      trasladarY(derImg.dy, size, tamanioImg, rotacion, direccionLente),
    );

    final transform = calcularTransformOverlay(
      pIzq: pIzq,
      pDer: pDer,
      anclajes: anclajes,
      anchoAssetPx: anchoAssetPx.toDouble(),
      altoAssetPx: altoAssetPx.toDouble(),
      factorAncho: _factorAncho,
    );
    if (transform == null) return;

    canvas.save();
    canvas.translate(transform.centro.dx, transform.centro.dy);
    canvas.rotate(transform.angulo);
    canvas.scale(transform.escala);
    // El punto medio de los anclajes del asset (no el origen de la imagen)
    // es lo que tiene que caer exactamente en `centro`: sin esta traslación
    // negativa, la prenda gira/escala alrededor de su esquina superior
    // izquierda y termina corrida en vez de centrada en el cuerpo.
    canvas.translate(-transform.anclaMedioPx.dx, -transform.anclaMedioPx.dy);
    canvas.drawImage(imagen, Offset.zero, Paint()..filterQuality = FilterQuality.high);
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _OverlayPainter oldDelegate) {
    return oldDelegate.imagenPrenda != imagenPrenda ||
        oldDelegate.hombroIzqImg != hombroIzqImg ||
        oldDelegate.hombroDerImg != hombroDerImg;
  }
}

/// Los cuatro números que hacen falta para ubicar el overlay: dónde va
/// (`centro`), cuánto rota, cuánto escala y qué punto del asset es el que
/// tiene que terminar exactamente en `centro` (`anclaMedioPx`).
class TransformOverlay {
  const TransformOverlay({required this.centro, required this.angulo, required this.escala, required this.anclaMedioPx});

  final Offset centro;
  final double angulo;
  final double escala;
  final Offset anclaMedioPx;
}

/// El paso 6 del overlay, aislado de `Canvas` para poder testearlo: dados
/// los hombros ya detectados (en coordenadas de canvas) y los anclajes del
/// asset (fracciones 0..1 de su propio tamaño en píxeles), calcula la
/// transformación completa. Devuelve `null` si no hay con qué calcular
/// nada razonable (asset sin tamaño, o los dos hombros en el mismo punto).
TransformOverlay? calcularTransformOverlay({
  required Offset pIzq,
  required Offset pDer,
  required AnclajesProbador anclajes,
  required double anchoAssetPx,
  required double altoAssetPx,
  required double factorAncho,
}) {
  if (anchoAssetPx <= 0 || altoAssetPx <= 0) return null;

  final vector = pDer - pIzq;
  final ancho = vector.distance;
  if (ancho <= 0) return null;
  final angulo = vector.direction;
  final centro = Offset.lerp(pIzq, pDer, 0.5)!;

  final anclaIzqPx = Offset(anclajes.hombroIzq.x * anchoAssetPx, anclajes.hombroIzq.y * altoAssetPx);
  final anclaDerPx = Offset(anclajes.hombroDer.x * anchoAssetPx, anclajes.hombroDer.y * altoAssetPx);
  final anclaMedioPx = Offset.lerp(anclaIzqPx, anclaDerPx, 0.5)!;

  final escala = (ancho / anchoAssetPx) * factorAncho;

  return TransformOverlay(centro: centro, angulo: angulo, escala: escala, anclaMedioPx: anclaMedioPx);
}

// Traduce un punto de las coordenadas del buffer de la cámara (tal cual lo
// ve ML Kit) a coordenadas del canvas donde se dibuja. Para la cámara
// frontal el CameraPreview de Flutter ya renderiza el video espejado (como
// un espejo real), pero el buffer que procesa ML Kit NO está espejado —
// por eso acá se espeja también la coordenada X, para que el punto (y la
// prenda que se ancla en él) caigan tal como se ven en pantalla.
double trasladarX(
  double x,
  Size tamanioCanvas,
  Size tamanioImagen,
  InputImageRotation rotacion,
  CameraLensDirection direccionLente,
) {
  switch (rotacion) {
    case InputImageRotation.rotation90deg:
      return x * tamanioCanvas.width / (Platform.isIOS ? tamanioImagen.width : tamanioImagen.height);
    case InputImageRotation.rotation270deg:
      return tamanioCanvas.width -
          x * tamanioCanvas.width / (Platform.isIOS ? tamanioImagen.width : tamanioImagen.height);
    case InputImageRotation.rotation0deg:
    case InputImageRotation.rotation180deg:
      switch (direccionLente) {
        case CameraLensDirection.back:
          return x * tamanioCanvas.width / tamanioImagen.width;
        default:
          return tamanioCanvas.width - x * tamanioCanvas.width / tamanioImagen.width;
      }
  }
}

double trasladarY(
  double y,
  Size tamanioCanvas,
  Size tamanioImagen,
  InputImageRotation rotacion,
  CameraLensDirection direccionLente,
) {
  switch (rotacion) {
    case InputImageRotation.rotation90deg:
    case InputImageRotation.rotation270deg:
      return y * tamanioCanvas.height / (Platform.isIOS ? tamanioImagen.height : tamanioImagen.width);
    case InputImageRotation.rotation0deg:
    case InputImageRotation.rotation180deg:
      return y * tamanioCanvas.height / tamanioImagen.height;
  }
}

/// Cuándo el polling de una generación tiene que dejar de reintentar y
/// terminar en un error explícito, en vez de seguir esperando para
/// siempre: ya sea porque se acumularon demasiados intentos fallidos
/// seguidos (probable corte de red) o porque pasó demasiado tiempo desde
/// que arrancó, tenga o no errores (el servicio externo se colgó). Ver
/// "Revisar": desconectar internet a propósito no puede colgar la app.
bool debeAbandonarPolling({
  required int intentosFallidosSeguidos,
  required Duration transcurridoDesdeElInicio,
  int maxIntentosFallidosSeguidos = 5,
  Duration timeoutTotal = const Duration(seconds: 90),
}) {
  if (transcurridoDesdeElInicio > timeoutTotal) return true;
  return intentosFallidosSeguidos >= maxIntentosFallidosSeguidos;
}
