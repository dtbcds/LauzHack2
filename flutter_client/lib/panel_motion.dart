import 'package:flet/flet.dart';
import 'package:material_ui/material_ui.dart';

class ResizableWorkspace extends StatefulWidget {
  final Control control;
  const ResizableWorkspace({super.key, required this.control});

  @override
  State<ResizableWorkspace> createState() => _ResizableWorkspaceState();
}

class _ResizableWorkspaceState extends State<ResizableWorkspace> {
  double? _preferredWidth;
  double _dragX = 0;
  double _dragWidth = 0;
  double _width = 0;

  void _settle() {
    widget.control.updateProperties({'panel_width': _width}, dart: false);
  }

  @override
  Widget build(BuildContext context) {
    final control = widget.control;
    final board = control.buildWidget('content') ?? const SizedBox.shrink();
    final open = control.getBool('panel_open', false)!;

    return LayoutBuilder(
      builder: (context, constraints) {
        final workspaceWidth = constraints.maxWidth;
        final docked = workspaceWidth >= 1000;
        final maxWidth = (workspaceWidth - (docked ? 470 : 12)).clamp(
          0.0,
          double.infinity,
        );
        final minWidth = maxWidth < 280 ? maxWidth : 280.0;
        final defaultWidth = (workspaceWidth * 0.31).clamp(340.0, 460.0);
        _width = (_preferredWidth ?? defaultWidth).clamp(minWidth, maxWidth);

        return Stack(
          fit: StackFit.expand,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(child: board),
                if (open && docked) SizedBox(width: _width),
              ],
            ),
            if (open && !docked)
              Positioned.fill(
                child: GestureDetector(
                  onTap: () => control.triggerEvent('close'),
                  child: const ColoredBox(color: Color(0x66000000)),
                ),
              ),
            if (open)
              Positioned(
                right: 0,
                top: 0,
                bottom: 0,
                width: _width,
                child: control.buildWidget('panel') ?? const SizedBox.shrink(),
              ),
            if (open)
              Positioned(
                right: _width - 6,
                top: 0,
                bottom: 0,
                width: 12,
                child: MouseRegion(
                  cursor: SystemMouseCursors.resizeLeftRight,
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onHorizontalDragDown: (event) {
                      _dragX = event.globalPosition.dx;
                      _dragWidth = _width;
                    },
                    onHorizontalDragUpdate: (event) {
                      setState(() {
                        _preferredWidth =
                            (_dragWidth + _dragX - event.globalPosition.dx)
                                .clamp(minWidth, maxWidth);
                      });
                    },
                    onHorizontalDragEnd: (_) => _settle(),
                    onHorizontalDragCancel: _settle,
                    child: Center(
                      child: Container(
                        width: 2,
                        height: 24,
                        decoration: BoxDecoration(
                          color: const Color(0xFFA8A6A3),
                          borderRadius: BorderRadius.circular(1),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}
