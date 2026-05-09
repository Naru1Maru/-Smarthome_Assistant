package com.local.smarthomeassistant.asr

import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import kotlin.math.roundToInt

data class DecodedWav(
    val sampleRate: Int,
    val samples: FloatArray
)

object WavFileCodec {
    private const val PCM_FORMAT = 1
    private const val MONO_CHANNELS = 1
    private const val BITS_PER_SAMPLE = 16
    private const val HEADER_SIZE = 44

    fun writeMonoPcm16(file: File, samples: FloatArray, sampleRate: Int) {
        file.parentFile?.mkdirs()
        val pcmBytes = ByteArray(samples.size * 2)
        var j = 0
        for (sample in samples) {
            val clamped = sample.coerceIn(-1f, 1f)
            val value = (clamped * Short.MAX_VALUE).roundToInt().toShort()
            pcmBytes[j++] = (value.toInt() and 0xFF).toByte()
            pcmBytes[j++] = ((value.toInt() shr 8) and 0xFF).toByte()
        }

        FileOutputStream(file).use { out ->
            out.writeAscii("RIFF")
            out.writeLeInt(36 + pcmBytes.size)
            out.writeAscii("WAVE")
            out.writeAscii("fmt ")
            out.writeLeInt(16)
            out.writeLeShort(PCM_FORMAT)
            out.writeLeShort(MONO_CHANNELS)
            out.writeLeInt(sampleRate)
            out.writeLeInt(sampleRate * MONO_CHANNELS * (BITS_PER_SAMPLE / 8))
            out.writeLeShort(MONO_CHANNELS * (BITS_PER_SAMPLE / 8))
            out.writeLeShort(BITS_PER_SAMPLE)
            out.writeAscii("data")
            out.writeLeInt(pcmBytes.size)
            out.write(pcmBytes)
        }
    }

    fun readMonoPcm16(file: File): DecodedWav {
        DataInputStream(BufferedInputStream(FileInputStream(file))).use { input ->
            val header = ByteArray(HEADER_SIZE)
            input.readFully(header)

            require(header.copyOfRange(0, 4).toAscii() == "RIFF") { "Invalid WAV header" }
            require(header.copyOfRange(8, 12).toAscii() == "WAVE") { "Invalid WAV format" }

            val audioFormat = header.readLeShort(20)
            val channels = header.readLeShort(22)
            val sampleRate = header.readLeInt(24)
            val bitsPerSample = header.readLeShort(34)
            val dataChunkSize = header.readLeInt(40)

            require(audioFormat == PCM_FORMAT) { "Only PCM WAV is supported" }
            require(channels == MONO_CHANNELS) { "Only mono WAV is supported" }
            require(bitsPerSample == BITS_PER_SAMPLE) { "Only 16-bit WAV is supported" }

            val pcm = ByteArray(dataChunkSize)
            input.readFully(pcm)
            val samples = FloatArray(dataChunkSize / 2)
            var src = 0
            var dst = 0
            while (src + 1 < pcm.size) {
                val lo = pcm[src].toInt() and 0xFF
                val hi = pcm[src + 1].toInt()
                val value = ((hi shl 8) or lo).toShort()
                samples[dst++] = value / 32768.0f
                src += 2
            }
            return DecodedWav(sampleRate = sampleRate, samples = samples)
        }
    }

    private fun FileOutputStream.writeAscii(text: String) {
        write(text.toByteArray(Charsets.US_ASCII))
    }

    private fun FileOutputStream.writeLeInt(value: Int) {
        write(byteArrayOf(
            (value and 0xFF).toByte(),
            ((value shr 8) and 0xFF).toByte(),
            ((value shr 16) and 0xFF).toByte(),
            ((value shr 24) and 0xFF).toByte()
        ))
    }

    private fun FileOutputStream.writeLeShort(value: Int) {
        write(byteArrayOf(
            (value and 0xFF).toByte(),
            ((value shr 8) and 0xFF).toByte()
        ))
    }

    private fun ByteArray.readLeInt(offset: Int): Int =
        (this[offset].toInt() and 0xFF) or
            ((this[offset + 1].toInt() and 0xFF) shl 8) or
            ((this[offset + 2].toInt() and 0xFF) shl 16) or
            ((this[offset + 3].toInt() and 0xFF) shl 24)

    private fun ByteArray.readLeShort(offset: Int): Int =
        (this[offset].toInt() and 0xFF) or
            ((this[offset + 1].toInt() and 0xFF) shl 8)

    private fun ByteArray.toAscii(): String = toString(Charsets.US_ASCII)
}
