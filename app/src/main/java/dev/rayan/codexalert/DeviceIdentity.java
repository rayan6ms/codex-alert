package dev.rayan.codexalert;

import android.content.Context;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;

import java.math.BigInteger;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.Certificate;
import java.security.spec.ECGenParameterSpec;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

import javax.net.ssl.KeyManagerFactory;
import javax.security.auth.x500.X500Principal;

final class DeviceIdentity {
    private static final String PREFERENCES = "identity";
    private static final int IDENTITY_VERSION = 3;
    private static final String KEY_ALIAS = "codex-alert-server-v3";
    private static final long PAIRING_LIFETIME_MS = 10L * 60 * 1000;
    private static final int MAX_PAIRING_ATTEMPTS = 5;
    private static final SecureRandom RANDOM = new SecureRandom();

    private DeviceIdentity() {}

    static synchronized KeyStore keyStore(Context context) throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        if (!keyStore.containsAlias(KEY_ALIAS)) {
            KeyPairGenerator generator = KeyPairGenerator.getInstance(
                    KeyProperties.KEY_ALGORITHM_EC,
                    "AndroidKeyStore"
            );
            long now = System.currentTimeMillis();
            byte[] serial = new byte[16];
            RANDOM.nextBytes(serial);
            generator.initialize(
                    new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_SIGN)
                            .setAlgorithmParameterSpec(new ECGenParameterSpec("secp256r1"))
                            // Android's TLS stack may hash handshake data itself and request a
                            // raw signature, so TLS identities must also allow DIGEST_NONE.
                            .setDigests(
                                    KeyProperties.DIGEST_NONE,
                                    KeyProperties.DIGEST_SHA256,
                                    KeyProperties.DIGEST_SHA384,
                                    KeyProperties.DIGEST_SHA512
                            )
                            .setCertificateSubject(new X500Principal("CN=Codex Alert receiver"))
                            .setCertificateSerialNumber(new BigInteger(1, serial))
                            .setCertificateNotBefore(new Date(now - 24L * 60 * 60 * 1000))
                            .setCertificateNotAfter(new Date(now + 20L * 365 * 24 * 60 * 60 * 1000))
                            .build()
            );
            generator.generateKeyPair();
            keyStore.load(null);
        }
        migrateLegacyIdentity(context);
        return keyStore;
    }

    static KeyManagerFactory keyManagers(Context context) throws Exception {
        KeyManagerFactory factory = KeyManagerFactory.getInstance(
                KeyManagerFactory.getDefaultAlgorithm()
        );
        factory.init(keyStore(context), null);
        return factory;
    }

    static synchronized String deliveryToken(Context context) {
        ensureIdentity(context);
        var preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        String existing = preferences.getString("delivery_token", "");
        if (existing.matches("[0-9a-f]{64}")) {
            return existing;
        }
        String token = newDeliveryToken();
        preferences.edit().putString("delivery_token", token).apply();
        return token;
    }

    static synchronized String beginPairing(Context context) throws Exception {
        keyStore(context);
        deliveryToken(context);
        String code = String.format(Locale.ROOT, "%08d", RANDOM.nextInt(100_000_000));
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putString("pairing_code", code)
                .putLong("pairing_expires_at", System.currentTimeMillis() + PAIRING_LIFETIME_MS)
                .putInt("pairing_attempts", 0)
                .apply();
        return code;
    }

    static synchronized String acceptPairingCode(Context context, String supplied) {
        var preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        String expected = preferences.getString("pairing_code", "");
        long expiresAt = preferences.getLong("pairing_expires_at", 0);
        int attempts = preferences.getInt("pairing_attempts", 0);
        if (expected.isEmpty() || System.currentTimeMillis() > expiresAt) {
            clearPairingCode(context);
            return "pairing-expired";
        }
        if (attempts >= MAX_PAIRING_ATTEMPTS) {
            clearPairingCode(context);
            return "too-many-attempts";
        }
        byte[] suppliedBytes = String.valueOf(supplied).getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        byte[] expectedBytes = expected.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        if (!MessageDigest.isEqual(suppliedBytes, expectedBytes)) {
            preferences.edit().putInt("pairing_attempts", attempts + 1).apply();
            return "invalid-code";
        }
        // Do not mark the phone paired yet. The desktop must prove it received the
        // credentials with an authenticated follow-up request. Until then the same
        // code remains safely retryable after a dropped HTTP response.
        return "paired";
    }

    static synchronized void completePairing(Context context) {
        var preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        preferences.edit()
                .putBoolean("paired", true)
                .putLong("paired_at", System.currentTimeMillis())
                .remove("pairing_code")
                .remove("pairing_expires_at")
                .remove("pairing_attempts")
                .apply();
    }

    static boolean pairingActive(Context context) {
        var preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        return !preferences.getString("pairing_code", "").isEmpty()
                && System.currentTimeMillis() <= preferences.getLong("pairing_expires_at", 0);
    }

    static String currentPairingCode(Context context) {
        if (!pairingActive(context)) {
            return "";
        }
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .getString("pairing_code", "");
    }

    static boolean isPaired(Context context) {
        var preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        return preferences.getInt("identity_version", 0) == IDENTITY_VERSION
                && preferences.getBoolean("paired", false);
    }

    static synchronized void forgetDesktop(Context context) {
        byte[] random = new byte[32];
        RANDOM.nextBytes(random);
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putBoolean("paired", false)
                .putString("delivery_token", hex(random))
                .remove("pairing_code")
                .remove("pairing_expires_at")
                .remove("pairing_attempts")
                .apply();
    }

    static String securityCode(Context context) {
        try {
            Certificate certificate = keyStore(context).getCertificate(KEY_ALIAS);
            String digest = hex(MessageDigest.getInstance("SHA-256").digest(certificate.getEncoded()));
            List<String> groups = new ArrayList<>();
            for (int index = 0; index < 16; index += 4) {
                groups.add(digest.substring(index, index + 4).toUpperCase(Locale.ROOT));
            }
            return String.join(" ", groups);
        } catch (Exception exception) {
            return "unavailable";
        }
    }

    static String deviceName() {
        String manufacturer = Build.MANUFACTURER == null ? "Android" : Build.MANUFACTURER.trim();
        String model = Build.MODEL == null ? "phone" : Build.MODEL.trim();
        if (model.toLowerCase(Locale.ROOT).startsWith(manufacturer.toLowerCase(Locale.ROOT))) {
            return model;
        }
        return (manufacturer + " " + model).trim();
    }

    private static void clearPairingCode(Context context) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .remove("pairing_code")
                .remove("pairing_expires_at")
                .remove("pairing_attempts")
                .apply();
    }

    private static void migrateLegacyIdentity(Context context) {
        var preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
        if (preferences.getInt("identity_version", 0) == IDENTITY_VERSION) {
            return;
        }
        boolean saved = preferences.edit()
                .putInt("identity_version", IDENTITY_VERSION)
                .putBoolean("paired", false)
                .putString("delivery_token", newDeliveryToken())
                .remove("pairing_code")
                .remove("pairing_expires_at")
                .remove("pairing_attempts")
                .commit();
        if (!saved) {
            throw new IllegalStateException("Could not migrate the device identity");
        }
    }

    private static void ensureIdentity(Context context) {
        try {
            keyStore(context);
        } catch (Exception exception) {
            throw new IllegalStateException("Could not prepare the device identity", exception);
        }
    }

    private static String newDeliveryToken() {
        byte[] random = new byte[32];
        RANDOM.nextBytes(random);
        return hex(random);
    }

    private static String hex(byte[] bytes) {
        StringBuilder value = new StringBuilder(bytes.length * 2);
        for (byte item : bytes) {
            value.append(String.format(Locale.ROOT, "%02x", item & 0xff));
        }
        return value.toString();
    }
}
