package com.local.smarthomeassistant.asr

data class CapturedAudio(
    val samples: FloatArray,
    val durationMs: Long,
    val speechDurationMs: Long = durationMs,
    val speechDetected: Boolean = false,
    val leadingTrimMs: Long = 0,
    val trailingTrimMs: Long = 0,
    val peakLevel: Float = 0f,
    val clippingDetected: Boolean = false,
    val clippedSampleCount: Int = 0,
    val dcOffset: Float = 0f,
    val normalizationGain: Float = 1f
)

data class SpeechActivityState(
    val speechDetected: Boolean = false,
    val speechActive: Boolean = false,
    val speechStartOffsetMs: Long? = null,
    val speechEndOffsetMs: Long? = null
)

interface AsrEngine {
    fun prepareModelIfNeeded(onError: (String) -> Unit): Boolean

    fun decodeAudio(samples: FloatArray): String

    fun startListening(
        onPartial: (String) -> Unit,
        onFinal: (String, Long) -> Unit,
        onError: (String) -> Unit,
        onAudioLevel: (Float) -> Unit,
        onSpeechActivityChanged: (SpeechActivityState) -> Unit
    )

    fun stopListening(deliverFinal: Boolean = true): CapturedAudio?

    fun close()
}
