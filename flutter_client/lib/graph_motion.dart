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
  double scrollOffset = 0;
  bool horizontal = true;
  double _gestureZoom = 1;
  int? _resetToken;
  Timer? _settleTimer;
  VoidCallback? onSettled;

  double get viewportExtent => horizontal ? viewport.width : viewport.height;
  double get sceneExtent => horizontal ? scene.width : scene.height;
  double get overflow => math.max(0, sceneExtent * zoom - viewportExtent);
  double get thumbExtent => math.min(
    viewportExtent,
    math.max(28, viewportExtent * viewportExtent / (sceneExtent * zoom)),
  );

  void configure(
    Size size,
    Size graphSize,
    Size nodeSize,
    int resetToken,
    bool horizontalFlow,
  ) {
    if (size.width <= 16 || size.height <= 1) return;
    if (viewport == size &&
        scene == graphSize &&
        _resetToken == resetToken &&
        horizontal == horizontalFlow)
      return;

    final reset = _resetToken != resetToken || horizontal != horizontalFlow;
    horizontal = horizontalFlow;
    viewport = size;
    scene = graphSize;
    _resetToken = resetToken;

    final crossExtent = horizontal ? size.height : size.width;
    final sceneCrossExtent = horizontal ? graphSize.height : graphSize.width;
    final nodeExtent = horizontal ? nodeSize.width : nodeSize.height;
    final rowFit =
        (crossExtent - 16).clamp(1.0, double.infinity) / sceneCrossExtent;
    final nodeFit = viewportExtent / (nodeExtent + 64);
    maximum = math.min(2, math.min(rowFit, nodeFit));
    minimum = math.min(maximum, viewportExtent / sceneExtent);
    zoom = reset ? minimum : zoom.clamp(minimum, maximum);
    scrollOffset = reset ? 0 : scrollOffset.clamp(0, overflow);

    // LayoutBuilder runs during build. Notify the toolbar after layout completes.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_users > 0) changed();
    });
  }

  void zoomBy(double factor, {double delta = 0}) {
    if (viewport.isEmpty) return;

    final anchor = viewportExtent / 2;
    final graphPosition = (scrollOffset + anchor) / zoom;
    zoom = (zoom * factor).clamp(minimum, maximum);
    scrollOffset = (graphPosition * zoom - anchor - delta).clamp(0, overflow);

    changed();
  }

  void beginGesture() {
    _gestureZoom = zoom;
    _settleTimer?.cancel();
  }

  void updateGesture(double scale, Offset movement) {
    final delta = horizontal && movement.dx.abs() > movement.dy.abs()
        ? movement.dx
        : movement.dy;

    zoomBy(_gestureZoom * scale / zoom, delta: delta);
  }

  void scrollTo(double position) {
    scrollOffset = position.clamp(0, overflow);

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
  double _dragPosition = 0;
  double _dragOffset = 0;

  @override
  void initState() {
    super.initState();
    channel = widget.control.getString('channel')!;
    motion = GraphMotion.acquire(channel);
    motion.onSettled = () {
      widget.control.updateProperties({
        'zoom': motion.zoom,
        'scroll_top': motion.horizontal ? 0.0 : motion.scrollOffset,
        'scroll_left': motion.horizontal ? motion.scrollOffset : 0.0,
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
          Size(
            control.getDouble('node_width', 208)!,
            control.getDouble('node_height', 120)!,
          ),
          control.getInt('reset_token', 0)!,
          control.getBool('horizontal', true)!,
        );

        return AnimatedBuilder(
          animation: motion,
          child: RepaintBoundary(child: control.buildWidget('content')),
          builder: (context, child) {
            final travel = motion.viewportExtent - motion.thumbExtent;
            final thumbOffset = motion.overflow > 0
                ? motion.scrollOffset / motion.overflow * travel
                : 0.0;
            final centeredX =
                (motion.viewport.width - scene.width * motion.zoom) / 2;
            final centeredY =
                (motion.viewport.height - scene.height * motion.zoom) / 2;

            return ClipRect(
              child: Stack(
                children: [
                  Positioned(
                    left: motion.horizontal
                        ? math.max(0, centeredX) - motion.scrollOffset
                        : centeredX,
                    top: motion.horizontal
                        ? centeredY
                        : math.max(0, centeredY) - motion.scrollOffset,
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
                      right: motion.horizontal ? null : 2,
                      bottom: motion.horizontal ? 2 : null,
                      left: motion.horizontal ? thumbOffset : null,
                      top: motion.horizontal ? null : thumbOffset,
                      width: motion.horizontal ? motion.thumbExtent : 6,
                      height: motion.horizontal ? 6 : motion.thumbExtent,
                      child: MouseRegion(
                        cursor: SystemMouseCursors.grab,
                        child: GestureDetector(
                          behavior: HitTestBehavior.opaque,
                          onPanStart: (event) {
                            _dragPosition = motion.horizontal
                                ? event.globalPosition.dx
                                : event.globalPosition.dy;
                            _dragOffset = motion.scrollOffset;
                          },
                          onPanUpdate: (event) {
                            if (travel > 0) {
                              final position = motion.horizontal
                                  ? event.globalPosition.dx
                                  : event.globalPosition.dy;
                              motion.scrollTo(
                                _dragOffset +
                                    (position - _dragPosition) *
                                        motion.overflow /
                                        travel,
                              );
                            }
                          },
                          onPanEnd: (_) => motion.settle(),
                          onPanCancel: motion.settle,
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
              iconSize: 20,
              constraints: const BoxConstraints.tightFor(width: 44, height: 44),
              onPressed: motion.zoom > motion.minimum + 0.00001
                  ? () => motion.zoomBy(1 / 1.2)
                  : null,
              icon: const Icon(Icons.remove),
            ),
            Expanded(
              child: Text(
                '${(motion.zoom * 100).round()}%',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: Color(0xFFA8A6A3)),
              ),
            ),
            IconButton(
              tooltip: 'Zoom in',
              iconSize: 20,
              constraints: const BoxConstraints.tightFor(width: 44, height: 44),
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
                  final movement = (signal as PointerScrollEvent).scrollDelta;
                  if (motion.horizontal && movement.dx != 0) {
                    motion.scrollTo(motion.scrollOffset + movement.dx);
                  } else {
                    final delta = movement.dy.clamp(-400, 400);
                    motion.zoomBy(math.exp(-delta / 400));
                  }
                });
              }
            },
      onPointerPanZoomStart: !active ? null : (_) => motion.beginGesture(),
      onPointerPanZoomUpdate: !active
          ? null
          : (event) => motion.updateGesture(event.scale, event.panDelta),
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
                  motion.updateGesture(event.scale, event.focalPointDelta),
        onScaleEnd: !active ? null : (_) => motion.settle(),
        child: child,
      ),
    );
  }
}
