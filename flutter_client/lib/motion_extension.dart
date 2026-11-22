import 'dart:async';

import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';

import 'graph_motion.dart';
import 'panel_motion.dart';

class MotionExtension extends FletExtension {
  @override
  Widget? createWidget(Key? key, Control control) {
    final Widget child;

    switch (control.type) {
      case 'GraphViewport':
        child = GraphViewport(control: control);
      case 'GraphToolbar':
        child = GraphToolbar(control: control);
      case 'GraphGestureSurface':
        child = GraphGestureSurface(control: control);
      case 'ResizableWorkspace':
        child = ResizableWorkspace(control: control);
      case 'SettledSize':
        child = SettledSize(control: control);
      default:
        return null;
    }

    return LayoutControl(key: key, control: control, child: child);
  }
}

/// Responsive Python controls only need the final size, not every drag frame.
class SettledSize extends StatefulWidget {
  final Control control;
  const SettledSize({super.key, required this.control});

  @override
  State<SettledSize> createState() => _SettledSizeState();
}

class _SettledSizeState extends State<SettledSize> {
  Size? _size;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = constraints.biggest;
        if (_size != size && size.isFinite) {
          _size = size;
          _timer?.cancel();
          _timer = Timer(const Duration(milliseconds: 180), () {
            widget.control.triggerEvent('settled', {
              'w': size.width,
              'h': size.height,
            });
          });
        }

        return widget.control.buildWidget('content') ?? const SizedBox.shrink();
      },
    );
  }
}
