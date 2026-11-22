import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';

import 'motion_extension.dart';

Future<void> main(List<String> arguments) async {
  WidgetsFlutterBinding.ensureInitialized();
  await setupDesktop();

  if (arguments.isEmpty) {
    throw ArgumentError('Start this client through src/main.py.');
  }

  if (arguments.length > 1) {
    await File(arguments[1]).writeAsString('$pid');
  }

  if (kReleaseMode) {
    debugPrint = (String? message, {int? wrapWidth}) {};
  }

  runApp(
    FletApp(
      pageUrl: arguments[0],
      assetsDir: arguments.length > 2 ? arguments[2] : '',
      extensions: [MotionExtension()],
    ),
  );
}
