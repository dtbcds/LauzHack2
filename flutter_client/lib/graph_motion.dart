import 'dart:async';
import 'dart:math' as math;

import 'package:flet/flet.dart';
import 'package:flutter/gestures.dart';
import 'package:material_ui/material_ui.dart';

/// Shared only by the viewport, toolbar and gesture surfaces for one graph.
/// Pointer events never cross the Python bridge; only settled state does.
class GraphMotion extends ChangeNotifier {
  static final _channels = <String, GraphMotion>{};

  static GraphMotion acquire(String channel) {
    final motion = _channels.putIfAbsent(channel, GraphMotion.new);
    motion._users++;
    return motion;
  }

  int _users = 0;
  Size viewport = Size.zero;
  Size scene = const Size(1, 1);
  double zoom = 1;
  double minimum = 1;
  double maximum = 1;
  double scrollTop = 0;
  double _gestureZoom = 1;
  int? _resetToken;
  Timer? _settleTimer;
  VoidCallback? onSettled;

  double get overflow => math.max(0, scene.height * zoom - viewport.height);
  double get thumbHeight => math.min(
    viewport.height,
    math.max(28, viewport.height * viewport.height / (scene.height * zoom)),
  );

  void configure(Size size, Size graphSize, double nodeHeight, int resetToken) {
    if (size.width <= 16 || size.height <= 1) return;
    if (viewport == size && scene == graphSize && _resetToken == resetToken)
      return;

    final reset = _resetToken != resetToken;
    viewport = size;
    scene = graphSize;
    _resetToken = resetToken;

    final rowFit = (size.width - 16) / graphSize.width;
    final nodeFit = size.height / (nodeHeight + 64);
    maximum = math.min(2, math.min(rowFit, nodeFit));
    minimum = math.min(maximum, size.height / graphSize.height);
    zoom = reset ? minimum : zoom.clamp(minimum, maximum);
    scrollTop = reset ? 0 : scrollTop.clamp(0, overflow);

    // LayoutBuilder runs during build. Notify the toolbar after layout completes.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_users > 0) changed();
    });
  }

  void zoomBy(double factor, {double deltaY = 0}) {
    if (viewport.isEmpty) return;

    final anchor = viewport.height / 2;
    final graphY = (scrollTop + anchor) / zoom;
    zoom = (zoom * factor).clamp(minimum, maximum);
    scrollTop = (graphY * zoom - anchor - deltaY).clamp(0, overflow);

    changed();
  }

  void beginGesture() {
    _gestureZoom = zoom;
    _settleTimer?.cancel();
  }

  void updateGesture(double scale, double deltaY) {
    zoomBy(_gestureZoom * scale / zoom, deltaY: deltaY);
  }

  void scrollTo(double position) {
    scrollTop = position.clamp(0, overflow);

    changed();
  }

  void changed() {
    notifyListeners();
    _settleTimer?.cancel();
    _settleTimer = Timer(const Duration(milliseconds: 180), settle);
  }

  void settle() {
    _settleTimer?.cancel();
    onSettled?.call();
  }

  void release(String channel) {
    _users--;
    if (_users == 0) {
      _settleTimer?.cancel();
      _channels.remove(channel);
      dispose();
    }
  }
}

class GraphViewport extends StatefulWidget {
  final Control control;
  const GraphViewport({super.key, required this.control});

  @override
  State<GraphViewport> createState() => _GraphViewportState();
}

class _GraphViewportState extends State<GraphViewport> {
  late final String channel;
  late final GraphMotion motion;
  double _dragY = 0;
  double _dragTop = 0;

  @override
  void initState() {
    super.initState();
    channel = widget.control.getString('channel')!;
    motion = GraphMotion.acquire(channel);
    motion.onSettled = () {
      widget.control.updateProperties({
        'zoom': motion.zoom,
        'scroll_top': motion.scrollTop,
      }, dart: false);
    };
  }

