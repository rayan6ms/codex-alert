package dev.rayan.codexalert;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

final class AlertStore {
    private static final String PREFERENCES = "status";
    private static final String ALERT_HISTORY = "alert_history_v1";
    private static final int ALERT_HISTORY_LIMIT = 5;

    static final class AlertRecord {
        final String eventId;
        final String title;
        final String body;
        final long receivedAt;

        AlertRecord(String eventId, String title, String body, long receivedAt) {
            this.eventId = eventId;
            this.title = title;
            this.body = body;
            this.receivedAt = receivedAt;
        }
    }

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
        long receivedAt = System.currentTimeMillis();
        ArrayDeque<String> ids = new ArrayDeque<>();
        if (!eventId.isEmpty()) {
            ids.add(eventId);
        }
        for (String existing : preferences.getString("recent_event_ids", "").split("\\n")) {
            if (!existing.isEmpty() && !existing.equals(eventId) && ids.size() < 128) {
                ids.add(existing);
            }
        }

        List<AlertRecord> history = readHistory(preferences);
        history.removeIf(alert -> alert.eventId.equals(eventId));
        history.add(0, new AlertRecord(eventId, title, body, receivedAt));
        while (history.size() > ALERT_HISTORY_LIMIT) {
            history.remove(history.size() - 1);
        }

        SharedPreferences.Editor editor = preferences.edit()
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
                .putLong("last_time", receivedAt)
                .putLong("received_count", preferences.getLong("received_count", 0) + 1)
                .remove("last_delivery_error");
        String encodedHistory = encodeHistory(history);
        if (encodedHistory != null) {
            editor.putString(ALERT_HISTORY, encodedHistory);
        }
        editor.apply();
    }

    static synchronized List<AlertRecord> recentAlerts(Context context) {
        return new ArrayList<>(readHistory(
                context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        ));
    }

    private static List<AlertRecord> readHistory(SharedPreferences preferences) {
        List<AlertRecord> history = new ArrayList<>();
        String encoded = preferences.getString(ALERT_HISTORY, "");
        if (encoded != null && !encoded.isEmpty()) {
            try {
                JSONArray array = new JSONArray(encoded);
                for (int index = 0; index < array.length() && history.size() < ALERT_HISTORY_LIMIT;
                     index++) {
                    JSONObject value = array.getJSONObject(index);
                    String eventId = value.optString("event_id", "");
                    String title = value.optString("title", "");
                    String body = value.optString("body", "");
                    long receivedAt = value.optLong("received_at", 0);
                    if (!title.isEmpty() && receivedAt > 0) {
                        history.add(new AlertRecord(eventId, title, body, receivedAt));
                    }
                }
            } catch (JSONException ignored) {
                // Fall through to the legacy last-alert values when possible.
            }
        }
        if (history.isEmpty()) {
            long lastTime = preferences.getLong("last_time", 0);
            if (lastTime > 0) {
                history.add(new AlertRecord(
                        preferences.getString("last_event_id", ""),
                        preferences.getString("last_title", "Codex finished"),
                        preferences.getString("last_body", "Task completed."),
                        lastTime
                ));
            }
        }
        return history;
    }

    private static String encodeHistory(List<AlertRecord> history) {
        JSONArray array = new JSONArray();
        try {
            for (AlertRecord alert : history) {
                array.put(new JSONObject()
                        .put("event_id", alert.eventId)
                        .put("title", alert.title)
                        .put("body", alert.body)
                        .put("received_at", alert.receivedAt));
            }
            return array.toString();
        } catch (JSONException ignored) {
            return null;
        }
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
