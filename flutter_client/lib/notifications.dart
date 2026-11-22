import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

final _notifications = FlutterLocalNotificationsPlugin();

Future<void> initializeRelayNotifications() async {
  if (!Platform.isMacOS) return;
  await _notifications.initialize(
    settings: const InitializationSettings(
      macOS: DarwinInitializationSettings(
        requestAlertPermission: true,
        requestSoundPermission: true,
        requestBadgePermission: false,
        defaultPresentBanner: true,
        defaultPresentList: true,
      ),
    ),
  );
}

class NotificationSink extends StatefulWidget {
  final Control control;

  const NotificationSink({super.key, required this.control});

  @override
  State<NotificationSink> createState() => _NotificationSinkState();
}

class _NotificationSinkState extends State<NotificationSink> {
  int _lastSequence = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _sendIfNew();
    });
  }

  @override
  void didUpdateWidget(NotificationSink oldWidget) {
    super.didUpdateWidget(oldWidget);
    _sendIfNew();
  }

  void _sendIfNew() {
    final sequence = widget.control.getInt('sequence', 0)!;
    if (sequence <= _lastSequence) return;
    _lastSequence = sequence;
    if (!Platform.isMacOS) return;
    final title = widget.control.getString('title') ?? 'Relay';
    final message = widget.control.getString('message') ?? '';
    _notifications.show(
      id: sequence,
      title: title,
      body: message,
      notificationDetails: const NotificationDetails(
        macOS: DarwinNotificationDetails(presentBanner: true, presentList: true),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
