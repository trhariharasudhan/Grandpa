import 'dart:async';
import 'dart:convert';

import 'package:battery_plus/battery_plus.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:speech_to_text/speech_to_text.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

void main() {
  runApp(const GrandpaCompanionApp());
}

class GrandpaCompanionApp extends StatelessWidget {
  const GrandpaCompanionApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Grandpa Companion',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF6244C5),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF12141D),
        useMaterial3: true,
      ),
      home: const CompanionHome(),
    );
  }
}

class CompanionHome extends StatefulWidget {
  const CompanionHome({super.key});

  @override
  State<CompanionHome> createState() => _CompanionHomeState();
}

class _CompanionHomeState extends State<CompanionHome> {
  static const _native = MethodChannel('grandpa/mobile_companion');

  final _storage = const FlutterSecureStorage();
  final _notifications = FlutterLocalNotificationsPlugin();
  final _speech = SpeechToText();
  final _battery = Battery();
  final _serverController = TextEditingController(text: 'ws://127.0.0.1:8000/v1/mobile/ws');
  final _deviceController = TextEditingController(text: 'Android Companion');
  final _pairingController = TextEditingController();
  final _commandController = TextEditingController(text: 'desktop status');
  final _notificationController = TextEditingController(text: 'Grandpa test notification');

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _heartbeatTimer;
  bool _speechReady = false;
  bool _autoReconnect = true;
  String _connectionState = 'offline';
  String _deviceId = '';
  String _trustedToken = '';
  String _latestMessage = 'Not connected';
  String _lastTranscript = '';
  final List<String> _events = <String>[];
  final Set<int> _deliveredOutbox = <int>{};

  @override
  void initState() {
    super.initState();
    _restoreTrustedSession();
    _initializeLocalNotifications();
    _native.setMethodCallHandler(_handleNativeEvent);
  }

  @override
  void dispose() {
    _autoReconnect = false;
    _heartbeatTimer?.cancel();
    _subscription?.cancel();
    _channel?.sink.close();
    _serverController.dispose();
    _deviceController.dispose();
    _pairingController.dispose();
    _commandController.dispose();
    _notificationController.dispose();
    super.dispose();
  }

  Future<void> _restoreTrustedSession() async {
    final server = await _storage.read(key: 'serverUrl');
    final deviceId = await _storage.read(key: 'deviceId');
    final token = await _storage.read(key: 'trustedToken');
    setState(() {
      if (server != null) _serverController.text = server;
      _deviceId = deviceId ?? '';
      _trustedToken = token ?? '';
    });
  }

  Future<void> _initializeLocalNotifications() async {
    const android = AndroidInitializationSettings('ic_launcher');
    await _notifications.initialize(const InitializationSettings(android: android));
  }

  Future<dynamic> _handleNativeEvent(MethodCall call) async {
    if (call.method == 'notification') {
      final args = Map<String, dynamic>.from(call.arguments as Map);
      _send({
        'type': 'notification',
        'notification': {
          'kind': args['kind'] ?? 'app',
          'app': args['app'] ?? 'Android',
          'title': args['title'] ?? '',
          'summary': args['summary'] ?? '',
        },
      });
    }
  }

  Future<void> _requestPermissions() async {
    await Permission.microphone.request();
    await Permission.camera.request();
    await Permission.notification.request();
    await _native.invokeMethod<void>('openNotificationListenerSettings');
    await _initializeSpeech();
    _addEvent('Permission onboarding opened. Enable Grandpa notification access only if you want notification sync.');
  }

  Future<void> _initializeSpeech() async {
    _speechReady = await _speech.initialize(
      onError: (error) => _setError('Speech error: ${error.errorMsg}'),
      onStatus: (status) => _addEvent('Speech status: $status'),
    );
    setState(() {});
  }

  Future<void> _connect() async {
    await _subscription?.cancel();
    await _channel?.sink.close();
    _heartbeatTimer?.cancel();
    setState(() {
      _connectionState = 'connecting';
      _latestMessage = 'Connecting to Grandpa...';
    });
    try {
      final url = _serverController.text.trim();
      final channel = WebSocketChannel.connect(Uri.parse(url));
      _channel = channel;
      await _storage.write(key: 'serverUrl', value: url);
      _subscription = channel.stream.listen(
        _handleMessage,
        onError: (Object error) {
          _setError('Connection error: $error');
          _scheduleReconnect();
        },
        onDone: () {
          setState(() => _connectionState = 'offline');
          _scheduleReconnect();
        },
      );
      setState(() => _connectionState = 'connected');
      if (_deviceId.isNotEmpty && _trustedToken.isNotEmpty) {
        _authenticate();
      }
      _startHeartbeat();
    } catch (error) {
      _setError('Could not connect: $error');
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (!_autoReconnect) return;
    Future<void>.delayed(const Duration(seconds: 4), () {
      if (!mounted || _connectionState == 'connected') return;
      _connect();
    });
  }

  void _startHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = Timer.periodic(const Duration(seconds: 25), (_) => _heartbeat());
  }

