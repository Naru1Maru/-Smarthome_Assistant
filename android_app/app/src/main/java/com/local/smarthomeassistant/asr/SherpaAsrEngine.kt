package com.local.smarthomeassistant.asr

import android.content.Context
import android.util.Log
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.OfflineTransducerModelConfig

class SherpaAsrEngine(
    private val appContext: Context,
    private val modelAssetDir: String
) : BufferedPushToTalkAsrEngine(TAG) {

    private companion object {
        const val TAG = "SherpaAsrEngine"
        const val FEATURE_DIM = 80
    }

    private var recognizer: OfflineRecognizer? = null

    override fun prepareModelIfNeeded(onError: (String) -> Unit): Boolean {
        if (recognizer != null) return true

        return try {
            val config = OfflineRecognizerConfig(
                featConfig = FeatureConfig(
                    sampleRate = SAMPLE_RATE,
                    featureDim = FEATURE_DIM,
                    dither = 0f
                ),
                modelConfig = OfflineModelConfig(
                    transducer = OfflineTransducerModelConfig(
                        encoder = "$modelAssetDir/encoder.int8.onnx",
                        decoder = "$modelAssetDir/decoder.onnx",
                        joiner = "$modelAssetDir/joiner.int8.onnx"
                    ),
                    tokens = "$modelAssetDir/tokens.txt",
                    numThreads = 2,
                    modelType = "transducer"
                )
            )

            recognizer = OfflineRecognizer(
                assetManager = appContext.assets,
                config = config
            )
            Log.i(TAG, "Sherpa model initialized from '$modelAssetDir'")
            true
        } catch (e: Exception) {
            val detail = buildString {
                append("Не удалось инициализировать модель Sherpa-ONNX из assets: '$modelAssetDir'\n")
                append("Проверьте: app/src/main/assets/$modelAssetDir\n")
                append("Exception: ${e::class.java.name}: ${e.message}\n")
                append(Log.getStackTraceString(e))
            }
            onError(detail)
            false
        }
    }

    override fun close() {
        stopListening(deliverFinal = false)
        recognizer?.release()
        recognizer = null
        resetCapturedAudio()
    }

    override fun isDecoderReady(): Boolean = recognizer != null

    override fun decodeAudio(samples: FloatArray): String {
        val currentRecognizer = recognizer ?: return ""
        val stream = currentRecognizer.createStream()
        return try {
            stream.acceptWaveform(samples, SAMPLE_RATE)
            currentRecognizer.decode(stream)
            currentRecognizer.getResult(stream).text
        } finally {
            stream.release()
        }
    }
}
