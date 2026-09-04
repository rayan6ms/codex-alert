package dev.rayan.codexalert;

import android.Manifest;
import android.annotation.SuppressLint;
import android.animation.ObjectAnimator;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.text.format.DateFormat;
import android.view.Gravity;
import android.view.View;
import android.view.animation.LinearInterpolator;
import android.widget.Button;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;

import java.util.Date;
import java.util.List;

@SuppressLint("SetTextI18n")
public final class MainActivity extends Activity {
    private int INK;
    private int MUTED;
    private int TEAL;
    private int TEAL_DARK;
    private int TEAL_PRESSED;
    private int TEAL_PALE;
    private int GREEN;
    private int GREEN_PALE;
    private int AMBER;
    private int AMBER_PALE;
    private int RED;
    private int RED_PALE;
    private int RED_PRESSED;
    private int BACKGROUND;
    private int SURFACE;
    private int SURFACE_MUTED;
    private int DIVIDER;

    private final Handler refreshHandler = new Handler(Looper.getMainLooper());
    private final Runnable periodicRefresh = new Runnable() {
        @Override public void run() {
            refreshStatus();
            refreshHandler.postDelayed(this, 1000);
        }
    };
    private final Runnable refreshCheck = new Runnable() {
        @Override public void run() {
            if (!refreshing) return;
            long elapsed = SystemClock.elapsedRealtime() - refreshStartedAt;
            if (AlertServerService.isListening() || elapsed >= 4_000) {
                long minimumDisplay = 350 - elapsed;
                if (minimumDisplay > 0) {
                    refreshHandler.postDelayed(this, minimumDisplay);
                } else {
                    finishRefresh();
                }
                return;
            }
            refreshHandler.postDelayed(this, 200);
        }
    };

