package dev.rayan.codexalert;

import android.content.Context;

import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

final class AlertStore {
    private static final String PREFERENCES = "status";

    private AlertStore() {}

    static synchronized boolean alreadyReceived(Context context, String eventId) {
        if (eventId.isEmpty()) {
            return false;
        }
        String stored = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .getString("recent_event_ids", "");
        Set<String> ids = new HashSet<>(Arrays.asList(stored.split("\\n")));
        return ids.contains(eventId);
    }

    static synchronized void recordDuplicate(Context context) {
        var preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        preferences.edit()
                .putLong("duplicate_count", preferences.getLong("duplicate_count", 0) + 1)
                .apply();
    }

    static synchronized void recordDelivery(
            Context context,
            String eventId,
            String title,
            String body,
            String transport,
            String environmentId,
            String threadId,
            long completedAt,
            long sentAt
    ) {
        var preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        ArrayDeque<String> ids = new ArrayDeque<>();
        if (!eventId.isEmpty()) {
            ids.add(eventId);
        }
        for (String existing : preferences.getString("recent_event_ids", "").split("\\n")) {
            if (!existing.isEmpty() && !existing.equals(eventId) && ids.size() < 128) {
                ids.add(existing);
            }
        }

        preferences.edit()
                .putString("recent_event_ids", String.join("\n", ids))
                .putString("last_title", title)
                .putString("last_body", body)
                .putString("last_event_id", eventId)
                .putString("active_event_id", eventId)
                .putString("active_environment_id", environmentId)
                .putString("active_thread_id", threadId)
                .putLong("active_since_time", System.currentTimeMillis())
                .putString("last_transport", transport)
                .putLong("last_completed_time", completedAt)
                .putLong("last_sent_time", sentAt)
                .putLong("last_time", System.currentTimeMillis())
                .putLong("received_count", preferences.getLong("received_count", 0) + 1)
                .remove("last_delivery_error")
                .apply();
    }

    static synchronized String activeEventId(Context context) {
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .getString("active_event_id", "");
    }

    static synchronized long activeSince(Context context) {
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .getLong("active_since_time", 0);
    }

    static synchronized boolean clearActive(
            Context context,
            String expectedEventId,
            String reason
    ) {
        var preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        String active = preferences.getString("active_event_id", "");
        if (!expectedEventId.isEmpty() && !expectedEventId.equals(active)) {
            return false;
        }
        if (active.isEmpty()) {
            return false;
        }
        preferences.edit()
                .remove("active_event_id")
                .remove("active_environment_id")
                .remove("active_thread_id")
                .remove("active_since_time")
                .putString("last_clear_reason", reason)
                .putLong("last_clear_time", System.currentTimeMillis())
                .apply();
        return true;
    }

    static void serverState(Context context, String state, String error) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putString("server_state", state)
                .putString("server_error", error)
                .putLong("server_state_time", System.currentTimeMillis())
                .apply();
    }

    static void deliveryError(Context context, String error) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putString("last_delivery_error", error)
                .apply();
    }

    static void pairingError(Context context, String error) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putString("last_pairing_error", error)
                .putLong("last_pairing_error_time", System.currentTimeMillis())
                .apply();
    }

    static void pairingSucceeded(Context context) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .remove("last_pairing_error")
                .putLong("last_pairing_time", System.currentTimeMillis())
                .apply();
    }

    static void usageWatchState(Context context, String state) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putString("t3_watch_state", state)
                .apply();
    }

    static void integrationError(Context context, String error) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putString("t3_integration_error", error)
                .apply();
    }
}