  @override
  void dispose() {
    motion.onSettled = null;
    motion.release(channel);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final control = widget.control;
    final scene = Size(
      control.getDouble('scene_width', 1)!,
      control.getDouble('scene_height', 1)!,
    );

    return LayoutBuilder(
      builder: (context, constraints) {
        motion.configure(
          constraints.biggest,
          scene,
          control.getDouble('node_height', 120)!,
          control.getInt('reset_token', 0)!,
        );

        return AnimatedBuilder(
          animation: motion,
          child: RepaintBoundary(child: control.buildWidget('content')),
          builder: (context, child) {
            final travel = motion.viewport.height - motion.thumbHeight;
            final thumbTop = motion.overflow > 0
                ? motion.scrollTop / motion.overflow * travel
                : 0.0;

            return ClipRect(
              child: Stack(
                children: [
                  Positioned(
                    left:
                        (motion.viewport.width - scene.width * motion.zoom) / 2,
                    top: -motion.scrollTop,
                    width: scene.width,
                    height: scene.height,
                    child: Transform.scale(
                      scale: motion.zoom,
                      alignment: Alignment.topLeft,
                      child: child,
                    ),
                  ),
                  if (motion.overflow > 0.5)
                    Positioned(
                      right: 2,
                      top: thumbTop,
                      width: 6,
                      height: motion.thumbHeight,
                      child: MouseRegion(
                        cursor: SystemMouseCursors.grab,
                        child: GestureDetector(
                          behavior: HitTestBehavior.opaque,
                          onVerticalDragStart: (event) {
                            _dragY = event.globalPosition.dy;
                            _dragTop = motion.scrollTop;
                          },
                          onVerticalDragUpdate: (event) {
                            if (travel > 0) {
                              motion.scrollTo(
                                _dragTop +
                                    (event.globalPosition.dy - _dragY) *
                                        motion.overflow /
                                        travel,
                              );
                            }
                          },
                          onVerticalDragEnd: (_) => motion.settle(),
                          onVerticalDragCancel: motion.settle,
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              color: const Color(0xFFA8A6A3),
                              borderRadius: BorderRadius.circular(4),
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            );
          },
        );
      },
    );
  }
}

class GraphToolbar extends StatefulWidget {
  final Control control;
  const GraphToolbar({super.key, required this.control});

  @override
  State<GraphToolbar> createState() => _GraphToolbarState();
}

class _GraphToolbarState extends State<GraphToolbar> {
  late final String channel;
  late final GraphMotion motion;

  @override
  void initState() {
    super.initState();
    channel = widget.control.getString('channel')!;
    motion = GraphMotion.acquire(channel);
  }

  @override
  void dispose() {
    motion.release(channel);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: motion,
      builder: (context, child) {
        return Row(
          children: [
            IconButton(
              tooltip: 'Zoom out',
              iconSize: 18,
              constraints: const BoxConstraints.tightFor(width: 36, height: 40),
              onPressed: motion.zoom > motion.minimum + 0.00001
                  ? () => motion.zoomBy(1 / 1.2)
                  : null,
              icon: const Icon(Icons.remove),
            ),
            Expanded(
              child: Text(
                '${(motion.zoom * 100).round()}%',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 12, color: Color(0xFFA8A6A3)),
              ),
            ),
            IconButton(
              tooltip: 'Zoom in',
              iconSize: 18,
              constraints: const BoxConstraints.tightFor(width: 36, height: 40),
              onPressed: motion.zoom < motion.maximum - 0.00001
                  ? () => motion.zoomBy(1.2)
                  : null,
              icon: const Icon(Icons.add),
            ),
          ],
        );
      },
    );
  }
}

class GraphGestureSurface extends StatefulWidget {
  final Control control;
  const GraphGestureSurface({super.key, required this.control});

  @override
  State<GraphGestureSurface> createState() => _GraphGestureSurfaceState();
}

class _GraphGestureSurfaceState extends State<GraphGestureSurface> {
  late final String channel;
  late final GraphMotion motion;

  @override
  void initState() {
    super.initState();
    channel = widget.control.getString('channel')!;
    motion = GraphMotion.acquire(channel);
  }

  @override
  void dispose() {
    motion.release(channel);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final child =
        widget.control.buildWidget('content') ?? const SizedBox.shrink();
    final active = widget.control.getBool('active', false)!;

    return Listener(
      behavior: HitTestBehavior.translucent,
      onPointerSignal: !active
          ? null
          : (event) {
              if (event is PointerScrollEvent) {
                GestureBinding.instance.pointerSignalResolver.register(event, (
                  signal,
                ) {
                  final delta = (signal as PointerScrollEvent).scrollDelta.dy
                      .clamp(-400, 400);
                  motion.zoomBy(math.exp(-delta / 400));
                });
              }
            },
      onPointerPanZoomStart: !active ? null : (_) => motion.beginGesture(),
      onPointerPanZoomUpdate: !active
          ? null
          : (event) => motion.updateGesture(event.scale, event.panDelta.dy),
      onPointerPanZoomEnd: !active ? null : (_) => motion.settle(),
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        supportedDevices: const {
          PointerDeviceKind.touch,
          PointerDeviceKind.stylus,
        },
        onScaleStart: !active ? null : (_) => motion.beginGesture(),
        onScaleUpdate: !active
            ? null
            : (event) =>
                  motion.updateGesture(event.scale, event.focalPointDelta.dy),
        onScaleEnd: !active ? null : (_) => motion.settle(),
        child: child,
      ),
    );
  }
}
