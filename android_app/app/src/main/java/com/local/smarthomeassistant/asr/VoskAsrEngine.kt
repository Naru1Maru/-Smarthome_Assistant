package com.local.smarthomeassistant.asr

import android.content.Context
import android.content.res.AssetManager
import android.util.Log
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.StorageService
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import java.util.concurrent.CountDownLatch

/**
 * Vosk ASR wrapper for buffered push-to-talk.
 *
 * Model must be placed in:
 *   app/src/main/assets/<modelAssetDir>/
 * Example:
 *   app/src/main/assets/models/vosk-model-small-ru-0.22/
 */
class VoskAsrEngine(
    private val appContext: Context,
    private val modelAssetDir: String
) : BufferedPushToTalkAsrEngine(TAG) {

    private companion object {
        const val TAG = "VoskAsrEngine"
    }

    private var model: Model? = null

    override fun prepareModelIfNeeded(onError: (String) -> Unit): Boolean {
        if (model != null) return true

        Log.i(TAG, "prepareModelIfNeeded: assetDir='$modelAssetDir'")

        val latch = CountDownLatch(1)
        var ok = false

        StorageService.unpack(
            appContext,
            modelAssetDir,
            "vosk_model",
            { m ->
                model = m
                ok = true
                Log.i(TAG, "Vosk model unpacked OK")
                latch.countDown()
            },
            { e ->
                Log.e(TAG, "Vosk model unpack FAILED. assetDir='$modelAssetDir'", e)
                ok = tryManualModelLoad(onError, e)
                latch.countDown()
            }
        )

        latch.await()
        return ok
    }

    override fun close() {
        stopListening(deliverFinal = false)
        model?.close()
        model = null
        resetCapturedAudio()
    }

    override fun isDecoderReady(): Boolean = model != null

    override fun decodeAudio(samples: FloatArray): String {
        val currentModel = model ?: return ""
        val recognizer = Recognizer(currentModel, SAMPLE_RATE.toFloat())
        return try {
            val pcm = floatsToPcm16(samples)
            recognizer.acceptWaveForm(pcm, pcm.size)
            safeExtractText(recognizer.finalResult)
        } finally {
            recognizer.close()
        }
    }

    private fun safeExtractText(json: String): String =
        try { JSONObject(json).optString("text", "") } catch (_: Exception) { "" }

    private fun floatsToPcm16(samples: FloatArray): ByteArray {
        val out = ByteArray(samples.size * 2)
        var j = 0
        for (sample in samples) {
            val clamped = sample.coerceIn(-1f, 1f)
            val value = (clamped * Short.MAX_VALUE).toInt().toShort()
            out[j++] = (value.toInt() and 0xFF).toByte()
            out[j++] = ((value.toInt() shr 8) and 0xFF).toByte()
        }
        return out
    }

    private fun tryManualModelLoad(onError: (String) -> Unit, originalError: Exception): Boolean {
        return try {
            val targetDir = File(appContext.filesDir, "vosk_model_manual")
            if (targetDir.exists()) targetDir.deleteRecursively()

            copyAssetEntry(appContext.assets, modelAssetDir, targetDir)

            val uuidFile = File(targetDir, "uuid")
            if (!uuidFile.exists()) {
                uuidFile.writeText(UUID.randomUUID().toString())
                Log.w(TAG, "Model asset has no uuid, synthesized one at: ${uuidFile.absolutePath}")
            }

            model = Model(targetDir.absolutePath)
            Log.i(TAG, "Vosk model loaded via manual fallback from '$modelAssetDir'")
            true
        } catch (fallbackError: Exception) {
            val detail = buildString {
                append("Не удалось распаковать модель Vosk из assets: '$modelAssetDir'\n")
                append("Проверьте: app/src/main/assets/$modelAssetDir\n")
                append("Primary exception: ${originalError::class.java.name}: ${originalError.message}\n")
                append("Fallback exception: ${fallbackError::class.java.name}: ${fallbackError.message}\n")
                append(Log.getStackTraceString(fallbackError))
            }
            onError(detail)
            false
        }
    }

    private fun copyAssetEntry(assets: AssetManager, assetPath: String, destination: File) {
        val children = assets.list(assetPath) ?: emptyArray()
        if (children.isEmpty()) {
            destination.parentFile?.mkdirs()
            assets.open(assetPath).use { input ->
                FileOutputStream(destination).use { output ->
                    input.copyTo(output)
                }
            }
            return
        }

        destination.mkdirs()
        for (child in children) {
            copyAssetEntry(
                assets = assets,
                assetPath = "$assetPath/$child",
                destination = File(destination, child)
            )
        }
    }
}
