package com.wails.app;

import android.net.Uri;
import android.util.Log;
import android.webkit.WebResourceResponse;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.webkit.WebViewAssetLoader;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;


public class WailsPathHandler implements WebViewAssetLoader.PathHandler {
    private static final String TAG = "WailsPathHandler";
    private static final boolean DEBUG = BuildConfig.DEBUG;

    private final WailsBridge bridge;

    public WailsPathHandler(WailsBridge bridge) {
        this.bridge = bridge;
    }

    @Nullable
    @Override
    public WebResourceResponse handle(@NonNull String path) {
        if (DEBUG) Log.d(TAG, "Handling path: " + path);


        if (path.isEmpty() || path.equals("/")) {
            path = "/index.html";
        }


        byte[] data = bridge.serveAsset(path, "GET", "{}");

        if (data == null || data.length == 0) {
            Log.w(TAG, "Asset not found: " + path);
            return null;
        }


        String mimeType = bridge.getAssetMimeType(path);
        if (DEBUG) Log.d(TAG, "Serving " + path + " with type " + mimeType + " (" + data.length + " bytes)");


        InputStream inputStream = new ByteArrayInputStream(data);
        Map<String, String> headers = new HashMap<>();
        headers.put("Access-Control-Allow-Origin", "*");
        headers.put("Cache-Control", "no-cache");

        return new WebResourceResponse(
                mimeType,
                "UTF-8",
                200,
                "OK",
                headers,
                inputStream
        );
    }
}
