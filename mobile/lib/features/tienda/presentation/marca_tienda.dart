import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../models/tienda.dart';

/// El nombre de la plataforma cuando aún no hay una tienda elegida.
const nombrePlataforma = 'FashionStore';

/// La marca de la tienda para la barra superior: su logo si lo tiene, si no su nombre, y sin tienda "FashionStore".
/// Sirve dentro del `title` de un AppBar.
class MarcaTienda extends StatelessWidget {
  const MarcaTienda({super.key, this.tienda, this.estilo});

  final Tienda? tienda;

  /// Estilo del texto; por defecto el del título de la barra.
  final TextStyle? estilo;

  /// Alto del logo: cabe en un AppBar estándar (56 px) con aire alrededor.
  static const alturaLogo = 32.0;

  @override
  Widget build(BuildContext context) {
    final t = tienda;
    final texto = _Nombre(t?.nombre ?? nombrePlataforma, estilo);
    final logo = t?.logoUrl;
    if (logo == null || logo.isEmpty) return texto;
    return Semantics(
      label: t!.nombre,
      image: true,
      child: CachedNetworkImage(
        imageUrl: logo,
        height: alturaLogo,
        fit: BoxFit.contain,
        alignment: Alignment.centerLeft,
        placeholder: (context, url) => const SizedBox(height: alturaLogo),
        errorWidget: (context, url, error) => texto,
      ),
    );
  }
}

class _Nombre extends StatelessWidget {
  const _Nombre(this.texto, this.estilo);

  final String texto;
  final TextStyle? estilo;

  @override
  Widget build(BuildContext context) {
    return Text(
      texto,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: estilo ?? Theme.of(context).appBarTheme.titleTextStyle,
    );
  }
}
