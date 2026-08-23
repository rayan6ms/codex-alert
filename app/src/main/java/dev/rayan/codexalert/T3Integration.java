package dev.rayan.codexalert;

import android.app.AppOpsManager;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Process;
import android.provider.Settings;

final class T3Integration {
    static final String PACKAGE_NAME = "com.t3tools.t3code";

    private T3Integration() {}

    static boolean enabled(Context context) {
        return context.getSharedPreferences("features", Context.MODE_PRIVATE)
                .getBoolean("t3_enabled", false);
    }

    static void setEnabled(Context context, boolean enabled) {
        context.getSharedPreferences("features", Context.MODE_PRIVATE)
                .edit().putBoolean("t3_enabled", enabled).apply();
    }

    static boolean autoClearEnabled(Context context) {
        return enabled(context) && context.getSharedPreferences("features", Context.MODE_PRIVATE)
                .getBoolean("t3_auto_clear", false);
    }

    static void setAutoClearEnabled(Context context, boolean enabled) {
        context.getSharedPreferences("features", Context.MODE_PRIVATE)
                .edit().putBoolean("t3_auto_clear", enabled).apply();
    }

    static boolean hasUsageAccess(Context context) {
        AppOpsManager appOps = context.getSystemService(AppOpsManager.class);
        return appOps != null && appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                context.getPackageName()
        ) == AppOpsManager.MODE_ALLOWED;
    }

    static Intent usageAccessSettings(Context context) {
        return new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
                .setData(Uri.parse("package:" + context.getPackageName()));
    }

    static Intent openIntent(Context context, String environmentId, String threadId) {
        if (validRoutePart(environmentId) && validRoutePart(threadId)) {
            Uri uri = Uri.parse(
                    "t3code:///threads/"
                            + Uri.encode(environmentId)
                            + "/"
                            + Uri.encode(threadId)
            );
            Intent deepLink = new Intent(Intent.ACTION_VIEW, uri)
                    .setPackage(PACKAGE_NAME)
                    .addCategory(Intent.CATEGORY_BROWSABLE);
            if (deepLink.resolveActivity(context.getPackageManager()) != null) {
                return deepLink;
            }
        }
        return context.getPackageManager().getLaunchIntentForPackage(PACKAGE_NAME);
    }

    static boolean wasResumed(Context context, long beginTime, long endTime) {
        UsageStatsManager usage = context.getSystemService(UsageStatsManager.class);
        if (usage == null || beginTime >= endTime) {
            return false;
        }
        UsageEvents events = usage.queryEvents(beginTime, endTime);
        UsageEvents.Event event = new UsageEvents.Event();
        while (events != null && events.hasNextEvent()) {
            events.getNextEvent(event);
            if (PACKAGE_NAME.equals(event.getPackageName())
                    && event.getEventType() == UsageEvents.Event.ACTIVITY_RESUMED) {
                return true;
            }
        }
        return false;
    }

    static boolean validRoutePart(String value) {
        return value != null
                && value.length() >= 1
                && value.length() <= 128
                && value.matches("[A-Za-z0-9._:-]+");
    }
}
