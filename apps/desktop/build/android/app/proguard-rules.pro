
-keepclasseswithmembernames class * {
    native <methods>;
}

-keep class com.wails.app.WailsBridge { *; }
-keep class com.wails.app.WailsJSBridge { *; }
