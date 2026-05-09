package com.local.smarthomeassistant.net

internal fun normalizeBaseUrlForTest(baseUrl: String): String {
    val trimmed = baseUrl.trim().removeSuffix("/")
    return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed else "http://$trimmed"
}
