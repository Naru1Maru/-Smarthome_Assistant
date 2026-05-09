package com.local.smarthomeassistant

import com.local.smarthomeassistant.data.AppSettings
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MainViewModelStateMergeTest {

    @Test
    fun mergeSnapshotHydratesConversationContextOnlyOnce() {
        val current = UiState(
            gatewayUrl = "http://10.0.2.2:8099",
            apiKey = "test-api-key",
            selectedHomeAreaName = "Спальня",
            lastAreaName = "Спальня",
            selectedTarget = HomeTargetSelection(
                kind = HomeTargetKind.DEVICE_TYPE,
                deviceType = "light",
                controlProfile = "ambient"
            ),
            speechRate = 1.0f,
            speechPitch = 1.0f
        )
        val settings = AppSettings(
            gatewayUrl = "http://10.0.2.2:8109",
            apiKey = "updated-key",
            selectedHomeAreaName = "",
            lastAreaName = "",
            lastEntityIds = emptyList(),
            lastColorName = "",
            lastBrightness = null,
            lastColorTempKelvin = null,
            selectedTargetKind = "device_type",
            selectedTargetDeviceType = "",
            selectedTargetDeviceId = "",
            selectedTargetControlProfile = "",
            asrEngine = "vosk",
            speechRate = 0.9f,
            speechPitch = 1.1f,
            developerModeEnabled = false
        )

        val hydrated = mergeUiStateWithSettingsSnapshot(
            current = current,
            settings = settings,
            hydrateConversationContext = true
        )
        assertEquals("Спальня", hydrated.selectedHomeAreaName)
        assertEquals("Спальня", hydrated.lastAreaName)
        assertEquals("light", hydrated.selectedTarget.deviceType)
        assertEquals("ambient", hydrated.selectedTarget.controlProfile)
        assertEquals("http://10.0.2.2:8109", hydrated.gatewayUrl)
        assertEquals("updated-key", hydrated.apiKey)

        val afterRuntimeSelection = hydrated.copy(selectedHomeAreaName = "Кухня", lastAreaName = "Кухня")
        val mergedStaticOnly = mergeUiStateWithSettingsSnapshot(
            current = afterRuntimeSelection,
            settings = settings.copy(gatewayUrl = "http://10.0.2.2:8110"),
            hydrateConversationContext = false
        )

        assertEquals("Кухня", mergedStaticOnly.selectedHomeAreaName)
        assertEquals("Кухня", mergedStaticOnly.lastAreaName)
        assertEquals("http://10.0.2.2:8110", mergedStaticOnly.gatewayUrl)
        assertTrue(mergedStaticOnly.selectedTarget.deviceType.isNotBlank())
    }
}
