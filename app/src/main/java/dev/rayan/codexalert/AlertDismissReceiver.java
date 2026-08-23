package dev.rayan.codexalert;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Records a user swipe so a later remote clear is harmless and idempotent. */
public final class AlertDismissReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String eventId = intent == null ? "" : intent.getStringExtra("event_id");
        AlertStore.clearActive(context, eventId == null ? "" : eventId, "phone-dismissed");
    }
}
