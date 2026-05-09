package com.local.smarthomeassistant.asr

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import android.util.Log
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread
import kotlin.math.sqrt

abstract class BufferedPushToTalkAsrEngine(
    private val tag: String
) : AsrEngine {
    private data class RawCaptureBuffer(
        val samples: FloatArray,
        val peakLevel: Float,
        val clippedSampleCount: Int
    )

    protected companion object {
        const val SAMPLE_RATE = 16_000
        private const val LEVEL_EMIT_INTERVAL_MS = 50L
        private const val RELEASE_TAIL_MS = 240
    }

    private var audioRecord: AudioRecord? = null
    private var audioThread: Thread? = null

    private var onFinalCb: ((String, Long) -> Unit)? = null
    private var onErrorCb: ((String) -> Unit)? = null
    private var onAudioLevelCb: ((Float) -> Unit)? = null
    private var onSpeechActivityChangedCb: ((SpeechActivityState) -> Unit)? = null

    private val recording = AtomicBoolean(false)
    private var listenStartedAtMs: Long = 0
    private var lastLevelEmitMs: Long = 0
    private val segmenter = AudioSegmenter(SAMPLE_RATE)
    private val speechActivityDetector = SpeechActivityDetector(SAMPLE_RATE)

    private val audioLock = Any()
    private val audioChunks = mutableListOf<ShortArray>()
    private var capturedSamples = 0

    protected abstract fun isDecoderReady(): Boolean

    override abstract fun decodeAudio(samples: FloatArray): String

    protected open fun decoderNotReadyMessage(): String = "model not ready"

    override fun startListening(
        onPartial: (String) -> Unit,
        onFinal: (String, Long) -> Unit,
        onError: (String) -> Unit,
        onAudioLevel: (Float) -> Unit,
        onSpeechActivityChanged: (SpeechActivityState) -> Unit
    ) {
        if (!isDecoderReady()) {
            onError(decoderNotReadyMessage())
            return
        }

        stopListening(deliverFinal = false)

        onFinalCb = onFinal
        onErrorCb = onError
        onAudioLevelCb = onAudioLevel
        onSpeechActivityChangedCb = onSpeechActivityChanged

        resetCapturedAudio()
        speechActivityDetector.reset()

        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuffer <= 0) {
            onError("AudioRecord buffer init failed")
            return
        }

        val recorder = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            minBuffer * 2
        )

        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            onError("AudioRecord init failed")
            return
        }

        audioRecord = recorder
        listenStartedAtMs = SystemClock.elapsedRealtime()
        lastLevelEmitMs = 0
        recording.set(true)

        try {
            recorder.startRecording()
        } catch (e: Exception) {
            recording.set(false)
            recorder.release()
            onError("AudioRecord start failed: ${e.message}")
            return
        }

        audioThread = thread(name = "${tag}AudioThread") {
            processAudio(recorder, minBuffer)
        }
    }

    override fun stopListening(deliverFinal: Boolean): CapturedAudio? {
        val wasRecording = recording.getAndSet(false)
        stopRecorder()
        joinAudioThread()

        val capturedAudio =
            if (wasRecording || capturedSamples > 0) {
                val rawCapture = buildCapturedAudioWithTailPadding()
                val segment = segmenter.segment(rawCapture.samples)
                val rawDurationMs = SystemClock.elapsedRealtime() - listenStartedAtMs
                val speechDurationMs = (segment.samples.size * 1000L) / SAMPLE_RATE
                val leadingTrimMs = (segment.startSample * 1000L) / SAMPLE_RATE
                val trailingTrimMs =
                    ((segment.totalSamples - segment.endSampleExclusive) * 1000L) / SAMPLE_RATE
                Log.i(
                    tag,
                    "segment speechDetected=${segment.speechDetected} rawMs=$rawDurationMs speechMs=$speechDurationMs trimStartMs=$leadingTrimMs trimEndMs=$trailingTrimMs peak=${"%.3f".format(rawCapture.peakLevel)} clipped=${rawCapture.clippedSampleCount} dcOffset=${"%.5f".format(segment.dcOffset)} gain=${"%.2f".format(segment.normalizationGain)}"
                )
                CapturedAudio(
                    samples = segment.samples,
                    durationMs = rawDurationMs,
                    speechDurationMs = speechDurationMs,
                    speechDetected = segment.speechDetected,
                    leadingTrimMs = leadingTrimMs,
                    trailingTrimMs = trailingTrimMs,
                    peakLevel = rawCapture.peakLevel,
                    clippingDetected = rawCapture.clippedSampleCount > 0,
                    clippedSampleCount = rawCapture.clippedSampleCount,
                    dcOffset = segment.dcOffset,
                    normalizationGain = segment.normalizationGain
                )
            } else {
                null
            }

        if (deliverFinal && capturedAudio != null) {
            val text = try {
                decodeAudio(capturedAudio.samples)
            } catch (e: Exception) {
                Log.e(tag, "decodeAudio failed", e)
                onErrorCb?.invoke("ASR decode error: ${e.message}")
                ""
            }
            onFinalCb?.invoke(text, capturedAudio.durationMs)
        }

        onAudioLevelCb?.invoke(0f)
        onSpeechActivityChangedCb?.invoke(SpeechActivityState())
        return capturedAudio
    }

    protected fun appendSamples(buffer: ShortArray, length: Int) {
        val chunk = buffer.copyOf(length)
        synchronized(audioLock) {
            audioChunks += chunk
            capturedSamples += length
        }
    }

    private fun processAudio(recorder: AudioRecord, minBuffer: Int) {
        val buffer = ShortArray(minBuffer)
        try {
            while (recording.get()) {
                val read = recorder.read(buffer, 0, buffer.size)
                if (read <= 0) continue
                appendSamples(buffer, read)
                emitAudioLevel(buffer, read)
                emitSpeechActivity(buffer, read)
            }
        } catch (e: Exception) {
            Log.e(tag, "processAudio loop error", e)
            onErrorCb?.invoke("Audio loop error: ${e.message}")
        } finally {
            stopRecorder()
        }
    }

    private fun buildCapturedAudioWithTailPadding(): RawCaptureBuffer {
        val totalWithTail = synchronized(audioLock) {
            capturedSamples + ((SAMPLE_RATE * RELEASE_TAIL_MS) / 1000)
        }
        if (totalWithTail <= 0) {
            return RawCaptureBuffer(
                samples = FloatArray(0),
                peakLevel = 0f,
                clippedSampleCount = 0
            )
        }

        return synchronized(audioLock) {
            val out = FloatArray(totalWithTail)
            var offset = 0
            var peakLevel = 0f
            var clippedSampleCount = 0
            for (chunk in audioChunks) {
                for (sample in chunk) {
                    val normalized = sample / 32768.0f
                    out[offset++] = normalized
                    val abs = kotlin.math.abs(normalized)
                    if (abs > peakLevel) peakLevel = abs
                    if (kotlin.math.abs(sample.toInt()) >= 32760) {
                        clippedSampleCount += 1
                    }
                }
            }
            RawCaptureBuffer(
                samples = out,
                peakLevel = peakLevel,
                clippedSampleCount = clippedSampleCount
            )
        }
    }

    protected fun resetCapturedAudio() {
        synchronized(audioLock) {
            audioChunks.clear()
            capturedSamples = 0
        }
    }

    private fun stopRecorder() {
        audioRecord?.run {
            try {
                stop()
            } catch (_: Exception) {
            }
            release()
        }
        audioRecord = null
    }

    private fun joinAudioThread() {
        val thread = audioThread ?: return
        if (thread !== Thread.currentThread()) {
            try {
                thread.join(200)
            } catch (_: InterruptedException) {
            }
        }
        audioThread = null
    }

    private fun emitAudioLevel(buffer: ShortArray, length: Int) {
        val now = SystemClock.elapsedRealtime()
        if (now - lastLevelEmitMs < LEVEL_EMIT_INTERVAL_MS) return
        lastLevelEmitMs = now

        var sum = 0.0
        for (i in 0 until length) {
            val sample = buffer[i].toInt()
            sum += (sample * sample).toDouble()
        }
        if (length == 0) return

        val rms = sqrt(sum / length) / Short.MAX_VALUE
        onAudioLevelCb?.invoke(rms.toFloat().coerceIn(0f, 1f))
    }

    private fun emitSpeechActivity(buffer: ShortArray, length: Int) {
        speechActivityDetector.process(buffer, length) { state ->
            onSpeechActivityChangedCb?.invoke(state)
        }
    }
}
