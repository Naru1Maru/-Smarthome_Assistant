package com.local.smarthomeassistant.asr

import kotlin.math.max
import kotlin.math.sqrt

class SpeechActivityDetector(
    private val sampleRate: Int
) {
    companion object {
        private const val FRAME_MS = 20
        private const val MIN_START_THRESHOLD = 0.010f
        private const val MAX_START_THRESHOLD = 0.050f
        private const val MIN_END_THRESHOLD = 0.007f
        private const val START_THRESHOLD_MULTIPLIER = 2.8f
        private const val END_THRESHOLD_MULTIPLIER = 1.9f
        private const val START_THRESHOLD_MARGIN = 0.003f
        private const val END_THRESHOLD_MARGIN = 0.002f
        private const val START_FRAMES = 3
        private const val END_FRAMES = 8
        private const val NOISE_FLOOR_ALPHA = 0.08f
    }

    private val frameSize = max(1, sampleRate * FRAME_MS / 1000)
    private val frameBuffer = ShortArray(frameSize)

    private var frameBufferSize = 0
    private var processedSamples = 0L
    private var noiseFloor = MIN_END_THRESHOLD
    private var voicedRunFrames = 0
    private var silenceRunFrames = 0
    private var state = SpeechActivityState()

    fun reset() {
        frameBufferSize = 0
        processedSamples = 0L
        noiseFloor = MIN_END_THRESHOLD
        voicedRunFrames = 0
        silenceRunFrames = 0
        state = SpeechActivityState()
    }

    fun process(samples: ShortArray, length: Int, onStateChanged: (SpeechActivityState) -> Unit) {
        for (i in 0 until length) {
            frameBuffer[frameBufferSize++] = samples[i]
            if (frameBufferSize == frameSize) {
                processFrame(onStateChanged)
                frameBufferSize = 0
            }
        }
    }

    private fun processFrame(onStateChanged: (SpeechActivityState) -> Unit) {
        val level = computeRms(frameBuffer, frameSize)
        val startThreshold = (noiseFloor * START_THRESHOLD_MULTIPLIER + START_THRESHOLD_MARGIN)
            .coerceIn(MIN_START_THRESHOLD, MAX_START_THRESHOLD)
        val endThreshold = (noiseFloor * END_THRESHOLD_MULTIPLIER + END_THRESHOLD_MARGIN)
            .coerceIn(MIN_END_THRESHOLD, startThreshold)
        val frameEndSampleExclusive = processedSamples + frameSize

        if (!state.speechActive && level < startThreshold) {
            noiseFloor = noiseFloor * (1f - NOISE_FLOOR_ALPHA) + level * NOISE_FLOOR_ALPHA
        }

        val voiced = level >= if (state.speechActive) endThreshold else startThreshold
        var nextState = state

        if (state.speechActive) {
            if (voiced) {
                silenceRunFrames = 0
            } else {
                silenceRunFrames += 1
                if (silenceRunFrames >= END_FRAMES) {
                    val speechEndSampleExclusive =
                        (frameEndSampleExclusive - END_FRAMES.toLong() * frameSize)
                            .coerceAtLeast(0L)
                    nextState = state.copy(
                        speechActive = false,
                        speechEndOffsetMs = samplesToMs(speechEndSampleExclusive)
                    )
                    voicedRunFrames = 0
                    silenceRunFrames = 0
                }
            }
        } else {
            if (voiced) {
                voicedRunFrames += 1
                if (voicedRunFrames >= START_FRAMES) {
                    val speechStartSample =
                        (frameEndSampleExclusive - START_FRAMES.toLong() * frameSize)
                            .coerceAtLeast(0L)
                    nextState = state.copy(
                        speechDetected = true,
                        speechActive = true,
                        speechStartOffsetMs = state.speechStartOffsetMs ?: samplesToMs(speechStartSample),
                        speechEndOffsetMs = null
                    )
                    voicedRunFrames = 0
                    silenceRunFrames = 0
                }
            } else {
                voicedRunFrames = 0
            }
        }

        processedSamples = frameEndSampleExclusive

        if (nextState != state) {
            state = nextState
            onStateChanged(state)
        }
    }

    private fun samplesToMs(sampleOffset: Long): Long = (sampleOffset * 1000L) / sampleRate

    private fun computeRms(samples: ShortArray, length: Int): Float {
        var sum = 0.0
        for (i in 0 until length) {
            val value = samples[i].toDouble() / Short.MAX_VALUE
            sum += value * value
        }
        return if (length == 0) 0f else sqrt(sum / length).toFloat()
    }
}
