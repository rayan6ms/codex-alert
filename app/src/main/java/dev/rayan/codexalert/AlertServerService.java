package dev.rayan.codexalert;

import android.app.Notification;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLServerSocket;
import javax.net.ssl.SSLServerSocketFactory;
import javax.net.ssl.SSLSocket;

public final class AlertServerService extends Service {
    static final int PORT = 24601;
    static final String ACTION_TEST = "dev.rayan.codexalert.TEST";
    static final String ACTION_READY = "dev.rayan.codexalert.READY";
    private static final int MAX_HEADER_BYTES = 8192;
    private static final int MAX_BODY_BYTES = 8192;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private Thread serverThread;
    private SSLServerSocket serverSocket;
    private NsdManager.RegistrationListener nsdListener;
    private final Object watcherLock = new Object();
    private String watchedEventId = "";

    static void start(Context context) {
        Intent intent = new Intent(context, AlertServerService.class);
        context.startForegroundService(intent);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        AlertNotifier.ensureChannels(this);
        showForeground(AlertNotifier.ready(this, "Starting private LAN/Tailscale receiver…"));
        running.set(true);
        serverThread = new Thread(this::serverLoop, "codex-alert-server");
        serverThread.start();
        watchActiveAlert();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_TEST.equals(intent.getAction())) {
            long now = System.currentTimeMillis();
            acceptAlert(
                    UUID.randomUUID().toString(),
                    "Codex finished · local test",
                    "phone · Direct receiver test completed successfully.",
                    "on-device test",
                    "",
                    "",
                    now,
                    now
            );
        } else if (intent != null && ACTION_READY.equals(intent.getAction())) {
            AlertNotifier.clearCompletion(this);
            AlertStore.clearActive(this, "", "on-device");
        }
        watchActiveAlert();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running.set(false);
        closeServer();
        unregisterNsd();
        if (serverThread != null) {
            serverThread.interrupt();
        }
        AlertStore.serverState(this, "stopped", "");
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void showForeground(Notification notification) {
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(
                    AlertNotifier.RECEIVER_NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING
            );
        } else {
            startForeground(AlertNotifier.RECEIVER_NOTIFICATION_ID, notification);
        }
    }

    private void serverLoop() {
        int failures = 0;
        while (running.get()) {
            try {
                serverSocket = createServerSocket();
                failures = 0;
                registerNsd();
                AlertStore.serverState(this, "running", "");
                showForeground(AlertNotifier.ready(this, readyDetail()));
                while (running.get()) {
                    Socket socket = serverSocket.accept();
                    handleClient((SSLSocket) socket);
                }
            } catch (Exception exception) {
                if (!running.get()) {
                    break;
                }
                failures++;
                String error = cleanError(exception);
                AlertStore.serverState(this, "error", error);
                showForeground(AlertNotifier.ready(this, "Receiver error · retrying automatically"));
                if (running.get()) {
                    try {
                        Thread.sleep(Math.min(60_000L, failures * 5_000L));
                    } catch (InterruptedException ignored) {
                        Thread.currentThread().interrupt();
                    }
                }
            } finally {
                closeServer();
                unregisterNsd();
            }
        }
    }

    private SSLServerSocket createServerSocket() throws Exception {
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(DeviceIdentity.keyManagers().getKeyManagers(), null, null);
        SSLServerSocketFactory factory = context.getServerSocketFactory();
        SSLServerSocket socket = (SSLServerSocket) factory.createServerSocket();
        socket.setReuseAddress(true);
        socket.bind(new InetSocketAddress(PORT), 8);
        return socket;
    }

    private void handleClient(SSLSocket socket) {
        try (socket) {
            socket.setSoTimeout(4_000);
            if (!allowedSource(socket.getInetAddress())) {
                return;
            }
            socket.startHandshake();
            BufferedInputStream input = new BufferedInputStream(socket.getInputStream());
            OutputStream output = socket.getOutputStream();
            HttpRequest request = readRequest(input);
            if (request == null) {
                sendResponse(output, 400, "invalid-request");
                return;
            }
            if ("POST".equals(request.method) && "/v1/pair".equals(request.path)) {
                pairDesktop(request, output);
                return;
            }
            if (!authorized(request.headers.get("authorization"))) {
                sendResponse(output, 401, "unauthorized");
                return;
            }
            if ("GET".equals(request.method) && "/v1/health".equals(request.path)) {
                sendResponse(output, 200, "ok");
                return;
            }
            if ("POST".equals(request.method) && "/v1/clear".equals(request.path)) {
                JSONObject payload = new JSONObject(new String(request.body, StandardCharsets.UTF_8));
                String eventId = limited(payload.optString("id", ""), 128);
                if (!eventId.matches("[A-Za-z0-9._:-]{1,128}")) {
                    sendResponse(output, 400, "invalid-event-id");
                    return;
                }
                sendResponse(output, 200, clearAlert(eventId));
                return;
            }
            if (!"POST".equals(request.method) || !"/v1/alert".equals(request.path)) {
                sendResponse(output, 404, "not-found");
                return;
            }
            JSONObject payload = new JSONObject(new String(request.body, StandardCharsets.UTF_8));
            String eventId = limited(payload.optString("id", ""), 128);
            String title = limited(payload.optString("title", "Codex finished"), 240);
            String body = limited(payload.optString("body", "Task completed."), 2400);
            String environmentId = limited(payload.optString("environment_id", ""), 128);
            String threadId = limited(payload.optString("thread_id", ""), 128);
            long completedAt = payload.optLong("completed_at_ms", 0);
            long sentAt = payload.optLong("sent_at_ms", 0);
            if (!eventId.matches("[A-Za-z0-9._:-]{1,128}")) {
                sendResponse(output, 400, "invalid-event-id");
                return;
            }
            boolean hasT3Target = !environmentId.isEmpty() || !threadId.isEmpty();
            if (hasT3Target && (!T3Integration.validRoutePart(environmentId)
                    || !T3Integration.validRoutePart(threadId))) {
                sendResponse(output, 400, "invalid-t3-target");
                return;
            }
            String result = acceptAlert(
                    eventId,
                    title,
                    body,
                    transportFor(socket.getInetAddress()),
                    environmentId,
                    threadId,
                    completedAt,
                    sentAt
            );
            sendResponse(output, "notifications-disabled".equals(result) ? 503 : 200, result);
        } catch (JSONException exception) {
            // The connection is already closed; malformed JSON is not retried server-side.
        } catch (Exception ignored) {
            // A single invalid or interrupted client must never stop the listener.
        }
    }

    private void pairDesktop(HttpRequest request, OutputStream output) throws IOException {
        try {
            JSONObject payload = new JSONObject(new String(request.body, StandardCharsets.UTF_8));
            String result = DeviceIdentity.acceptPairingCode(this, payload.optString("code", ""));
            if (!"paired".equals(result)) {
                JSONObject error = new JSONObject()
                        .put("status", result)
                        .put("message", pairingMessage(result));
                sendJsonResponse(output, 401, error);
                return;
            }
            JSONObject response = new JSONObject()
                    .put("status", "paired")
                    .put("token", DeviceIdentity.deliveryToken(this))
                    .put("device_name", DeviceIdentity.deviceName())
                    .put("addresses", new org.json.JSONArray(networkAddresses()));
            sendJsonResponse(output, 200, response);
            showForeground(AlertNotifier.ready(this, readyDetail()));
        } catch (JSONException exception) {
            sendResponse(output, 400, "invalid-request");
        }
    }

    private String pairingMessage(String result) {
        return switch (result) {
            case "invalid-code" -> "The pairing code is incorrect.";
            case "too-many-attempts" -> "Too many attempts. Create a new code in the app.";
            default -> "The pairing code expired. Create a new code in the app.";
        };
    }

    private synchronized String acceptAlert(
            String eventId,
            String title,
            String body,
            String transport,
            String environmentId,
            String threadId,
            long completedAt,
            long sentAt
    ) {
        if (!AlertNotifier.completionNotificationsEnabled(this)) {
            AlertStore.deliveryError(this, "notifications-disabled");
            return "notifications-disabled";
        }
        if (AlertStore.alreadyReceived(this, eventId)) {
            AlertStore.recordDuplicate(this);
            return "duplicate";
        }
        AlertStore.recordDelivery(
                this, eventId, title, body, transport, environmentId, threadId, completedAt, sentAt
        );
        AlertNotifier.postCompletion(
                this, title, body, eventId, environmentId, threadId, completedAt
        );
        if (T3Integration.autoClearEnabled(this)) {
            startT3Watcher(eventId, AlertStore.activeSince(this));
        }
        return "ok";
    }

    private synchronized String clearAlert(String eventId) {
        String activeEventId = AlertStore.activeEventId(this);
        if (activeEventId.isEmpty()) {
            return "already-clear";
        }
        if (!activeEventId.equals(eventId)) {
            return "stale";
        }
        AlertNotifier.clearCompletion(this);
        AlertStore.clearActive(this, eventId, "desktop-input");
        return "cleared";
    }

    private void watchActiveAlert() {
        String eventId = AlertStore.activeEventId(this);
        if (!eventId.isEmpty() && T3Integration.autoClearEnabled(this)) {
            startT3Watcher(eventId, AlertStore.activeSince(this));
        }
    }

    private void startT3Watcher(String eventId, long activeSince) {
        synchronized (watcherLock) {
            if (eventId.equals(watchedEventId)) {
                return;
            }
            watchedEventId = eventId;
        }
        Thread watcher = new Thread(
                () -> watchForT3Resume(eventId, activeSince),
                "codex-alert-t3-foreground"
        );
        watcher.start();
    }

    private void watchForT3Resume(String eventId, long activeSince) {
        try {
            if (!T3Integration.hasUsageAccess(this)) {
                AlertStore.usageWatchState(this, "permission-required");
                return;
            }
            AlertStore.usageWatchState(this, "watching");
            long now = System.currentTimeMillis();
            long cursor = Math.max(activeSince, now - 24L * 60 * 60 * 1000);
            while (running.get() && eventId.equals(AlertStore.activeEventId(this))) {
                if (!T3Integration.hasUsageAccess(this)) {
                    AlertStore.usageWatchState(this, "permission-required");
                    return;
                }
                now = System.currentTimeMillis();
                if (T3Integration.wasResumed(this, cursor, now)) {
                    synchronized (this) {
                        if (eventId.equals(AlertStore.activeEventId(this))) {
                            AlertNotifier.clearCompletion(this);
                            AlertStore.clearActive(this, eventId, "t3-opened");
                        }
                    }
                    AlertStore.usageWatchState(this, "cleared-on-t3-open");
                    return;
                }
                cursor = Math.max(cursor, now - 250);
                try {
                    Thread.sleep(750);
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
            AlertStore.usageWatchState(this, "idle");
        } catch (SecurityException exception) {
            AlertStore.usageWatchState(this, "permission-required");
        } finally {
            synchronized (watcherLock) {
                if (eventId.equals(watchedEventId)) {
                    watchedEventId = "";
                }
            }
        }
    }

    private HttpRequest readRequest(BufferedInputStream input) throws IOException {
        int headerBytes = 0;
        String requestLine = readLine(input, 1024);
        if (requestLine == null) {
            return null;
        }
        headerBytes += requestLine.length();
        String[] requestParts = requestLine.split(" ");
        if (requestParts.length != 3 || !requestParts[2].startsWith("HTTP/1.")) {
            return null;
        }
        Map<String, String> headers = new HashMap<>();
        while (true) {
            String line = readLine(input, 2048);
            if (line == null) {
                return null;
            }
            headerBytes += line.length();
            if (headerBytes > MAX_HEADER_BYTES) {
                return null;
            }
            if (line.isEmpty()) {
                break;
            }
            int separator = line.indexOf(':');
            if (separator <= 0) {
                return null;
            }
            headers.put(
                    line.substring(0, separator).trim().toLowerCase(Locale.ROOT),
                    line.substring(separator + 1).trim()
            );
        }
        int length = 0;
        try {
            length = Integer.parseInt(headers.getOrDefault("content-length", "0"));
        } catch (NumberFormatException exception) {
            return null;
        }
        if (length < 0 || length > MAX_BODY_BYTES) {
            return null;
        }
        byte[] body = new byte[length];
        int offset = 0;
        while (offset < length) {
            int count = input.read(body, offset, length - offset);
            if (count == -1) {
                return null;
            }
            offset += count;
        }
        return new HttpRequest(requestParts[0], requestParts[1], headers, body);
    }

    private String readLine(InputStream input, int maximum) throws IOException {
        ByteArrayOutputStream line = new ByteArrayOutputStream();
        int previous = -1;
        while (line.size() <= maximum) {
            int current = input.read();
            if (current == -1) {
                return null;
            }
            if (previous == '\r' && current == '\n') {
                byte[] bytes = line.toByteArray();
                return new String(bytes, 0, Math.max(0, bytes.length - 1), StandardCharsets.US_ASCII);
            }
            line.write(current);
            previous = current;
        }
        return null;
    }

    private boolean authorized(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            return false;
        }
        byte[] supplied = authorization.substring(7).getBytes(StandardCharsets.UTF_8);
        byte[] expected = DeviceIdentity.deliveryToken(this).getBytes(StandardCharsets.UTF_8);
        return expected.length >= 32 && MessageDigest.isEqual(supplied, expected);
    }

    private void sendResponse(OutputStream output, int status, String result) throws IOException {
        JSONObject payload = new JSONObject();
        try {
            payload.put("status", result);
        } catch (JSONException ignored) {
            // A fixed string cannot fail JSON encoding.
        }
        sendJsonResponse(output, status, payload);
    }

    private void sendJsonResponse(OutputStream output, int status, JSONObject payload) throws IOException {
        byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
        String reason = status == 200 ? "OK" : status == 401 ? "Unauthorized" :
                status == 404 ? "Not Found" : status == 503 ? "Service Unavailable" : "Bad Request";
        String headers = "HTTP/1.1 " + status + " " + reason + "\r\n"
                + "Content-Type: application/json\r\n"
                + "Content-Length: " + body.length + "\r\n"
                + "Connection: close\r\n\r\n";
        output.write(headers.getBytes(StandardCharsets.US_ASCII));
        output.write(body);
        output.flush();
    }

    private boolean allowedSource(InetAddress address) {
        if (address.isLoopbackAddress() || address.isSiteLocalAddress()) {
            return true;
        }
        byte[] bytes = address.getAddress();
        if (bytes.length == 4) {
            int first = bytes[0] & 0xff;
            int second = bytes[1] & 0xff;
            return first == 100 && second >= 64 && second <= 127;
        }
        if (bytes.length == 16) {
            boolean tailscaleV6 = (bytes[0] & 0xff) == 0xfd
                    && (bytes[1] & 0xff) == 0x7a
                    && (bytes[2] & 0xff) == 0x11
                    && (bytes[3] & 0xff) == 0x5c
                    && (bytes[4] & 0xff) == 0xa1
                    && (bytes[5] & 0xff) == 0xe0;
            boolean mappedV4 = true;
            for (int index = 0; index < 10; index++) {
                mappedV4 &= bytes[index] == 0;
            }
            mappedV4 &= (bytes[10] & 0xff) == 0xff && (bytes[11] & 0xff) == 0xff;
            if (mappedV4) {
                int first = bytes[12] & 0xff;
                int second = bytes[13] & 0xff;
                return first == 10 || (first == 192 && second == 168) ||
                        (first == 172 && second >= 16 && second <= 31) ||
                        (first == 100 && second >= 64 && second <= 127);
            }
            return tailscaleV6;
        }
        return false;
    }

    private String transportFor(InetAddress address) {
        byte[] bytes = address.getAddress();
        if (bytes.length == 4 && (bytes[0] & 0xff) == 100
                && (bytes[1] & 0xff) >= 64 && (bytes[1] & 0xff) <= 127) {
            return "tailscale-direct";
        }
        if (bytes.length == 16 && (bytes[0] & 0xff) == 0xfd
                && (bytes[1] & 0xff) == 0x7a) {
            return "tailscale-direct";
        }
        return "lan-direct";
    }

    private String limited(String value, int maximum) {
        String clean = value == null ? "" : value.strip().replace("\u0000", "");
        return clean.length() <= maximum ? clean : clean.substring(0, maximum - 1) + "…";
    }

    private void registerNsd() {
        if (nsdListener != null) {
            return;
        }
        NsdServiceInfo serviceInfo = new NsdServiceInfo();
        serviceInfo.setServiceName("Codex Alert · " + DeviceIdentity.deviceName());
        serviceInfo.setServiceType("_codexalert._tcp.");
        serviceInfo.setPort(PORT);
        serviceInfo.setAttribute("paired", DeviceIdentity.isPaired(this) ? "1" : "0");
        NsdManager manager = getSystemService(NsdManager.class);
        nsdListener = new NsdManager.RegistrationListener() {
            @Override public void onServiceRegistered(NsdServiceInfo info) {}
            @Override public void onRegistrationFailed(NsdServiceInfo info, int errorCode) {}
            @Override public void onServiceUnregistered(NsdServiceInfo info) {}
            @Override public void onUnregistrationFailed(NsdServiceInfo info, int errorCode) {}
        };
        manager.registerService(serviceInfo, NsdManager.PROTOCOL_DNS_SD, nsdListener);
    }

    private void unregisterNsd() {
        if (nsdListener == null) {
            return;
        }
        try {
            getSystemService(NsdManager.class).unregisterService(nsdListener);
        } catch (IllegalArgumentException ignored) {
            // Registration may have failed before cleanup.
        }
        nsdListener = null;
    }

    private String readyDetail() {
        return (DeviceIdentity.isPaired(this) ? "Paired" : "Waiting for pairing")
                + " · LAN/Tailscale port " + PORT;
    }

    static String networkSummary() {
        List<String> addresses = networkAddresses();
        return addresses.isEmpty() ? "No network address available" : String.join("\n", addresses);
    }

    static List<String> networkAddresses() {
        List<String> addresses = new ArrayList<>();
        try {
            for (NetworkInterface network : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!network.isUp() || network.isLoopback()) {
                    continue;
                }
                for (InetAddress address : Collections.list(network.getInetAddresses())) {
                    if (!address.isLoopbackAddress() && address.getAddress().length == 4) {
                        addresses.add(address.getHostAddress());
                    }
                }
            }
        } catch (Exception ignored) {
            return addresses;
        }
        return addresses;
    }

    private void closeServer() {
        if (serverSocket != null) {
            try {
                serverSocket.close();
            } catch (IOException ignored) {
                // Already closed.
            }
            serverSocket = null;
        }
    }

    private String cleanError(Exception exception) {
        String message = exception.getMessage();
        return exception.getClass().getSimpleName() + (message == null ? "" : ": " + limited(message, 180));
    }

    private static final class HttpRequest {
        final String method;
        final String path;
        final Map<String, String> headers;
        final byte[] body;

        HttpRequest(String method, String path, Map<String, String> headers, byte[] body) {
            this.method = method;
            this.path = path;
            this.headers = headers;
            this.body = body;
        }
    }
}