  Future<void> _handleMessage(dynamic raw) async {
    final text = raw.toString();
    final Map<String, dynamic> message = jsonDecode(text) as Map<String, dynamic>;
    final type = message['type']?.toString() ?? 'event';
    if (type == 'pairing_code') {
      _deviceId = message['device_id']?.toString() ?? '';
      _pairingController.text = message['pairing_code']?.toString() ?? '';
    }
    if (type == 'paired' && message['ok'] == true) {
      _deviceId = message['device_id']?.toString() ?? _deviceId;
      _trustedToken = message['trusted_token']?.toString() ?? '';
      await _storage.write(key: 'deviceId', value: _deviceId);
      await _storage.write(key: 'trustedToken', value: _trustedToken);
    }
    if (type == 'outbox') {
      await _handleOutbox(message['items']);
    }
    setState(() {
      _latestMessage = text;
      _events.insert(0, '$type: $text');
      if (_events.length > 40) _events.removeLast();
    });
  }

  Future<void> _handleOutbox(dynamic rawItems) async {
    if (rawItems is! List) return;
    for (final item in rawItems) {
      if (item is! Map) continue;
      final id = int.tryParse('${item['id']}') ?? -1;
      if (_deliveredOutbox.contains(id)) continue;
      _deliveredOutbox.add(id);
      final payload = Map<String, dynamic>.from(item['payload'] as Map? ?? {});
      await _notifications.show(
        id,
        payload['title']?.toString() ?? 'Grandpa',
        payload['body']?.toString() ?? '',
        const NotificationDetails(
          android: AndroidNotificationDetails(
            'grandpa_mobile',
            'Grandpa Mobile',
            channelDescription: 'Local Grandpa companion notifications',
            importance: Importance.defaultImportance,
            priority: Priority.defaultPriority,
          ),
        ),
      );
    }
  }

  void _setError(String message) {
    setState(() {
      _connectionState = 'error';
      _latestMessage = message;
    });
    _addEvent(message);
  }

  void _addEvent(String message) {
    setState(() {
      _events.insert(0, message);
      if (_events.length > 40) _events.removeLast();
    });
  }

  void _send(Map<String, Object?> payload) {
    final channel = _channel;
    if (channel == null) {
      _setError('Connect to Grandpa first.');
      return;
    }
    channel.sink.add(jsonEncode(payload));
  }

  void _requestPairing() {
    _send({'type': 'pair_request', 'device_name': _deviceController.text.trim()});
  }

  Future<void> _confirmPairing() async {
    _send({
      'type': 'pair_confirm',
      'device_id': _deviceId,
      'pairing_code': _pairingController.text.trim(),
      'status': await _statusPayload(),
    });
  }

  void _authenticate() {
    _send({'type': 'authenticate', 'device_id': _deviceId, 'trusted_token': _trustedToken});
  }

  Future<void> _heartbeat() async {
    if (_deviceId.isEmpty || _trustedToken.isEmpty) return;
    _authenticate();
    _send({'type': 'heartbeat', 'status': await _statusPayload()});
  }

  void _sendNotification() {
    _send({
      'type': 'notification',
      'notification': {
        'kind': 'app',
        'app': 'Grandpa Companion',
        'title': 'Companion event',
        'summary': _notificationController.text.trim(),
      },
    });
  }

  void _sendCommand() {
    _send({'type': 'remote_command', 'command': _commandController.text.trim()});
  }

  Future<void> _listenAndRelay() async {
    if (!_speechReady) await _initializeSpeech();
    if (!_speechReady) {
      _setError('Speech recognition is unavailable on this device.');
      return;
    }
    await _speech.listen(
      listenFor: const Duration(seconds: 10),
      pauseFor: const Duration(seconds: 2),
      onResult: (result) {
        _lastTranscript = result.recognizedWords;
        setState(() {});
        if (result.finalResult && _lastTranscript.trim().isNotEmpty) {
          _send({'type': 'voice_relay', 'transcript': _lastTranscript.trim()});
        }
      },
    );
  }

  Future<Map<String, Object?>> _statusPayload() async {
    final battery = await _battery.batteryLevel.catchError((_) => -1);
    final chargingState = await _battery.batteryState.catchError((_) => BatteryState.unknown);
    final connectivity = await Connectivity().checkConnectivity().catchError((_) => <ConnectivityResult>[ConnectivityResult.none]);
    return {
      'device_name': _deviceController.text.trim(),
      'battery': battery >= 0 ? battery : null,
      'charging': chargingState == BatteryState.charging || chargingState == BatteryState.full,
      'connectivity': connectivity.map((item) => item.name).join(','),
      'platform': 'android',
      'app_version': '0.2.0',
    };
  }

