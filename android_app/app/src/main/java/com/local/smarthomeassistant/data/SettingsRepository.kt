package com.local.smarthomeassistant.data

import android.content.Context
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

data class AppSettings(
    val gatewayUrl: String,
    val apiKey: String,
    val selectedHomeAreaName: String,
    val lastAreaName: String,
    val lastEntityIds: List<String>,
    val lastColorName: String,
    val lastBrightness: Int?,
    val lastColorTempKelvin: Int?,
    val selectedTargetKind: String,
    val selectedTargetDeviceType: String,
    val selectedTargetDeviceId: String,
    val selectedTargetControlProfile: String,
    val asrEngine: String,
    val speechRate: Float,
    val speechPitch: Float,
    val developerModeEnabled: Boolean
)

class SettingsRepository(private val ctx: Context) {

    private val prefs = ctx.getSharedPreferences("smarthome_settings", Context.MODE_PRIVATE)
    private val state = MutableStateFlow(readFromPrefs())

    fun settingsFlow(): Flow<AppSettings> = state.asStateFlow()

    suspend fun setGatewayUrl(v: String) {
        prefs.edit().putString("gateway_url", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setApiKey(v: String) {
        prefs.edit().putString("api_key", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setLastAreaName(v: String) {
        prefs.edit().putString("last_area_name", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setSelectedHomeAreaName(v: String) {
        prefs.edit().putString("selected_home_area_name", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setLastEntityIds(v: List<String>) {
        prefs.edit().putString("last_entity_ids", v.joinToString("|")).apply()
        state.value = readFromPrefs()
    }

    suspend fun setLastColorName(v: String?) {
        prefs.edit().putString("last_color_name", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setLastBrightness(v: Int?) {
        val editor = prefs.edit()
        if (v == null) editor.remove("last_brightness") else editor.putInt("last_brightness", v)
        editor.apply()
        state.value = readFromPrefs()
    }

    suspend fun setLastColorTempKelvin(v: Int?) {
        val editor = prefs.edit()
        if (v == null) editor.remove("last_color_temp_kelvin") else editor.putInt("last_color_temp_kelvin", v)
        editor.apply()
        state.value = readFromPrefs()
    }

    suspend fun setSelectedTargetKind(v: String) {
        prefs.edit().putString("selected_target_kind", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setSelectedTargetDeviceType(v: String) {
        prefs.edit().putString("selected_target_device_type", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setSelectedTargetDeviceId(v: String) {
        prefs.edit().putString("selected_target_device_id", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setSelectedTargetControlProfile(v: String) {
        prefs.edit().putString("selected_target_control_profile", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setAsrEngine(v: String) {
        prefs.edit().putString("asr_engine", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setSpeechRate(v: Float) {
        prefs.edit().putFloat("speech_rate", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setSpeechPitch(v: Float) {
        prefs.edit().putFloat("speech_pitch", v).apply()
        state.value = readFromPrefs()
    }

    suspend fun setDeveloperModeEnabled(v: Boolean) {
        prefs.edit().putBoolean("developer_mode_enabled", v).apply()
        state.value = readFromPrefs()
    }

    private fun readFromPrefs(): AppSettings =
        AppSettings(
            gatewayUrl = prefs.getString("gateway_url", "") ?: "",
            apiKey = prefs.getString("api_key", "") ?: "",
            selectedHomeAreaName = prefs.getString("selected_home_area_name", "") ?: "",
            lastAreaName = prefs.getString("last_area_name", "") ?: "",
            lastEntityIds = (prefs.getString("last_entity_ids", "") ?: "")
                .split("|")
                .map { it.trim() }
                .filter { it.isNotBlank() },
            lastColorName = prefs.getString("last_color_name", "") ?: "",
            lastBrightness = if (prefs.contains("last_brightness")) prefs.getInt("last_brightness", 0) else null,
            lastColorTempKelvin = if (prefs.contains("last_color_temp_kelvin")) prefs.getInt("last_color_temp_kelvin", 0) else null,
            selectedTargetKind = prefs.getString("selected_target_kind", "device_type") ?: "device_type",
            selectedTargetDeviceType = prefs.getString("selected_target_device_type", "") ?: "",
            selectedTargetDeviceId = prefs.getString("selected_target_device_id", "") ?: "",
            selectedTargetControlProfile = prefs.getString("selected_target_control_profile", "") ?: "",
            asrEngine = prefs.getString("asr_engine", "vosk") ?: "vosk",
            speechRate = prefs.getFloat("speech_rate", 1.0f),
            speechPitch = prefs.getFloat("speech_pitch", 1.0f),
            developerModeEnabled = prefs.getBoolean("developer_mode_enabled", false)
        )
}
