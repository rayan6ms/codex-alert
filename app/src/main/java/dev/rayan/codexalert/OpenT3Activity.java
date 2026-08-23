package dev.rayan.codexalert;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** Clears the tapped completion before handing its exact route to T3 Code. */
public final class OpenT3Activity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Intent source = getIntent();
        String eventId = value(source, "event_id");
        String environmentId = value(source, "environment_id");
        String threadId = value(source, "thread_id");

        if (AlertStore.clearActive(this, eventId, "notification-opened")) {
            AlertNotifier.clearCompletion(this);
        }

        Intent target = T3Integration.enabled(this)
                ? T3Integration.openIntent(this, environmentId, threadId)
                : null;
        if (target == null) {
            if (T3Integration.enabled(this)) {
                AlertStore.integrationError(this, "T3 Code is not installed or no exact thread was provided");
            } else {
                AlertStore.integrationError(this, "");
            }
            target = new Intent(this, MainActivity.class)
                    .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        } else {
            AlertStore.integrationError(this, "");
        }
        startActivity(target);
        finish();
    }

    private static String value(Intent intent, String key) {
        String value = intent == null ? "" : intent.getStringExtra(key);
        return value == null ? "" : value;
    }
}