  void _openQrScanner() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (context) => QrPairingScanner(
          onPayload: (payload) {
            final host = payload['host']?.toString() ?? '';
            final path = payload['websocket_path']?.toString() ?? '/v1/mobile/ws';
            if (host.isNotEmpty) {
              _serverController.text = host.startsWith('ws') ? '$host$path' : 'ws://$host$path';
            }
            _deviceId = payload['device_id']?.toString() ?? _deviceId;
            _pairingController.text = payload['pairing_code']?.toString() ?? _pairingController.text;
            setState(() {});
          },
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 5,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Grandpa Companion'),
          bottom: const TabBar(
            isScrollable: true,
            tabs: [
              Tab(text: 'Onboard'),
              Tab(text: 'Pair'),
              Tab(text: 'Assistant'),
              Tab(text: 'Sync'),
              Tab(text: 'Diagnostics'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _Panel(
              children: [
                const Text('Grandpa uses only local LAN communication. Enable permissions only for features you want.'),
                FilledButton.icon(
                  onPressed: _requestPermissions,
                  icon: const Icon(Icons.verified_user_outlined),
                  label: const Text('Open Permission Setup'),
                ),
                _StatusLine(label: 'Microphone', value: _speechReady ? 'ready' : 'needs permission'),
                const _StatusLine(label: 'Notifications', value: 'Android listener opens in system settings'),
                const _StatusLine(label: 'Token storage', value: 'Flutter secure storage'),
              ],
            ),
            _Panel(
              children: [
                TextField(controller: _serverController, decoration: const InputDecoration(labelText: 'Grandpa WebSocket URL')),
                TextField(controller: _deviceController, decoration: const InputDecoration(labelText: 'Device name')),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  FilledButton(onPressed: _connect, child: const Text('Connect')),
                  FilledButton.tonal(onPressed: _requestPairing, child: const Text('Request Pairing')),
                  FilledButton.tonal(onPressed: _openQrScanner, child: const Text('Scan QR')),
                ]),
                TextField(controller: _pairingController, decoration: const InputDecoration(labelText: 'Pairing code')),
                FilledButton(onPressed: _confirmPairing, child: const Text('Confirm Pairing')),
                if (_pairingController.text.isNotEmpty)
                  Center(
                    child: QrImageView(
                      data: jsonEncode({'device_id': _deviceId, 'pairing_code': _pairingController.text}),
                      size: 160,
                      backgroundColor: Colors.white,
                    ),
                  ),
                _StatusLine(label: 'Connection', value: _connectionState),
                _StatusLine(label: 'Device ID', value: _deviceId.isEmpty ? 'not paired' : _deviceId),
              ],
            ),
            _Panel(
              children: [
                TextField(controller: _commandController, decoration: const InputDecoration(labelText: 'Remote command')),
                FilledButton(onPressed: _sendCommand, child: const Text('Ask Grandpa')),
                const Divider(),
                FilledButton.tonal(onPressed: _listenAndRelay, child: const Text('Hold Phone Mic and Relay')),
                Text('Transcript: ${_lastTranscript.isEmpty ? 'none yet' : _lastTranscript}'),
              ],
            ),
            _Panel(
              children: [
                FilledButton(onPressed: _heartbeat, child: const Text('Send Heartbeat')),
                TextField(controller: _notificationController, decoration: const InputDecoration(labelText: 'Notification summary simulation')),
                FilledButton.tonal(onPressed: _sendNotification, child: const Text('Sync Notification')),
                const Text('Real notification sync uses Android notification listener access and redacts sensitive content before sending.'),
              ],
            ),
            _Panel(
              children: [
                Text('Latest: $_latestMessage'),
                for (final event in _events) Card(child: Padding(padding: const EdgeInsets.all(10), child: Text(event))),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class QrPairingScanner extends StatelessWidget {
  const QrPairingScanner({required this.onPayload, super.key});

  final ValueChanged<Map<String, dynamic>> onPayload;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scan Grandpa Pairing QR')),
      body: MobileScanner(
        onDetect: (capture) {
          final raw = capture.barcodes.isEmpty ? null : capture.barcodes.first.rawValue;
          if (raw == null) return;
          try {
            final payload = jsonDecode(raw) as Map<String, dynamic>;
            if (payload['type'] == 'grandpa_pairing' || payload.containsKey('pairing_code')) {
              onPayload(payload);
              Navigator.of(context).pop();
            }
          } catch (_) {
            // Ignore non-Grandpa QR codes.
          }
        },
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: children.map((child) => Padding(padding: const EdgeInsets.only(bottom: 12), child: child)).toList(),
    );
  }
}

class _StatusLine extends StatelessWidget {
  const _StatusLine({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(width: 120, child: Text(label, style: Theme.of(context).textTheme.labelMedium)),
        Expanded(child: Text(value)),
      ],
    );
  }
}
