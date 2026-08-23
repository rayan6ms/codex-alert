package dev.rayan.codexalert;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.format.DateFormat;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;

import java.util.Date;

@SuppressLint("SetTextI18n")
public final class MainActivity extends Activity {
    private final Handler refreshHandler = new Handler(Looper.getMainLooper());
    private final Runnable periodicRefresh = new Runnable() {
        @Override public void run() {
            refreshStatus();
            refreshHandler.postDelayed(this, 1000);
        }
    };
    private TextView setupStatus;
    private TextView receiverStatus;
    private Button pairingButton;
    private Button forgetButton;
    private Switch t3Switch;
    private Switch autoClearSwitch;
    private Button usageAccessButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        AlertNotifier.ensureChannels(this);
        AlertServerService.start(this);
        setContentView(buildContent());
    }

    @Override
    protected void onResume() {
        super.onResume();
        AlertServerService.start(this);
        refreshHandler.removeCallbacks(periodicRefresh);
        refreshHandler.post(periodicRefresh);
    }

    @Override
    protected void onPause() {
        refreshHandler.removeCallbacks(periodicRefresh);
        super.onPause();
    }

    private View buildContent() {
        int pad = dp(24);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(pad, dp(32), pad, dp(32));
        content.setBackgroundColor(Color.rgb(245, 247, 248));

        TextView eyebrow = text("CODEX ALERT", 12, Color.rgb(13, 148, 136));
        eyebrow.setTypeface(Typeface.DEFAULT_BOLD);
        content.addView(eyebrow);

        TextView title = text("Know when Codex is done.", 28, Color.rgb(17, 24, 39));
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setPadding(0, dp(8), 0, dp(8));
        content.addView(title);
        content.addView(text(
                "Private completion alerts over your LAN or Tailscale—without a cloud relay.",
                16,
                Color.rgb(75, 85, 99)
        ));

        content.addView(sectionTitle("1 · Allow notifications"));
        content.addView(text(
                "Android needs this permission before Codex Alert can show completions.",
                14,
                Color.rgb(75, 85, 99)
        ));
        addWithTopMargin(content, button("Allow notifications", view -> requestNotificationPermission()));

        content.addView(sectionTitle("2 · Pair this phone"));
        content.addView(text(
                "Keep the phone and computer on the same trusted network. Then create a code here and run codex-alert pair on the computer.",
                14,
                Color.rgb(75, 85, 99)
        ));
        setupStatus = statusCard("Preparing secure receiver…");
        addWithTopMargin(content, setupStatus);
        pairingButton = button("Create 8-digit pairing code", view -> beginPairing());
        addWithTopMargin(content, pairingButton);
        forgetButton = button("Forget paired computer", view -> confirmForget());
        addWithTopMargin(content, forgetButton);

        content.addView(sectionTitle("3 · Check delivery"));
        receiverStatus = statusCard("Starting receiver…");
        content.addView(receiverStatus);
        addWithTopMargin(content, button("Send on-device test alert", view -> {
            Intent intent = new Intent(this, AlertServerService.class)
                    .setAction(AlertServerService.ACTION_TEST);
            startForegroundService(intent);
        }));
        addWithTopMargin(content, button("Notification settings", view -> {
            Intent intent = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName());
            startActivity(intent);
        }));
        addWithTopMargin(content, button("Battery/background settings", view ->
                startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        ));

        content.addView(sectionTitle("Optional · T3 Code"));
        content.addView(text(
                "Off by default. Enable it only if you want notification taps to open the exact T3 Code thread.",
                14,
                Color.rgb(75, 85, 99)
        ));
        t3Switch = toggle("Open exact T3 Code thread", T3Integration.enabled(this), checked -> {
            T3Integration.setEnabled(this, checked);
            if (!checked) {
                autoClearSwitch.setChecked(false);
                T3Integration.setAutoClearEnabled(this, false);
            }
            refreshStatus();
        });
        addWithTopMargin(content, t3Switch);
        autoClearSwitch = toggle(
                "Auto-clear when T3 Code opens",
                T3Integration.autoClearEnabled(this),
                checked -> {
                    T3Integration.setAutoClearEnabled(this, checked);
                    refreshStatus();
                }
        );
        addWithTopMargin(content, autoClearSwitch);
        usageAccessButton = button("Grant T3 auto-clear access", view -> {
            try {
                startActivity(T3Integration.usageAccessSettings(this));
            } catch (RuntimeException exception) {
                startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
            }
        });
        addWithTopMargin(content, usageAccessButton);

        TextView privacy = text(
                "Pairing codes expire after 10 minutes and five failed attempts. Each phone generates its own TLS key and delivery token; private keys never leave the device.",
                12,
                Color.rgb(107, 114, 128)
        );
        privacy.setPadding(0, dp(28), 0, 0);
        privacy.setGravity(Gravity.CENTER_HORIZONTAL);
        content.addView(privacy);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(content);
        return scroll;
    }

    private void beginPairing() {
        try {
            String code = DeviceIdentity.beginPairing(this);
            setupStatus.setText(
                    "Pairing code\n" + code.substring(0, 4) + " " + code.substring(4)
                            + "\n\nSecurity code\n" + DeviceIdentity.securityCode()
                            + "\n\nExpires in 10 minutes."
            );
            AlertServerService.start(this);
        } catch (Exception exception) {
            setupStatus.setText("Could not create a device key.\n" + exception.getClass().getSimpleName());
        }
    }

    private void confirmForget() {
        new AlertDialog.Builder(this)
                .setTitle("Forget paired computer?")
                .setMessage("Existing desktop credentials will stop working. You can pair again at any time.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Forget", (dialog, which) -> {
                    DeviceIdentity.forgetDesktop(this);
                    AlertNotifier.clearCompletion(this);
                    refreshStatus();
                })
                .show();
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 100);
        } else {
            startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
        }
    }

    private void refreshStatus() {
        if (setupStatus == null || receiverStatus == null) {
            return;
        }
        boolean paired = DeviceIdentity.isPaired(this);
        pairingButton.setVisibility(paired ? View.GONE : View.VISIBLE);
        forgetButton.setVisibility(paired ? View.VISIBLE : View.GONE);
        if (paired) {
            setupStatus.setText("Paired securely\nSecurity code · " + DeviceIdentity.securityCode());
        } else if (!DeviceIdentity.pairingActive(this)) {
            setupStatus.setText("Not paired yet\n" + AlertServerService.networkSummary());
        }

        NotificationManager manager = getSystemService(NotificationManager.class);
        var channel = manager.getNotificationChannel(AlertNotifier.COMPLETION_CHANNEL_ID);
        boolean notifications = manager.areNotificationsEnabled()
                && (channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE);
        var prefs = getSharedPreferences("status", Context.MODE_PRIVATE);
        String activeEventId = prefs.getString("active_event_id", "");
        StringBuilder value = new StringBuilder()
                .append("Receiver · ").append(prefs.getString("server_state", "starting"))
                .append("\nNotifications · ").append(notifications ? "allowed" : "permission needed")
                .append("\nNetwork · ").append(AlertServerService.networkSummary())
                .append("\nCompletion · ").append(activeEventId.isEmpty() ? "clear" : "visible");
        long lastTime = prefs.getLong("last_time", 0);
        if (lastTime > 0) {
            value.append("\n\nLast received · ")
                    .append(DateFormat.getTimeFormat(this).format(new Date(lastTime)))
                    .append("\n").append(prefs.getString("last_title", "Codex finished"))
                    .append("\n").append(prefs.getString("last_body", "Task completed."));
        }
        receiverStatus.setText(value);

        boolean t3 = T3Integration.enabled(this);
        autoClearSwitch.setEnabled(t3);
        usageAccessButton.setVisibility(
                t3 && autoClearSwitch.isChecked() ? View.VISIBLE : View.GONE
        );
        if (autoClearSwitch.isChecked() && T3Integration.hasUsageAccess(this)) {
            usageAccessButton.setText("T3 auto-clear access granted");
        } else {
            usageAccessButton.setText("Grant T3 auto-clear access");
        }
    }

    private TextView sectionTitle(String value) {
        TextView title = text(value, 18, Color.rgb(17, 24, 39));
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setPadding(0, dp(28), 0, dp(6));
        return title;
    }

    private TextView statusCard(String value) {
        TextView view = text(value, 15, Color.rgb(31, 41, 55));
        view.setPadding(dp(16), dp(16), dp(16), dp(16));
        view.setBackgroundColor(Color.WHITE);
        return view;
    }

    private Button button(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setOnClickListener(listener);
        return button;
    }

    @SuppressWarnings("deprecation")
    private Switch toggle(String label, boolean initial, ToggleListener listener) {
        Switch toggle = new Switch(this);
        toggle.setText(label);
        toggle.setChecked(initial);
        toggle.setOnCheckedChangeListener((button, checked) -> listener.changed(checked));
        return toggle;
    }

    private void addWithTopMargin(LinearLayout content, View view) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.setMargins(0, dp(8), 0, 0);
        content.addView(view, params);
    }

    private TextView text(String value, int sp, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sp);
        view.setTextColor(color);
        view.setLineSpacing(0, 1.12f);
        return view;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private interface ToggleListener {
        void changed(boolean checked);
    }
}
