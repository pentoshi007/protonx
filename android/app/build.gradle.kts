plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "dev.pentoshi.protonx"
    compileSdk = 35

    defaultConfig {
        applicationId = "dev.pentoshi.protonx"
        minSdk = 26
        targetSdk = 35
        versionCode = 5
        versionName = "1.2.4"
        resourceConfigurations += listOf("en")
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }

    buildFeatures { viewBinding = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    signingConfigs {
        create("release") {
            // Public sideload key: it exists so every release upgrades the previous
            // install instead of colliding with it. It is not a Play Store key.
            storeFile = rootProject.file("keystore/protonx-release.jks")
            storePassword = "protonx-sideload"
            keyAlias = "protonx"
            keyPassword = "protonx-sideload"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    packaging {
        resources.excludes += setOf("META-INF/versions/9/OSGI-INF/MANIFEST.MF", "META-INF/LICENSE*")
    }

    testOptions { unitTests.isReturnDefaultValues = true }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.core:core-splashscreen:1.0.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    implementation("com.wireguard.android:tunnel:1.0.20260102")
    implementation("org.bouncycastle:bcprov-jdk18on:1.87")
    implementation("at.favre.lib:bcrypt:0.10.2")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
