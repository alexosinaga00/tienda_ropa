plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
    // Debe ir después del plugin de Android: procesa app/google-services.json (ignorado por git).
    id("com.google.gms.google-services")
}

android {
    namespace = "com.fashionstore.mobile"
    // flutter.compileSdkVersion (36) se quedó corto: flutter_secure_storage
    // y permission_handler_android piden compileSdk 37. Es compatible hacia
    // atrás, así que se fija acá en vez de esperar a que Flutter lo suba.
    compileSdk = 37
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.fashionstore.mobile"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
            // R8 apagado hasta auditar las reglas de keep de las dependencias
            // (sin reglas propias de ProGuard, minificar elimina constructores
            // que algunas librerías nativas usan por reflexión).
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
