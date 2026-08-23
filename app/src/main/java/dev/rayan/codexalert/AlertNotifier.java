package dev.rayan.codexalert;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.media.AudioAttributes;
import android.media.RingtoneManager;

final class AlertNotifier {
    static final String COMPLETION_CHANNEL_ID = "codex_completions_v1";
    static final String RECEIVER_CHANNEL_ID = "codex_receiver_v1";
    static final int RECEIVER_NOTIFICATION_ID = 24600;
    static final int COMPLETION_NOTIFICATION_ID = 24601;

    private AlertNotifier() {}

    static void ensureChannels(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);

        NotificationChannel completion = new NotificationChannel(
                COMPLETION_CHANNEL_ID,
                "Codex completions",
                NotificationManager.IMPORTANCE_HIGH
        );
        completion.setDescription("Alerts when a Codex job finishes");
        completion.enableVibration(true);
        completion.enableLights(true);
        completion.setLightColor(Color.rgb(13, 148, 136));
        AudioAttributes audio = new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
                .build();
        completion.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION), audio);
        manager.createNotificationChannel(completion);

        NotificationChannel receiver = new NotificationChannel(
                RECEIVER_CHANNEL_ID,
                "Codex receiver",
                NotificationManager.IMPORTANCE_MIN
        );
        receiver.setDescription("Keeps the private LAN and Tailscale receiver available");
        receiver.setSound(null, null);
        receiver.enableVibration(false);
        receiver.setShowBadge(false);
        manager.createNotificationChannel(receiver);
        manager.deleteNotificationChannel("codex_receiver_hidden_v2");
    }

    static boolean completionNotificationsEnabled(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (!manager.areNotificationsEnabled()) {
            return false;
        }
        NotificationChannel channel = manager.getNotificationChannel(COMPLETION_CHANNEL_ID);
        return channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE;
    }

    static Notification ready(Context context, String detail) {
        return new Notification.Builder(context, RECEIVER_CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_codex_alert)
                .setContentTitle("Codex receiver active")
                .setContentText(detail)
                .setStyle(new Notification.BigTextStyle().bigText(detail))
                .setContentIntent(openApp(context))
                .setCategory(Notification.CATEGORY_SERVICE)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setColor(Color.rgb(13, 148, 136))
                // Android 13 allows foreground-service notifications to be
                // swiped by default. Do not opt back into non-dismissible
                // behavior with FLAG_ONGOING_EVENT.
                .setOngoing(false)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .build();
    }

    static Notification completion(
            Context context,
            String title,
            String body,
            String eventId,
            String environmentId,
            String threadId,
            long completedAt
    ) {
        long now = System.currentTimeMillis();
        long notificationTime = completedAt > 0 && completedAt <= now ? completedAt : now;
        return new Notification.Builder(context, COMPLETION_CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_codex_alert)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setContentIntent(openT3(context, eventId, environmentId, threadId))
                .setCategory(Notification.CATEGORY_REMINDER)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setColor(Color.rgb(13, 148, 136))
                .setDeleteIntent(dismissed(context, eventId))
                .setOngoing(false)
                .setAutoCancel(true)
                .setOnlyAlertOnce(false)
                .setShowWhen(true)
                .setWhen(notificationTime)
                .build();
    }

    static void postCompletion(
            Context context,
            String title,
            String body,
            String eventId,
            String environmentId,
            String threadId,
            long completedAt
    ) {
        context.getSystemService(NotificationManager.class).notify(
                COMPLETION_NOTIFICATION_ID,
                completion(context, title, body, eventId, environmentId, threadId, completedAt)
        );
    }

    static void clearCompletion(Context context) {
        context.getSystemService(NotificationManager.class).cancel(COMPLETION_NOTIFICATION_ID);
    }

    private static PendingIntent openApp(Context context) {
        Intent intent = new Intent(context, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(
                context,
                0,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
    }

    private static PendingIntent openT3(
            Context context,
            String eventId,
            String environmentId,
            String threadId
    ) {
        Intent intent = new Intent(context, OpenT3Activity.class)
                .putExtra("event_id", eventId)
                .putExtra("environment_id", environmentId)
                .putExtra("thread_id", threadId);
        return PendingIntent.getActivity(
                context,
                2,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
    }

    private static PendingIntent dismissed(Context context, String eventId) {
        Intent intent = new Intent(context, AlertDismissReceiver.class)
                .putExtra("event_id", eventId);
        return PendingIntent.getBroadcast(
                context,
                1,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
    }
}
