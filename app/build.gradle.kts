plugins {
    id("com.android.application")
}

val releaseStore = providers.environmentVariable("ANDROID_KEYSTORE_FILE").orNull
val releaseStorePassword = providers.environmentVariable("ANDROID_KEYSTORE_PASSWORD").orNull
val releaseKeyAlias = providers.environmentVariable("ANDROID_KEY_ALIAS").orNull
val releaseKeyPassword = providers.environmentVariable("ANDROID_KEY_PASSWORD").orNull
val appVersion = rootProject.file("VERSION").readText().trim()

android {
    namespace = "dev.rayan.codexalert"
    compileSdk = 35

    defaultConfig {
        applicationId = "dev.rayan.codexalert"
        minSdk = 26
        targetSdk = 35
        versionCode = 10000
        versionName = appVersion
    }

    val releaseSigning = if (listOf(
            releaseStore,
            releaseStorePassword,
            releaseKeyAlias,
            releaseKeyPassword
        ).all { !it.isNullOrBlank() }
    ) {
        signingConfigs.create("release") {
            storeFile = file(releaseStore!!)
            storePassword = releaseStorePassword
            keyAlias = releaseKeyAlias
            keyPassword = releaseKeyPassword
        }
    } else {
        null
    }

    buildTypes {
        getByName("release") {
            releaseSigning?.let { signingConfig = it }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        // Runtime targets are pinned to the locally verified SDK/toolchain.
        // Dependency-version suggestions are reviewed separately from code lint.
        disable += setOf("OldTargetApi", "GradleDependency", "AndroidGradlePluginVersion")
    }
}