    private int setupStep;
    private boolean dashboard;
    private boolean lastNotifications;
    private boolean darkMode;
    private boolean refreshing;
    private long refreshStartedAt;
    private ObjectAnimator refreshAnimator;
    private TextView pairingCard;
    private TextView heroPill;
    private TextView heroTitle;
    private TextView heroDetail;
    private TextView receiverStatus;
    private TextView lastAlert;
    private TextView alertPosition;
    private ImageButton refreshButton;
    private ImageButton olderAlertButton;
    private ImageButton newerAlertButton;
    private Button nextButton;
    private Switch t3Switch;
    private Switch autoClearSwitch;
    private Button usageAccessButton;
    private int alertHistoryIndex;
    private String historyNewestEventId = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        darkMode = getSharedPreferences("ui", Context.MODE_PRIVATE)
                .getBoolean("dark_mode", false);
        setTheme(darkMode ? R.style.Theme_CodexAlert_Dark : R.style.Theme_CodexAlert);
        super.onCreate(savedInstanceState);
        applyPalette();
        applySystemBars();
        AlertNotifier.ensureChannels(this);
        AlertServerService.start(this);
        boolean paired = DeviceIdentity.isPaired(this);
        boolean notifications = notificationsAllowed();
        var ui = getSharedPreferences("ui", Context.MODE_PRIVATE);
        dashboard = ui.getBoolean("setup_complete", false) || (paired && notifications);
        if (dashboard) {
            ui.edit().putBoolean("setup_complete", true).apply();
        }
        setupStep = notifications ? (paired ? 2 : 1) : 0;
        render();
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
        cancelRefresh();
        super.onPause();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == 100) {
            refreshStatus();
        }
    }

    @SuppressWarnings("deprecation")
    private void render() {
        resetReferences();
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout content = column();
        int horizontalPadding = dp(22);
        int topPadding = dp(28);
        int bottomPadding = dp(36);
        content.setPadding(horizontalPadding, topPadding, horizontalPadding, bottomPadding);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            content.setPadding(
                    horizontalPadding,
                    topPadding + insets.getSystemWindowInsetTop(),
                    horizontalPadding,
                    bottomPadding + insets.getSystemWindowInsetBottom()
            );
            return insets;
        });
        content.setBackgroundColor(BACKGROUND);
        addBrand(content);
        if (dashboard) {
            buildDashboard(content);
        } else {
            buildSetup(content);
        }
        scroll.addView(content);
        setContentView(scroll);
        lastNotifications = notificationsAllowed();
        updateVisibleStatus();
    }

    private void resetReferences() {
        if (refreshAnimator != null) {
            refreshAnimator.cancel();
            refreshAnimator = null;
        }
        pairingCard = null;
        heroPill = null;
        heroTitle = null;
        heroDetail = null;
        receiverStatus = null;
        lastAlert = null;
        alertPosition = null;
        refreshButton = null;
        olderAlertButton = null;
        newerAlertButton = null;
        nextButton = null;
        t3Switch = null;
        autoClearSwitch = null;
        usageAccessButton = null;
    }

    private void addBrand(LinearLayout content) {
        LinearLayout brand = new LinearLayout(this);
        brand.setGravity(Gravity.CENTER_VERTICAL);
        TextView mark = text("✓", 18, Color.WHITE);
        mark.setTypeface(Typeface.DEFAULT_BOLD);
        mark.setGravity(Gravity.CENTER);
        mark.setBackground(rounded(TEAL, 12));
        brand.addView(mark, new LinearLayout.LayoutParams(dp(36), dp(36)));
        TextView name = text("Codex Alert", 17, INK);
        name.setTypeface(Typeface.DEFAULT_BOLD);
        LinearLayout.LayoutParams params = wrap();
        params.setMargins(dp(11), 0, 0, 0);
        brand.addView(name, params);
        brand.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1));
        ImageButton themeButton = iconButton(
                darkMode ? R.drawable.ic_light_mode : R.drawable.ic_dark_mode,
                darkMode ? "Use light theme" : "Use dark theme",
                view -> toggleTheme()
        );
        brand.addView(themeButton, new LinearLayout.LayoutParams(dp(48), dp(48)));
        content.addView(brand);
    }

    private void buildSetup(LinearLayout content) {
        TextView label = text("SETUP  ·  " + (setupStep + 1) + " OF 3", 12, TEAL);
        label.setTypeface(Typeface.DEFAULT_BOLD);
        addTop(content, label, 30);
        addProgress(content);
        if (setupStep == 0) {
            buildNotificationStep(content);
        } else if (setupStep == 1) {
            buildPairingStep(content);
        } else {
            buildFinishStep(content);
        }
        addSetupNavigation(content);
    }

    private void addProgress(LinearLayout content) {
        LinearLayout row = new LinearLayout(this);
        for (int index = 0; index < 3; index++) {
            View segment = new View(this);
            segment.setBackground(rounded(index <= setupStep ? TEAL : DIVIDER, 3));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(5), 1);
            if (index > 0) params.setMargins(dp(6), 0, 0, 0);
            row.addView(segment, params);
        }
        addTop(content, row, 10);
    }

    private void buildNotificationStep(LinearLayout content) {
        addPageHeading(content, "Let alerts reach you",
                "Allow completion notifications so you know immediately when Codex has finished.");
        LinearLayout card = card(SURFACE);
        card.addView(iconCircle("1", TEAL_PALE, TEAL));
        TextView title = text("Notifications", 18, INK);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        addTop(card, title, 16);
        boolean allowed = notificationsAllowed();
        card.addView(text(allowed
                ? "Allowed. Codex Alert can show completion alerts."
                : "Android is currently blocking completion alerts.", 15, allowed ? GREEN : MUTED));
        addTop(card, primaryButton(allowed ? "Notification settings" : "Allow notifications",
                view -> requestNotificationPermission()), 20);
        addTop(content, card, 26);
        addTop(content, text(
                "Only the alert title and task summary appear. Codex Alert has no cloud relay.",
                13, MUTED), 18);
    }

    private void buildPairingStep(LinearLayout content) {
        addPageHeading(content, "Connect this phone",
                "Pair once with your computer over the same trusted Wi-Fi or Tailscale network.");
        LinearLayout pairing = card(SURFACE);
        pairingCard = text("", 15, MUTED);
        pairing.addView(pairingCard);
        if (!DeviceIdentity.isPaired(this)) {
            boolean active = DeviceIdentity.pairingActive(this);
            addTop(pairing, primaryButton(active ? "Create a new code" : "Create pairing code",
                    view -> beginPairing()), 20);
        }
        addTop(content, pairing, 26);

        LinearLayout command = card(SURFACE_MUTED);
        TextView commandLabel = text("ON YOUR COMPUTER", 11, MUTED);
        commandLabel.setTypeface(Typeface.DEFAULT_BOLD);
        command.addView(commandLabel);
        TextView commandText = text("codex-alert pair", 17, INK);
        commandText.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        addTop(command, commandText, 8);
        command.addView(text(
                "Enter the code above, then confirm that both security codes match.", 14, MUTED));
        addTop(content, command, 12);
    }

    private void buildFinishStep(LinearLayout content) {
        addPageHeading(content, "You’re ready",
                "This phone is securely paired and listening for Codex completions.");
        LinearLayout success = card(GREEN_PALE);
        success.addView(iconCircle("✓", Color.WHITE, GREEN));
        TextView title = text("Everything is working", 21, GREEN);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        addTop(success, title, 16);
        success.addView(text("Receiver active · Notifications allowed · Computer paired", 14, INK));
        addTop(content, success, 26);
        addTop(content, secondaryButton("Send a test alert on this phone", view -> sendLocalTest()), 14);
        content.addView(text("You can change optional behavior later from the app dashboard.", 13, MUTED));
    }

    private void addSetupNavigation(LinearLayout content) {
        LinearLayout navigation = new LinearLayout(this);
        navigation.setGravity(Gravity.CENTER_VERTICAL);
        if (setupStep > 0) {
            Button back = quietButton("Back", view -> {
                setupStep--;
                render();
            });
            navigation.addView(back, new LinearLayout.LayoutParams(0, dp(52), 1));
        } else {
            navigation.addView(new View(this), new LinearLayout.LayoutParams(0, dp(52), 1));
        }
        nextButton = primaryButton(setupStep == 2 ? "Finish setup" : "Continue", view -> {
            if (setupStep == 2) {
                getSharedPreferences("ui", Context.MODE_PRIVATE).edit()
                        .putBoolean("setup_complete", true).apply();
                dashboard = true;
            } else {
                setupStep++;
            }
            render();
        });
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(52), 1.45f);
        params.setMargins(dp(10), 0, 0, 0);
        navigation.addView(nextButton, params);
        addTop(content, navigation, 30);
    }

    private void buildDashboard(LinearLayout content) {
        LinearLayout hero = card(SURFACE);
        heroPill = pill("CHECKING", AMBER_PALE, AMBER);
        LinearLayout heroHeader = new LinearLayout(this);
        heroHeader.setGravity(Gravity.CENTER_VERTICAL);
        heroHeader.addView(heroPill);
        View spacer = new View(this);
        heroHeader.addView(spacer, new LinearLayout.LayoutParams(0, 1, 1));
        refreshButton = createRefreshButton();
        heroHeader.addView(refreshButton);
        hero.addView(heroHeader);
        heroTitle = text("Checking your receiver…", 26, INK);
        heroTitle.setTypeface(Typeface.DEFAULT_BOLD);
        addTop(hero, heroTitle, 18);
        heroDetail = text("Confirming notification, pairing, and network status.", 15, MUTED);
        hero.addView(heroDetail);
        addTop(content, hero, 30);

        addTop(content, sectionTitle("Status"), 28);
        receiverStatus = text("", 15, INK);
        receiverStatus.setPadding(dp(18), dp(17), dp(18), dp(17));
        receiverStatus.setBackground(rounded(SURFACE, 16));
        content.addView(receiverStatus);
        lastAlert = text("", 14, MUTED);
        LinearLayout alertCard = card(SURFACE);
        LinearLayout historyNavigation = new LinearLayout(this);
        historyNavigation.setGravity(Gravity.CENTER_VERTICAL);
        alertPosition = text("", 13, MUTED);
        alertPosition.setTypeface(Typeface.DEFAULT_BOLD);
        historyNavigation.addView(
                alertPosition,
                new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1)
        );
        olderAlertButton = iconButton(
                R.drawable.ic_chevron_left,
                "Show older notification",
                view -> showOlderAlert()
        );
        newerAlertButton = iconButton(
                R.drawable.ic_chevron_right,
                "Show newer notification",
                view -> showNewerAlert()
        );
        LinearLayout.LayoutParams olderParams = new LinearLayout.LayoutParams(dp(48), dp(48));
        olderParams.setMargins(0, 0, dp(8), 0);
        historyNavigation.addView(olderAlertButton, olderParams);
        historyNavigation.addView(newerAlertButton, new LinearLayout.LayoutParams(dp(48), dp(48)));
        alertCard.addView(historyNavigation);
        addTop(alertCard, lastAlert, 12);
        addTop(content, alertCard, 10);

        LinearLayout actions = new LinearLayout(this);
        actions.addView(primaryButton("Send test alert", view -> sendLocalTest()),
                new LinearLayout.LayoutParams(0, dp(52), 1));
        Button notificationSettings = secondaryButton("Notifications", view -> openNotificationSettings());
        LinearLayout.LayoutParams settingsParams = new LinearLayout.LayoutParams(0, dp(52), 1);
        settingsParams.setMargins(dp(10), 0, 0, 0);
        actions.addView(notificationSettings, settingsParams);
        addTop(content, actions, 12);
        if (!notificationsAllowed()) {
            addTop(content, primaryButton("Allow completion notifications",
                    view -> requestNotificationPermission()), 10);
        }

        addTop(content, sectionTitle("Optional · T3 Code"), 30);
        content.addView(text(
                "Open the exact T3 Code thread when you tap an alert. This stays off unless you enable it.",
                14, MUTED));
        LinearLayout preferences = card(SURFACE);
        t3Switch = toggle("Open exact T3 Code thread", T3Integration.enabled(this), checked -> {
            T3Integration.setEnabled(this, checked);
            if (!checked && autoClearSwitch != null) {
                autoClearSwitch.setChecked(false);
                T3Integration.setAutoClearEnabled(this, false);
            }
            updateT3Controls();
        });
        preferences.addView(t3Switch);
        View line = new View(this);
        line.setBackgroundColor(DIVIDER);
        LinearLayout.LayoutParams lineParams = match(dp(1));
        lineParams.setMargins(0, dp(14), 0, dp(14));
        preferences.addView(line, lineParams);
        autoClearSwitch = toggle("Clear alert when T3 Code opens",
                T3Integration.autoClearEnabled(this), checked -> {
                    T3Integration.setAutoClearEnabled(this, checked);
                    updateT3Controls();
                });
        preferences.addView(autoClearSwitch);
        usageAccessButton = secondaryButton("Grant auto-clear access", view -> openUsageAccess());
        addTop(preferences, usageAccessButton, 14);
        addTop(content, preferences, 12);

        addTop(content, sectionTitle("Device & security"), 30);
        LinearLayout security = card(SURFACE);
        TextView securityLabel = text("SECURITY CODE", 11, MUTED);
        securityLabel.setTypeface(Typeface.DEFAULT_BOLD);
        security.addView(securityLabel);
        TextView code = text(DeviceIdentity.securityCode(this), 16, INK);
        code.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        addTop(security, code, 6);
        addTop(security, quietButton("Battery & background settings", view ->
                startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))), 16);
        addTop(security, destructiveButton("Forget paired computer", view -> confirmForget()), 6);
        addTop(content, security, 12);
        TextView privacy = text(
                "Private LAN/Tailscale delivery · No cloud relay · Keys stay on this device",
                12, MUTED);
        privacy.setGravity(Gravity.CENTER_HORIZONTAL);
        addTop(content, privacy, 24);
    }

    private ImageButton createRefreshButton() {
        ImageButton button = iconButton(
                R.drawable.ic_refresh,
                "Refresh connection status",
                view -> startRefresh()
        );
        button.setLayoutParams(new LinearLayout.LayoutParams(dp(48), dp(48)));
        return button;
    }

    private ImageButton iconButton(
            int drawable,
            String contentDescription,
            View.OnClickListener listener
    ) {
        ImageButton button = new ImageButton(this);
        button.setImageResource(drawable);
        button.setImageTintList(ColorStateList.valueOf(TEAL_DARK));
        button.setBackground(interactiveRounded(TEAL_PALE, SURFACE_MUTED, 24));
        button.setPadding(dp(12), dp(12), dp(12), dp(12));
        button.setContentDescription(contentDescription);
        button.setTooltipText(contentDescription);
        button.setOnClickListener(listener);
        return button;
    }

    private void toggleTheme() {
        darkMode = !darkMode;
        getSharedPreferences("ui", Context.MODE_PRIVATE).edit()
                .putBoolean("dark_mode", darkMode)
                .apply();
        recreate();
    }

    private void showOlderAlert() {
        int count = AlertStore.recentAlerts(this).size();
        if (alertHistoryIndex < count - 1) {
            alertHistoryIndex++;
            updateVisibleStatus();
        }
    }

    private void showNewerAlert() {
        if (alertHistoryIndex > 0) {
            alertHistoryIndex--;
            updateVisibleStatus();
        }
    }

    private void startRefresh() {
        if (refreshing) return;
        refreshing = true;
        refreshStartedAt = SystemClock.elapsedRealtime();
        if (refreshButton != null) {
            refreshButton.setEnabled(false);
            refreshButton.setAlpha(0.45f);
            refreshButton.setContentDescription("Refreshing connection status");
            refreshAnimator = ObjectAnimator.ofFloat(refreshButton, View.ROTATION, 0f, 360f);
            refreshAnimator.setDuration(800);
            refreshAnimator.setInterpolator(new LinearInterpolator());
            refreshAnimator.setRepeatCount(ObjectAnimator.INFINITE);
            refreshAnimator.start();
        }
        try {
            AlertServerService.start(this);
        } catch (RuntimeException ignored) {
            // The bounded check below will present OFFLINE with the retry action.
        }
        updateVisibleStatus();
        refreshHandler.removeCallbacks(refreshCheck);
        refreshHandler.post(refreshCheck);
    }

    private void finishRefresh() {
        if (!refreshing) return;
        refreshing = false;
        refreshHandler.removeCallbacks(refreshCheck);
        if (refreshAnimator != null) {
            refreshAnimator.cancel();
            refreshAnimator = null;
        }
        if (refreshButton != null) {
            refreshButton.setRotation(0f);
            refreshButton.setEnabled(true);
            refreshButton.setAlpha(1f);
            refreshButton.setContentDescription("Refresh connection status");
        }
        updateVisibleStatus();
    }

    private void cancelRefresh() {
        if (!refreshing) return;
        refreshing = false;
        refreshHandler.removeCallbacks(refreshCheck);
        if (refreshAnimator != null) {
            refreshAnimator.cancel();
            refreshAnimator = null;
        }
    }

    private void addPageHeading(LinearLayout content, String title, String detail) {
        TextView heading = text(title, 29, INK);
        heading.setTypeface(Typeface.DEFAULT_BOLD);
        addTop(content, heading, 24);
        content.addView(text(detail, 16, MUTED));
    }

    private void beginPairing() {
        try {
            DeviceIdentity.beginPairing(this);
            AlertServerService.start(this);
            render();
        } catch (Exception exception) {
            pairingCard.setText("Could not create a secure device key.\n"
                    + exception.getClass().getSimpleName());
            pairingCard.setTextColor(RED);
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
                    getSharedPreferences("ui", Context.MODE_PRIVATE).edit()
                            .putBoolean("setup_complete", false).apply();
                    dashboard = false;
                    setupStep = notificationsAllowed() ? 1 : 0;
                    render();
                })
                .show();
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 100);
        } else {
            openNotificationSettings();
        }
    }

    private void openNotificationSettings() {
        startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
    }

    private void openUsageAccess() {
        try {
            startActivity(T3Integration.usageAccessSettings(this));
        } catch (RuntimeException exception) {
            startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
        }
    }

    private void sendLocalTest() {
        Intent intent = new Intent(this, AlertServerService.class)
                .setAction(AlertServerService.ACTION_TEST);
        startForegroundService(intent);
    }

    private void refreshStatus() {
        boolean paired = DeviceIdentity.isPaired(this);
        boolean notifications = notificationsAllowed();
        if (dashboard && !paired) {
            dashboard = false;
            setupStep = notifications ? 1 : 0;
            getSharedPreferences("ui", Context.MODE_PRIVATE).edit()
                    .putBoolean("setup_complete", false).apply();
            render();
            return;
        }
        if (!dashboard) {
            if (setupStep == 0 && notifications) {
                setupStep = paired ? 2 : 1;
                render();
                return;
            }
            if (setupStep == 1 && paired) {
                setupStep = 2;
                render();
                return;
            }
            if (setupStep == 2 && !paired) {
                setupStep = 1;
                render();
                return;
            }
        } else if (!refreshing && notifications != lastNotifications) {
            render();
            return;
        }
        lastNotifications = notifications;
        updateVisibleStatus();
    }

    private void updateVisibleStatus() {
        boolean paired = DeviceIdentity.isPaired(this);
        boolean notifications = notificationsAllowed();
        boolean listening = AlertServerService.isListening();
        if (nextButton != null) {
            boolean enabled = setupStep == 0 ? notifications
                    : setupStep == 1 ? paired : paired && notifications;
            nextButton.setEnabled(enabled);
            nextButton.setAlpha(enabled ? 1f : 0.45f);
        }
        if (pairingCard != null) updatePairingCard(paired);
        if (heroTitle != null) {
            boolean ready = paired && notifications && listening;
            if (refreshing) {
                stylePill(heroPill, "●  CHECKING", AMBER_PALE, AMBER);
                heroTitle.setText("Checking the receiver…");
                heroDetail.setText("Refreshing the secure connection status.");
                heroPill.setContentDescription("Status: checking");
            } else if (ready) {
                stylePill(heroPill, "●  READY", GREEN_PALE, GREEN);
                heroTitle.setText("Codex Alert is working");
                heroDetail.setText("Your phone is connected and ready for completion alerts.");
                heroPill.setContentDescription("Status: ready");
            } else if (!paired) {
                stylePill(heroPill, "●  OFFLINE", RED_PALE, RED);
                heroTitle.setText("Computer not paired");
                heroDetail.setText("Pair this phone with your computer to receive completions.");
                heroPill.setContentDescription("Status: offline");
            } else if (!notifications) {
                stylePill(heroPill, "●  OFFLINE", RED_PALE, RED);
                heroTitle.setText("Notifications are blocked");
                heroDetail.setText("Allow notifications to receive Codex completions on this phone.");
                heroPill.setContentDescription("Status: offline");
            } else {
                stylePill(heroPill, "●  OFFLINE", RED_PALE, RED);
                heroTitle.setText("Receiver needs attention");
                heroDetail.setText("The secure receiver is not listening. Tap refresh to try again.");
                heroPill.setContentDescription("Status: offline");
            }
        }
        if (receiverStatus != null) {
            String serverLine = listening ? "✓  Receiver active" : "!  Receiver offline";
            receiverStatus.setText(serverLine
                    + "\n" + (notifications ? "✓  Notifications allowed" : "!  Notifications blocked")
                    + "\n" + (paired ? "✓  Computer paired securely" : "!  Computer not paired")
                    + "\n\nNetwork  ·  " + AlertServerService.networkSummary().replace("\n", "  ·  "));
            receiverStatus.setTextColor(
                    paired && notifications && listening ? INK : RED);
        }
        if (lastAlert != null) {
            updateAlertHistory();
        }
        if (refreshButton != null) {
            refreshButton.setEnabled(!refreshing);
            refreshButton.setAlpha(refreshing ? 0.45f : 1f);
        }
        updateT3Controls();
    }

    private void updateAlertHistory() {
        List<AlertStore.AlertRecord> history = AlertStore.recentAlerts(this);
        if (history.isEmpty()) {
            alertHistoryIndex = 0;
            historyNewestEventId = "";
            lastAlert.setText("LATEST ALERT\nNo completion received yet");
            updateHistoryButton(olderAlertButton, false);
            updateHistoryButton(newerAlertButton, false);
            if (alertPosition != null) alertPosition.setText("0 of 5 cached");
            return;
        }

        String newestEventId = history.get(0).eventId;
        if (!newestEventId.equals(historyNewestEventId)) {
            alertHistoryIndex = 0;
            historyNewestEventId = newestEventId;
        }
        alertHistoryIndex = Math.max(0, Math.min(alertHistoryIndex, history.size() - 1));
        AlertStore.AlertRecord alert = history.get(alertHistoryIndex);
        String label = alertHistoryIndex == 0 ? "LATEST ALERT" : "PAST ALERT";
        lastAlert.setText(label + "  ·  "
                + DateFormat.getTimeFormat(this).format(new Date(alert.receivedAt))
                + "\n" + alert.title + "\n" + alert.body);
        if (alertPosition != null) {
            alertPosition.setText((alertHistoryIndex + 1) + " of " + history.size());
        }
        updateHistoryButton(olderAlertButton, alertHistoryIndex < history.size() - 1);
        updateHistoryButton(newerAlertButton, alertHistoryIndex > 0);
    }

    private void updateHistoryButton(ImageButton button, boolean enabled) {
        if (button == null) return;
        button.setEnabled(enabled);
        button.setAlpha(enabled ? 1f : 0.38f);
    }

    private void updatePairingCard(boolean paired) {
        if (paired) {
            pairingCard.setText("✓  Paired securely\n\nSECURITY CODE\n"
                    + DeviceIdentity.securityCode(this));
            pairingCard.setTextColor(GREEN);
            pairingCard.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            return;
        }
        String code = DeviceIdentity.currentPairingCode(this);
        if (!code.isEmpty()) {
            pairingCard.setText("PAIRING CODE\n" + code.substring(0, 4) + "  " + code.substring(4)
                    + "\n\nSECURITY CODE\n" + DeviceIdentity.securityCode(this)
                    + "\n\nExpires after 10 minutes. Keep this screen open while pairing.");
            pairingCard.setTextColor(INK);
            pairingCard.setTextSize(18);
            pairingCard.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        } else {
            pairingCard.setText("Not paired yet\n\nCreate a one-time code, then enter it on your computer."
                    + "\n\nNetwork\n" + AlertServerService.networkSummary());
            pairingCard.setTextColor(MUTED);
            pairingCard.setTextSize(15);
            pairingCard.setTypeface(Typeface.DEFAULT, Typeface.NORMAL);
        }
    }

    private void updateT3Controls() {
        if (t3Switch == null || autoClearSwitch == null || usageAccessButton == null) return;
        boolean t3 = T3Integration.enabled(this);
        autoClearSwitch.setEnabled(t3);
        autoClearSwitch.setAlpha(t3 ? 1f : 0.45f);
        boolean showUsage = t3 && autoClearSwitch.isChecked();
        usageAccessButton.setVisibility(showUsage ? View.VISIBLE : View.GONE);
        usageAccessButton.setText(showUsage && T3Integration.hasUsageAccess(this)
                ? "Auto-clear access granted" : "Grant auto-clear access");
    }

    private boolean notificationsAllowed() {
        return AlertNotifier.completionNotificationsEnabled(this);
    }

    private TextView sectionTitle(String value) {
        TextView view = text(value, 18, INK);
        view.setTypeface(Typeface.DEFAULT_BOLD);
        view.setPadding(0, 0, 0, dp(10));
        return view;
    }

    private LinearLayout column() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    private LinearLayout card(int color) {
        LinearLayout layout = column();
        layout.setPadding(dp(18), dp(18), dp(18), dp(18));
        layout.setBackground(rounded(color, 18));
        layout.setElevation(dp(1));
        return layout;
    }

    private TextView iconCircle(String value, int background, int foreground) {
        TextView icon = text(value, 19, foreground);
        icon.setTypeface(Typeface.DEFAULT_BOLD);
        icon.setGravity(Gravity.CENTER);
        icon.setBackground(rounded(background, 22));
        icon.setLayoutParams(new LinearLayout.LayoutParams(dp(44), dp(44)));
        return icon;
    }

    private TextView pill(String value, int background, int foreground) {
        TextView view = text(value, 11, foreground);
        view.setTypeface(Typeface.DEFAULT_BOLD);
        view.setGravity(Gravity.CENTER);
        view.setPadding(dp(11), dp(6), dp(11), dp(6));
        view.setBackground(rounded(background, 20));
        view.setLayoutParams(wrap());
        return view;
    }

    private void stylePill(TextView view, String value, int background, int foreground) {
        view.setText(value);
        view.setTextColor(foreground);
        view.setBackground(rounded(background, 20));
    }

    private Button primaryButton(String label, View.OnClickListener listener) {
        Button button = baseButton(label, listener);
        button.setTextColor(Color.WHITE);
        button.setTypeface(Typeface.DEFAULT_BOLD);
        button.setBackgroundTintList(interactionColors(TEAL, TEAL_PRESSED));
        return button;
    }

    private Button secondaryButton(String label, View.OnClickListener listener) {
        Button button = baseButton(label, listener);
        button.setTextColor(TEAL_DARK);
        button.setTypeface(Typeface.DEFAULT_BOLD);
        button.setBackgroundTintList(interactionColors(SURFACE, TEAL_PALE));
        return button;
    }

    private Button quietButton(String label, View.OnClickListener listener) {
        Button button = baseButton(label, listener);
        button.setTextColor(MUTED);
        button.setBackgroundTintList(interactionColors(Color.TRANSPARENT, TEAL_PALE));
        return button;
    }

    private Button destructiveButton(String label, View.OnClickListener listener) {
        Button button = baseButton(label, listener);
        button.setTextColor(RED);
        button.setBackgroundTintList(interactionColors(RED_PALE, RED_PRESSED));
        return button;
    }

    private Button baseButton(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(14);
        button.setAllCaps(false);
        button.setGravity(Gravity.CENTER);
        button.setMinHeight(dp(52));
        button.setPadding(dp(14), 0, dp(14), 0);
        button.setStateListAnimator(null);
        button.setOnClickListener(listener);
        return button;
    }

    @SuppressWarnings("deprecation")
    private Switch toggle(String label, boolean initial, ToggleListener listener) {
        Switch toggle = new Switch(this);
        toggle.setText(label);
        toggle.setTextSize(15);
        toggle.setTextColor(INK);
        toggle.setGravity(Gravity.CENTER_VERTICAL);
        toggle.setChecked(initial);
        toggle.setShowText(false);
        toggle.setOnCheckedChangeListener((button, checked) -> listener.changed(checked));
        return toggle;
    }

    private TextView text(String value, int sp, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sp);
        view.setTextColor(color);
        view.setLineSpacing(0, 1.15f);
        return view;
    }

    private void applyPalette() {
        if (darkMode) {
            INK = Color.rgb(230, 242, 239);
            MUTED = Color.rgb(179, 195, 191);
            TEAL = Color.rgb(15, 118, 110);
            TEAL_DARK = Color.rgb(94, 234, 212);
            TEAL_PRESSED = Color.rgb(17, 94, 89);
            TEAL_PALE = Color.rgb(24, 67, 61);
            GREEN = Color.rgb(110, 231, 183);
            GREEN_PALE = Color.rgb(23, 60, 47);
            AMBER = Color.rgb(251, 191, 36);
            AMBER_PALE = Color.rgb(66, 47, 10);
            RED = Color.rgb(252, 165, 165);
            RED_PALE = Color.rgb(71, 31, 37);
            RED_PRESSED = Color.rgb(91, 40, 47);
            BACKGROUND = Color.rgb(15, 23, 21);
            SURFACE = Color.rgb(24, 35, 33);
            SURFACE_MUTED = Color.rgb(32, 45, 42);
            DIVIDER = Color.rgb(52, 67, 63);
        } else {
            INK = Color.rgb(16, 32, 29);
            MUTED = Color.rgb(82, 100, 95);
            TEAL = Color.rgb(8, 127, 112);
            TEAL_DARK = Color.rgb(5, 98, 86);
            TEAL_PRESSED = Color.rgb(5, 98, 86);
            TEAL_PALE = Color.rgb(221, 244, 239);
            GREEN = Color.rgb(20, 125, 85);
            GREEN_PALE = Color.rgb(224, 246, 235);
            AMBER = Color.rgb(151, 91, 8);
            AMBER_PALE = Color.rgb(255, 242, 211);
            RED = Color.rgb(178, 48, 48);
            RED_PALE = Color.rgb(255, 231, 231);
            RED_PRESSED = Color.rgb(250, 211, 211);
            BACKGROUND = Color.rgb(244, 247, 246);
            SURFACE = Color.WHITE;
            SURFACE_MUTED = Color.rgb(236, 241, 239);
            DIVIDER = Color.rgb(218, 226, 223);
        }
    }

    private void applySystemBars() {
        getWindow().setStatusBarColor(BACKGROUND);
        getWindow().setNavigationBarColor(BACKGROUND);
        if (Build.VERSION.SDK_INT >= 28) {
            getWindow().setNavigationBarDividerColor(DIVIDER);
        }
        int appearance = darkMode ? 0
                : View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        getWindow().getDecorView().setSystemUiVisibility(appearance);
    }

    private GradientDrawable rounded(int color, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(radiusDp));
        return drawable;
    }

    private StateListDrawable interactiveRounded(int normal, int pressed, int radiusDp) {
        StateListDrawable drawable = new StateListDrawable();
        drawable.addState(new int[]{android.R.attr.state_pressed}, rounded(pressed, radiusDp));
        drawable.addState(new int[]{}, rounded(normal, radiusDp));
        return drawable;
    }

    private ColorStateList interactionColors(int normal, int pressed) {
        return new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_pressed}, new int[]{}},
                new int[]{pressed, normal});
    }

    private void addTop(LinearLayout parent, View view, int marginDp) {
        LinearLayout.LayoutParams params = match(LinearLayout.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, dp(marginDp), 0, 0);
        parent.addView(view, params);
    }

    private LinearLayout.LayoutParams match(int height) {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, height);
    }

    private LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private interface ToggleListener {
        void changed(boolean checked);
    }
}
