package com.local.smarthomeassistant.tts

import android.content.Context
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

class TtsEngine(ctx: Context) {

    private val ready = AtomicBoolean(false)
    private val speaking = AtomicBoolean(false)

    private var tts: TextToSpeech? = null
    private var speechRate: Float = 1.0f
    private var speechPitch: Float = 1.0f
    private var onSpeakingChanged: ((Boolean) -> Unit)? = null

    init {
        tts = TextToSpeech(ctx.applicationContext) { status ->
            if (status == TextToSpeech.SUCCESS) {
                val r = tts?.setLanguage(Locale("ru", "RU"))
                val ok = r != TextToSpeech.LANG_MISSING_DATA && r != TextToSpeech.LANG_NOT_SUPPORTED
                ready.set(ok)
                if (ok) {
                    tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                        override fun onStart(utteranceId: String?) {
                            speaking.set(true)
                            onSpeakingChanged?.invoke(true)
                        }

                        override fun onDone(utteranceId: String?) {
                            speaking.set(false)
                            onSpeakingChanged?.invoke(false)
                        }

                        @Deprecated("Deprecated in Java")
                        override fun onError(utteranceId: String?) {
                            speaking.set(false)
                            onSpeakingChanged?.invoke(false)
                        }

                        override fun onError(utteranceId: String?, errorCode: Int) {
                            speaking.set(false)
                            onSpeakingChanged?.invoke(false)
                        }
                    })
                }
                Log.i("TtsEngine", "TTS ready=${ready.get()}")
            } else {
                ready.set(false)
                Log.e("TtsEngine", "TTS init failed: status=$status")
            }
        }
    }

    fun setOnSpeakingChanged(listener: (Boolean) -> Unit) {
        onSpeakingChanged = listener
    }

    fun setParams(rate: Float, pitch: Float) {
        speechRate = rate
        speechPitch = pitch
        val engine = tts ?: return
        if (ready.get()) {
            engine.setSpeechRate(speechRate)
            engine.setPitch(speechPitch)
        }
    }

    fun speak(text: String) {
        val t = text.trim()
        if (t.isBlank()) return

        val engine = tts ?: return
        if (!ready.get()) return

        engine.setSpeechRate(speechRate)
        engine.setPitch(speechPitch)

        val utteranceId = "smarthome_tts_${SystemClock.uptimeMillis()}"
        speaking.set(true)
        onSpeakingChanged?.invoke(true)
        engine.speak(t, TextToSpeech.QUEUE_FLUSH, null, utteranceId)
    }

    fun stop() {
        tts?.stop()
        speaking.set(false)
        onSpeakingChanged?.invoke(false)
    }

    fun close() {
        tts?.stop()
        tts?.shutdown()
        tts = null
    }
}
