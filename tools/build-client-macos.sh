#!/bin/bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
client_root="$repo_root/build/native_client"
flutter="${1:-${FLUTTER_BIN:-}}"
if [[ -z "$flutter" ]]; then
    if [[ -x "$repo_root/build/flutter-sdk/bin/flutter" ]]; then
        flutter="$repo_root/build/flutter-sdk/bin/flutter"
    else
        flutter="$(command -v flutter || true)"
    fi
fi
if [[ -z "$flutter" || ! -x "$flutter" ]]; then
    echo 'Flutter is required. Pass its executable path as the first argument.' >&2
    exit 1
fi
if [[ "$(uname -s)" != Darwin ]]; then
    echo 'Build this client on macOS.' >&2
    exit 1
fi
if [[ ! -d "$client_root/macos" ]]; then
    "$flutter" create --platforms macos --project-name dependency_client --empty --no-pub "$client_root"
fi
cp "$repo_root/flutter_client/pubspec.yaml" "$client_root/pubspec.yaml"
cp "$repo_root"/flutter_client/lib/*.dart "$client_root/lib/"
# This local development runner exchanges a PID file and Unix socket with
# Python outside an app container, just like the desktop Flet client.
for mode in Release DebugProfile; do
    /usr/libexec/PlistBuddy -c 'Set :com.apple.security.app-sandbox false' "$client_root/macos/Runner/$mode.entitlements"
done
# The Flet client connects to the local Python process over a socket.
/usr/libexec/PlistBuddy -c 'Set :com.apple.security.network.client true' "$client_root/macos/Runner/Release.entitlements" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c 'Add :com.apple.security.network.client bool true' "$client_root/macos/Runner/Release.entitlements"
/usr/libexec/PlistBuddy -c 'Set :com.apple.security.network.client true' "$client_root/macos/Runner/DebugProfile.entitlements" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c 'Add :com.apple.security.network.client bool true' "$client_root/macos/Runner/DebugProfile.entitlements"
cd "$client_root"
"$flutter" pub get
"$flutter" analyze lib
"$flutter" build macos --release --no-tree-shake-icons
cp "$repo_root/assets/LICENSE.lucide" "build/macos/Build/Products/Release/dependency_client.app/Contents/Resources/LICENSE.lucide"
echo 'Built macOS client. Run: .venv/bin/python src/main.py'
