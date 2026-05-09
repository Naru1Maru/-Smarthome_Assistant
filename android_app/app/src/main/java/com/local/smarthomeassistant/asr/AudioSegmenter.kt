package com.local.smarthomeassistant.asr

import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

data class AudioSegment(
    val samples: FloatArray,
    val speechDetected: Boolean,
    val startSample: Int,
    val endSampleExclusive: Int,
    val totalSamples: Int,
    val dcOffset: Float,
    val normalizationGain: Float
)

class AudioSegmenter(
    private val sampleRate: Int
) {
    companion object {
        private const val FRAME_MS = 20
        private const val HOP_MS = 10
        private const val MIN_RMS_THRESHOLD = 0.008f
        private const val MAX_RMS_THRESHOLD = 0.04f
        private const val THRESHOLD_MULTIPLIER = 2.6f
        private const val THRESHOLD_MARGIN = 0.003f
        private const val MIN_SPEECH_RUN_MS = 60
        private const val MAX_GAP_MS = 120
        private const val PRE_ROLL_MS = 320
        private const val TRAILING_CONTEXT_MS = 240
        private const val NORMALIZE_TARGET_PEAK = 0.85f
        private const val MAX_NORMALIZE_GAIN = 1.8f
        private const val MIN_NORMALIZE_PEAK = 0.05f
    }

    private val frameSize = max(1, sampleRate * FRAME_MS / 1000)
    private val hopSize = max(1, sampleRate * HOP_MS / 1000)
    private val minSpeechRunFrames = max(1, MIN_SPEECH_RUN_MS / HOP_MS)
    private val maxGapFrames = max(1, MAX_GAP_MS / HOP_MS)
    private val leadingContextSamples = sampleRate * PRE_ROLL_MS / 1000
    private val trailingContextSamples = sampleRate * TRAILING_CONTEXT_MS / 1000

    fun segment(samples: FloatArray): AudioSegment {
        if (samples.isEmpty()) {
            return AudioSegment(
                samples = samples,
                speechDetected = false,
                startSample = 0,
                endSampleExclusive = 0,
                totalSamples = 0,
                dcOffset = 0f,
                normalizationGain = 1f
            )
        }

        val preprocessed = preprocess(samples)

        val frameLevels = buildFrameLevels(preprocessed.samples)
        if (frameLevels.isEmpty()) {
            return fallback(preprocessed.samples, preprocessed.dcOffset, preprocessed.normalizationGain)
        }

        val noiseFloor = estimateNoiseFloor(frameLevels)
        val threshold = (noiseFloor * THRESHOLD_MULTIPLIER + THRESHOLD_MARGIN)
            .coerceIn(MIN_RMS_THRESHOLD, MAX_RMS_THRESHOLD)

        val voiced = BooleanArray(frameLevels.size) { idx -> frameLevels[idx] >= threshold }
        removeShortSpeechRuns(voiced)
        fillShortSilenceGaps(voiced)
        removeShortSpeechRuns(voiced)

        val firstVoiced = voiced.indexOfFirst { it }
        if (firstVoiced < 0) {
            return fallback(preprocessed.samples, preprocessed.dcOffset, preprocessed.normalizationGain)
        }
        val lastVoiced = voiced.indexOfLast { it }

        val speechStartSample = max(0, firstVoiced * hopSize - leadingContextSamples)
        val speechEndSample = min(
            preprocessed.samples.size,
            lastVoiced * hopSize + frameSize + trailingContextSamples
        )
        if (speechEndSample <= speechStartSample) {
            return fallback(preprocessed.samples, preprocessed.dcOffset, preprocessed.normalizationGain)
        }

        return AudioSegment(
            samples = preprocessed.samples.copyOfRange(speechStartSample, speechEndSample),
            speechDetected = true,
            startSample = speechStartSample,
            endSampleExclusive = speechEndSample,
            totalSamples = preprocessed.samples.size,
            dcOffset = preprocessed.dcOffset,
            normalizationGain = preprocessed.normalizationGain
        )
    }

    private fun fallback(
        samples: FloatArray,
        dcOffset: Float,
        normalizationGain: Float
    ): AudioSegment =
        AudioSegment(
            samples = samples.copyOf(),
            speechDetected = false,
            startSample = 0,
            endSampleExclusive = samples.size,
            totalSamples = samples.size,
            dcOffset = dcOffset,
            normalizationGain = normalizationGain
        )

    private data class AudioPreprocessResult(
        val samples: FloatArray,
        val dcOffset: Float,
        val normalizationGain: Float
    )

    private fun preprocess(samples: FloatArray): AudioPreprocessResult {
        if (samples.isEmpty()) {
            return AudioPreprocessResult(samples = samples, dcOffset = 0f, normalizationGain = 1f)
        }

        var sum = 0.0
        var peak = 0f
        for (sample in samples) {
            sum += sample
            val abs = kotlin.math.abs(sample)
            if (abs > peak) peak = abs
        }
        val dcOffset = (sum / samples.size).toFloat()
        val dcRemoved = FloatArray(samples.size)
        var dcRemovedPeak = 0f
        for (i in samples.indices) {
            val value = (samples[i] - dcOffset).coerceIn(-1f, 1f)
            dcRemoved[i] = value
            val abs = kotlin.math.abs(value)
            if (abs > dcRemovedPeak) dcRemovedPeak = abs
        }

        val normalizationGain =
            if (dcRemovedPeak in MIN_NORMALIZE_PEAK..NORMALIZE_TARGET_PEAK) {
                (NORMALIZE_TARGET_PEAK / dcRemovedPeak).coerceAtMost(MAX_NORMALIZE_GAIN)
            } else {
                1f
            }

        if (normalizationGain == 1f) {
            return AudioPreprocessResult(
                samples = dcRemoved,
                dcOffset = dcOffset,
                normalizationGain = 1f
            )
        }

        val normalized = FloatArray(dcRemoved.size)
        for (i in dcRemoved.indices) {
            normalized[i] = (dcRemoved[i] * normalizationGain).coerceIn(-1f, 1f)
        }
        return AudioPreprocessResult(
            samples = normalized,
            dcOffset = dcOffset,
            normalizationGain = normalizationGain
        )
    }

    private fun buildFrameLevels(samples: FloatArray): FloatArray {
        if (samples.isEmpty()) return FloatArray(0)

        val levels = ArrayList<Float>((samples.size + hopSize - 1) / hopSize)
        var start = 0
        while (start < samples.size) {
            val end = min(samples.size, start + frameSize)
            var sum = 0.0
            for (i in start until end) {
                val value = samples[i].toDouble()
                sum += value * value
            }
            val count = end - start
            if (count > 0) {
                levels += sqrt(sum / count).toFloat()
            }
            start += hopSize
        }
        return levels.toFloatArray()
    }

    private fun estimateNoiseFloor(levels: FloatArray): Float {
        if (levels.isEmpty()) return MIN_RMS_THRESHOLD
        val sorted = levels.copyOf().apply { sort() }
        val percentileIndex = ((sorted.size - 1) * 0.2f).toInt().coerceIn(0, sorted.lastIndex)
        return sorted[percentileIndex]
    }

    private fun removeShortSpeechRuns(voiced: BooleanArray) {
        var i = 0
        while (i < voiced.size) {
            if (!voiced[i]) {
                i++
                continue
            }
            val start = i
            while (i < voiced.size && voiced[i]) i++
            if (i - start < minSpeechRunFrames) {
                for (j in start until i) {
                    voiced[j] = false
                }
            }
        }
    }

    private fun fillShortSilenceGaps(voiced: BooleanArray) {
        var i = 0
        while (i < voiced.size) {
            if (voiced[i]) {
                i++
                continue
            }
            val start = i
            while (i < voiced.size && !voiced[i]) i++
            val gapFrames = i - start
            if (start > 0 && i < voiced.size && gapFrames <= maxGapFrames) {
                for (j in start until i) {
                    voiced[j] = true
                }
            }
        }
    }
}
