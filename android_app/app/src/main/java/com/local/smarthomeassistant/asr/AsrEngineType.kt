package com.local.smarthomeassistant.asr

enum class AsrEngineType(
    val storageValue: String,
    val label: String
) {
    VOSK("vosk", "Vosk"),
    SHERPA("sherpa", "Sherpa");

    companion object {
        fun fromStorage(value: String?): AsrEngineType =
            entries.firstOrNull { it.storageValue == value?.trim()?.lowercase() } ?: VOSK
    }
}
