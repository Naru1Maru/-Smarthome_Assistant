package com.local.smarthomeassistant

import android.app.Application
import android.os.SystemClock
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.local.smarthomeassistant.asr.AsrEngine
import com.local.smarthomeassistant.asr.AsrEngineType
import com.local.smarthomeassistant.asr.CapturedAudio
import com.local.smarthomeassistant.asr.SherpaAsrEngine
import com.local.smarthomeassistant.asr.SpeechActivityState
import com.local.smarthomeassistant.asr.VoskAsrEngine
import com.local.smarthomeassistant.asr.WavFileCodec
import com.local.smarthomeassistant.data.AppSettings
import com.local.smarthomeassistant.data.SettingsRepository
import com.local.smarthomeassistant.net.DeviceCatalog
import com.local.smarthomeassistant.net.DeviceCatalogDevice
import com.local.smarthomeassistant.net.GatewayCallResult
import com.local.smarthomeassistant.net.GatewayCatalogResult
import com.local.smarthomeassistant.net.GatewayClient
import com.local.smarthomeassistant.net.GatewayResult
import com.local.smarthomeassistant.net.GatewayScenarioDeleteCallResult
import com.local.smarthomeassistant.net.GatewayScenarioDeleteResult
import com.local.smarthomeassistant.net.GatewayScenarioListResult
import com.local.smarthomeassistant.net.GatewayScenarioPreviewCallResult
import com.local.smarthomeassistant.net.GatewayScenarioPreviewResult
import com.local.smarthomeassistant.net.GatewayScenarioSaveCallResult
import com.local.smarthomeassistant.net.GatewayScenarioSaveResult
import com.local.smarthomeassistant.tts.TtsEngine
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class LogKind { INFO, ACTION, ERROR }
enum class VoiceUiState { IDLE, ARMING, LISTENING, FINISHING, RECOGNIZING, ERROR }

enum class HomeTargetKind(val storageValue: String) {
    DEVICE_TYPE("device_type"),
    DEVICE("device");

    companion object {
        fun fromStorage(raw: String?): HomeTargetKind =
            entries.firstOrNull { it.storageValue == raw?.trim()?.lowercase(Locale.US) } ?: DEVICE_TYPE
    }
}

data class HomeTargetSelection(
    val kind: HomeTargetKind = HomeTargetKind.DEVICE_TYPE,
    val deviceType: String = "",
    val deviceId: String = "",
    val controlProfile: String = ""
)

data class LogEntry(
    val timestamp: Long = System.currentTimeMillis(),
    val message: String,
    val kind: LogKind = LogKind.INFO
)

data class RecentCommand(
    val text: String,
    val status: String,
    val timestamp: Long = System.currentTimeMillis()
)

data class ScenarioLibraryEntry(
    val automationId: String,
    val alias: String,
    val triggerSummary: String,
    val actionSummary: String,
    val automationJson: String
)

data class NetworkStatusInfo(
    val label: String = "Не проверено",
    val ok: Boolean = false,
    val latencyMs: Long? = null,
    val checkedAt: Long = 0L,
    val detailLines: List<String> = emptyList()
)

data class UiState(
    val gatewayUrl: String = "",
    val apiKey: String = "",
    val parserMode: String = "rules",
    val dryRun: Boolean = false,
    val developerModeEnabled: Boolean = false,

    val asrReady: Boolean = false,
    val asrEngine: String = AsrEngineType.VOSK.storageValue,
    val voiceUiState: VoiceUiState = VoiceUiState.IDLE,

    val isListening: Boolean = false,
    val isFinishing: Boolean = false,
    val isRecognizing: Boolean = false,
    val busy: Boolean = false,

    val lastAsrText: String = "",
    val lastCommandText: String = "",
    val lastCommandSource: String = "",
    val lastGatewayStatus: String = "",
    val lastSayText: String = "",
    val lastError: String = "",

    val selectedHomeAreaName: String = "",
    val lastAreaName: String = "",
    val lastEntityIds: List<String> = emptyList(),
    val lastColorName: String = "",
    val lastBrightness: Int? = null,
    val lastColorTempKelvin: Int? = null,
    val pendingClarificationSlot: String = "",
    val deviceCatalog: DeviceCatalog? = null,
    val catalogLoading: Boolean = false,
    val catalogError: String = "",
    val selectedTarget: HomeTargetSelection = HomeTargetSelection(),

    val clarificationQuestion: String = "",
    val clarificationOptions: List<String> = emptyList(),
    val pendingOriginalText: String = "",

    val asrMs: Long = 0,
    val netMs: Long = 0,
    val totalMs: Long = 0,

    val audioLevel: Float = 0f,
    val speechDetected: Boolean = false,
    val speechActive: Boolean = false,
    val speechStartOffsetMs: Long = 0,
    val speechEndOffsetMs: Long = 0,
    val releaseToResultMs: Long = 0,
    val lastAsrEmpty: Boolean = false,
    val speechRate: Float = 1.0f,
    val speechPitch: Float = 1.0f,
    val ttsSpeaking: Boolean = false,
    val networkStatus: NetworkStatusInfo = NetworkStatusInfo(),

    val lastGatewayRequestRaw: String = "",
    val lastGatewayResponseRaw: String = "",
    val lastClipWavPath: String = "",
    val lastClipMetadataPath: String = "",
    val lastParserModeUsed: String = "",
    val lastParsedStageSummary: String = "",
    val lastValidatedStageSummary: String = "",
    val lastExecutionStageSummary: String = "",
    val parseStageMs: Long = 0,
    val validateStageMs: Long = 0,
    val executeStageMs: Long = 0,
    val llmStageMs: Long = 0,
    val llmPromptTokens: Int = 0,
    val llmCompletionTokens: Int = 0,
    val llmTotalTokens: Int = 0,
    val llmModel: String = "",
    val scenarioPreviewStatus: String = "",
    val scenarioPreviewSayText: String = "",
    val scenarioPreviewQuestion: String = "",
    val scenarioPreviewTitle: String = "",
    val scenarioPreviewRuleCount: Int = 0,
    val scenarioPreviewAutomationCount: Int = 0,
    val scenarioPreviewParseMs: Long = 0,
    val scenarioPreviewValidateMs: Long = 0,
    val scenarioPreviewCompileMs: Long = 0,
    val scenarioPreviewLlmMs: Long = 0,
    val scenarioPreviewLlmPromptTokens: Int = 0,
    val scenarioPreviewLlmCompletionTokens: Int = 0,
    val scenarioPreviewLlmTotalTokens: Int = 0,
    val scenarioPreviewLlmModel: String = "",
    val scenarioPreviewParsedBundleJson: String = "",
    val scenarioPreviewValidatedBundleJson: String = "",
    val scenarioPreviewAutomationsJson: String = "",
    val scenarioPreviewRequestRaw: String = "",
    val scenarioPreviewResponseRaw: String = "",
    val scenarioSaveStatus: String = "",
    val scenarioSaveSayText: String = "",
    val scenarioSaveSavedAutomationCount: Int = 0,
    val scenarioSaveFileAutomationCount: Int = 0,
    val scenarioSaveStorageFile: String = "",
    val scenarioSaveIncludeDetected: Boolean = false,
    val scenarioSaveReloaded: Boolean = false,
    val scenarioSaveIncludeHint: String = "",
    val scenarioSaveRequestRaw: String = "",
    val scenarioSaveResponseRaw: String = "",
    val scenarioLibraryLoading: Boolean = false,
    val scenarioLibraryError: String = "",
    val scenarioLibraryStorageFile: String = "",
    val scenarioLibraryFileAutomationCount: Int = 0,
    val scenarioLibraryItems: List<ScenarioLibraryEntry> = emptyList(),
    val lastComparisonEngine: String = "",
    val lastComparisonText: String = "",
    val lastComparisonMs: Long = 0,
    val evalHistoryJsonlPath: String = "",
    val evalHistoryCsvPath: String = "",
    val evalHistoryCount: Int = 0,
    val logPreview: String = "",
    val logFilePath: String = "",

    val logs: List<LogEntry> = emptyList(),
    val tipsDismissed: Boolean = false,
    val recentCommands: List<RecentCommand> = emptyList()
)

internal fun mergeUiStateWithSettingsSnapshot(
    current: UiState,
    settings: AppSettings,
    hydrateConversationContext: Boolean
): UiState {
    val asrType = AsrEngineType.fromStorage(settings.asrEngine)
    var next = current.copy(
        gatewayUrl = settings.gatewayUrl,
        apiKey = settings.apiKey,
        asrEngine = asrType.storageValue,
        speechRate = settings.speechRate,
        speechPitch = settings.speechPitch,
        developerModeEnabled = settings.developerModeEnabled
    )
    if (!hydrateConversationContext) {
        return next
    }

    val persistedTarget = HomeTargetSelection(
        kind = HomeTargetKind.fromStorage(settings.selectedTargetKind),
        deviceType = settings.selectedTargetDeviceType,
        deviceId = settings.selectedTargetDeviceId,
        controlProfile = settings.selectedTargetControlProfile
    )
    val hasPersistedTargetSelection = persistedTarget.deviceType.isNotBlank() ||
        persistedTarget.deviceId.isNotBlank() ||
        persistedTarget.controlProfile.isNotBlank()

    next = next.copy(
        selectedHomeAreaName = settings.selectedHomeAreaName.ifBlank {
            current.selectedHomeAreaName.ifBlank { settings.lastAreaName.ifBlank { current.lastAreaName } }
        },
        lastAreaName = settings.lastAreaName.ifBlank { current.lastAreaName },
        lastEntityIds = if (settings.lastEntityIds.isNotEmpty()) settings.lastEntityIds else current.lastEntityIds,
        lastColorName = settings.lastColorName.ifBlank { current.lastColorName },
        lastBrightness = settings.lastBrightness ?: current.lastBrightness,
        lastColorTempKelvin = settings.lastColorTempKelvin ?: current.lastColorTempKelvin,
        selectedTarget = if (hasPersistedTargetSelection) persistedTarget else current.selectedTarget
    )
    return next
}

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private data class LastClipInfo(
        val clipId: String,
        val capturedAtMs: Long,
        val activeAsrType: AsrEngineType,
        val parserMode: String,
        val capturedAudio: CapturedAudio
    )

    private data class DecodeSnapshot(
        val engineType: AsrEngineType,
        val text: String,
        val decodeMs: Long
    )

    private companion object {
        private const val ASR_SAMPLE_RATE = 16_000
        private const val MAX_LISTENING_MS = 10_000L
        private const val FINISHING_MIN_MS = 120L
        private const val FINISHING_MAX_MS = 800L
        private const val FINISHING_SILENCE_MS = 220L
        private const val FINISHING_POLL_MS = 40L
        private const val FINISHING_SPEECH_LEVEL_THRESHOLD = 0.015f
        private const val MIN_CAPTURE_DURATION_MS = 350L
        private const val MIN_SPEECH_DURATION_MS = 180L
        private const val MIN_PEAK_LEVEL = 0.018f
    }

    private val settings = SettingsRepository(app.applicationContext)
    private val gateway = GatewayClient()
    private val tts = TtsEngine(app.applicationContext)
    private val logFile = File(app.applicationContext.filesDir, "asr_diagnostics.log")
    private val recentCommandsFile = File(app.applicationContext.filesDir, "recent_commands.json")
    private val lastClipWavFile = File(app.applicationContext.filesDir, "last_voice_clip.wav")
    private val lastClipMetadataFile = File(app.applicationContext.filesDir, "last_voice_clip.json")
    private val evalHistoryJsonlFile = File(app.applicationContext.filesDir, "voice_eval_history.jsonl")
    private val evalHistoryCsvFile = File(app.applicationContext.filesDir, "voice_eval_history.csv")
    private val logFormatter = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)

    private val asrEngines: Map<AsrEngineType, AsrEngine> = mapOf(
        AsrEngineType.VOSK to VoskAsrEngine(
            appContext = app.applicationContext,
            modelAssetDir = "models/vosk-model-small-ru-0.22"
        ),
        AsrEngineType.SHERPA to SherpaAsrEngine(
            appContext = app.applicationContext,
            modelAssetDir = "models/sherpa-onnx-small-zipformer-ru-2024-09-18"
        )
    )

    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui.asStateFlow()
    private var listenWatchdogJob: Job? = null
    private var pendingStopJob: Job? = null
    private var asrPrepareJob: Job? = null
    private var stopDecodeJob: Job? = null
    private var listeningStartedAtMs: Long = 0
    private var lastVoiceActivityAtMs: Long = 0
    private var speechEndedRealtimeAtMs: Long = 0
    private var stopRequestedAtMs: Long = 0
    private var lastClipInfo: LastClipInfo? = null
    private var activeAsrType = AsrEngineType.VOSK
    private var observedAsrType: AsrEngineType? = null
    private var attemptedInitialCatalogLoad = false
    private var settingsContextHydrated = false

    init {
        _ui.value = _ui.value.copy(
            recentCommands = loadRecentCommands(),
            logFilePath = logFile.absolutePath,
            lastClipWavPath = if (lastClipWavFile.exists()) lastClipWavFile.absolutePath else "",
            lastClipMetadataPath = if (lastClipMetadataFile.exists()) lastClipMetadataFile.absolutePath else "",
            evalHistoryJsonlPath = if (evalHistoryJsonlFile.exists()) evalHistoryJsonlFile.absolutePath else "",
            evalHistoryCsvPath = if (evalHistoryCsvFile.exists()) evalHistoryCsvFile.absolutePath else "",
            evalHistoryCount = loadEvalHistoryCount()
        )
        refreshLogPreview()
        tts.setOnSpeakingChanged { isSpeaking ->
            viewModelScope.launch {
                _ui.value = _ui.value.copy(ttsSpeaking = isSpeaking)
            }
        }

        viewModelScope.launch(Dispatchers.Main.immediate) {
            settings.settingsFlow().collect { s ->
                val asrType = AsrEngineType.fromStorage(s.asrEngine)
                _ui.value = mergeUiStateWithSettingsSnapshot(
                    current = _ui.value,
                    settings = s,
                    hydrateConversationContext = !settingsContextHydrated
                )
                settingsContextHydrated = true
                tts.setParams(s.speechRate, s.speechPitch)
                if (observedAsrType != asrType) {
                    observedAsrType = asrType
                    switchAsrEngine(asrType)
                }
                if (!attemptedInitialCatalogLoad && s.gatewayUrl.isNotBlank()) {
                    attemptedInitialCatalogLoad = true
                    refreshDeviceCatalog(silent = true)
                    refreshScenarioLibrary(silent = true)
                }
            }
        }
    }

    fun dismissTips() {
        if (!_ui.value.tipsDismissed) {
            _ui.value = _ui.value.copy(tipsDismissed = true)
        }
    }

    fun onGatewayUrlChanged(v: String) {
        val vv = v.trim()
        _ui.value = _ui.value.copy(
            gatewayUrl = vv,
            deviceCatalog = null,
            catalogError = ""
        )
        viewModelScope.launch { settings.setGatewayUrl(vv) }
    }

    fun onApiKeyChanged(v: String) {
        val vv = v.trim()
        _ui.value = _ui.value.copy(
            apiKey = vv,
            deviceCatalog = null,
            catalogError = ""
        )
        viewModelScope.launch { settings.setApiKey(vv) }
    }

    fun selectHomeArea(area: String) {
        val trimmed = area.trim()
        if (trimmed.isBlank()) return

        val nextState = _ui.value.copy(
            selectedHomeAreaName = trimmed,
            lastAreaName = trimmed,
            lastEntityIds = emptyList()
        )
        val nextTarget = reconcileSelectedTarget(
            catalog = nextState.deviceCatalog,
            areaName = trimmed,
            contextEntityIds = emptyList(),
            current = nextState.selectedTarget
        )
        _ui.value = nextState.copy(selectedTarget = nextTarget)
        appendLog("Выбрана комната: $trimmed", LogKind.INFO)
        viewModelScope.launch {
            settings.setSelectedHomeAreaName(trimmed)
            settings.setLastAreaName(trimmed)
            settings.setLastEntityIds(emptyList())
            persistSelectedTarget(nextTarget)
        }
    }

    fun refreshDeviceCatalog() {
        refreshDeviceCatalog(silent = false)
    }

    fun selectHomeTargetDeviceType(deviceType: String) {
        val normalized = deviceType.trim().lowercase(Locale.US)
        if (normalized.isBlank()) return
        val state = _ui.value
        val areaName = selectedHomeAreaName(state)
        val catalog = state.deviceCatalog ?: return
        val hasType = catalog.devices.any { it.areaName == areaName && it.deviceType == normalized }
        if (!hasType) return
        val next = HomeTargetSelection(
            kind = HomeTargetKind.DEVICE_TYPE,
            deviceType = normalized,
            deviceId = "",
            controlProfile = ""
        )
        _ui.value = state.copy(
            selectedTarget = next,
            lastEntityIds = emptyList()
        )
        viewModelScope.launch {
            settings.setLastEntityIds(emptyList())
            persistSelectedTarget(next)
        }
    }

    fun selectHomeTargetDevice(deviceId: String) {
        val trimmed = deviceId.trim()
        if (trimmed.isBlank()) return
        val state = _ui.value
        val areaName = selectedHomeAreaName(state)
        val device = state.deviceCatalog
            ?.devices
            ?.firstOrNull { it.deviceId == trimmed && it.areaName == areaName }
            ?: return
        val next = HomeTargetSelection(
            kind = HomeTargetKind.DEVICE,
            deviceType = device.deviceType,
            deviceId = device.deviceId,
            controlProfile = device.controlProfile
        )
        val entityIds = listOfNotNull(device.entityId)
        _ui.value = state.copy(
            selectedTarget = next,
            lastEntityIds = entityIds
        )
        viewModelScope.launch {
            settings.setLastEntityIds(entityIds)
            persistSelectedTarget(next)
        }
    }

    fun selectHomeTargetControlProfile(profileId: String) {
        val normalized = profileId.trim().lowercase(Locale.US)
        val state = _ui.value
        val areaName = selectedHomeAreaName(state)
        val catalog = state.deviceCatalog ?: return
        val selectedType = state.selectedTarget.deviceType.trim().lowercase(Locale.US)
        if (selectedType.isBlank()) return
        val availableProfiles = catalog.areas
            .firstOrNull { it.name == areaName }
            ?.targetProfiles
            ?.filter { it.deviceType == selectedType }
            ?.map { it.profileId }
            .orEmpty()
        if (normalized.isNotBlank() && normalized !in availableProfiles) return

        val next = state.selectedTarget.copy(
            kind = HomeTargetKind.DEVICE_TYPE,
            deviceId = "",
            controlProfile = normalized
        )
        _ui.value = state.copy(
            selectedTarget = next,
            lastEntityIds = emptyList()
        )
        viewModelScope.launch {
            settings.setLastEntityIds(emptyList())
            persistSelectedTarget(next)
        }
    }

    fun sendTextCommand(text: String) {
        val trimmed = text.trim()
        if (trimmed.isBlank()) return
        clearClarification()
        sendText(trimmed, originalText = trimmed, asrMs = 0, commandSource = "text")
    }

    fun runHomeQuickAction(
        actionId: String,
        areaName: String,
        deviceType: String,
        deviceId: String?
    ) {
        val normalizedAction = actionId.trim().uppercase(Locale.US)
        val normalizedDeviceType = deviceType.trim().lowercase(Locale.US)
        val normalizedArea = areaName.trim()
        val normalizedDeviceId = deviceId?.trim()?.takeIf { it.isNotBlank() }
        if (normalizedAction.isBlank() || normalizedDeviceType.isBlank()) return

        val state = _ui.value
        val baseUrl = state.gatewayUrl.trim()
        val apiKey = state.apiKey.trim()
        if (baseUrl.isBlank()) {
            setError("Не задан Gateway URL")
            return
        }
        if (apiKey.isBlank()) {
            setError("Не задан X-API-Key")
            return
        }

        val actionText = buildQuickActionDisplayText(
            actionId = normalizedAction,
            areaName = normalizedArea,
            deviceType = normalizedDeviceType,
            deviceId = normalizedDeviceId
        )
        appendLog("Быстрое действие: $actionText", LogKind.ACTION)
        beginGatewayCommand(commandText = actionText, commandSource = "quick")

        viewModelScope.launch {
            setBusy(true)
            val startedAtMs = System.currentTimeMillis()
            try {
                val envelope = withContext(Dispatchers.IO) {
                    gateway.sendQuickAction(
                        baseUrl = baseUrl,
                        apiKey = apiKey,
                        actionId = normalizedAction,
                        dryRun = state.dryRun,
                        areaName = normalizedArea.ifBlank { null },
                        deviceType = normalizedDeviceType,
                        deviceId = normalizedDeviceId
                    )
                }
                applyGatewayEnvelope(
                    envelope = envelope,
                    originalText = actionText,
                    asrMs = 0,
                    commandSource = "quick",
                    startedAtMs = startedAtMs
                )
            } finally {
                setBusy(false)
            }
        }
    }

    fun onDryRunChanged(v: Boolean) {
        _ui.value = _ui.value.copy(dryRun = v)
        appendLog("dry_run=${if (v) "ON" else "OFF"}", LogKind.ACTION)
    }

    fun onAsrEngineChanged(value: String) {
        if (_ui.value.isListening || _ui.value.isRecognizing) return
        val type = AsrEngineType.fromStorage(value)
        if (_ui.value.asrEngine == type.storageValue) return
        _ui.value = _ui.value.copy(asrEngine = type.storageValue, asrReady = false)
        appendLog("ASR engine -> ${type.label}", LogKind.ACTION)
        viewModelScope.launch { settings.setAsrEngine(type.storageValue) }
    }

    fun onSpeechRateChanged(value: Float) {
        val clamped = value.coerceIn(0.5f, 1.5f)
        _ui.value = _ui.value.copy(speechRate = clamped)
        tts.setParams(clamped, _ui.value.speechPitch)
        viewModelScope.launch { settings.setSpeechRate(clamped) }
    }

    fun onSpeechPitchChanged(value: Float) {
        val clamped = value.coerceIn(0.5f, 1.5f)
        _ui.value = _ui.value.copy(speechPitch = clamped)
        tts.setParams(_ui.value.speechRate, clamped)
        viewModelScope.launch { settings.setSpeechPitch(clamped) }
    }

    fun stopTts() {
        tts.stop()
    }

    fun onParserModeChanged(mode: String) {
        val normalized = when (mode.trim().lowercase()) {
            "rules" -> "rules"
            "llm", "ml", "ai" -> "llm"
            "llm_safe", "safe" -> "llm_safe"
            else -> "rules"
        }
        if (_ui.value.parserMode == normalized) return
        _ui.value = _ui.value.copy(parserMode = normalized)
        appendLog("Parser mode -> $normalized", LogKind.ACTION)
    }

    fun onDeveloperModeChanged(enabled: Boolean) {
        _ui.value = _ui.value.copy(developerModeEnabled = enabled)
        viewModelScope.launch { settings.setDeveloperModeEnabled(enabled) }
        appendLog("Developer mode -> ${if (enabled) "ON" else "OFF"}", LogKind.INFO)
    }

    fun pingGateway() {
        val state = _ui.value
        val base = state.gatewayUrl.trim()
        if (base.isBlank()) {
            setError("Не задан Gateway URL")
            return
        }
        viewModelScope.launch {
            updateNetworkStatus(
                ok = false,
                message = "Проверка соединения...",
                latencyMs = null
            )
            val result = withContext(Dispatchers.IO) {
                gateway.ping(base, state.apiKey.trim(), liveMode = !state.dryRun)
            }
            updateNetworkStatus(result.ok, result.message, result.latencyMs, result.detailLines)
            if (result.gatewayReachable) {
                refreshDeviceCatalog(silent = true)
            }
        }
    }

    private fun refreshDeviceCatalog(silent: Boolean) {
        val state = _ui.value
        val base = state.gatewayUrl.trim()
        if (base.isBlank()) return

        viewModelScope.launch {
            _ui.value = _ui.value.copy(
                catalogLoading = true,
                catalogError = ""
            )
            when (val result = withContext(Dispatchers.IO) {
                gateway.fetchCatalog(base, state.apiKey.trim())
            }) {
                is GatewayCatalogResult.Ok -> {
                    val reconciled = reconcileSelectedTarget(
                        catalog = result.catalog,
                        areaName = selectedHomeAreaName(_ui.value),
                        contextEntityIds = _ui.value.lastEntityIds,
                        current = _ui.value.selectedTarget
                    )
                    _ui.value = _ui.value.copy(
                        deviceCatalog = result.catalog,
                        catalogLoading = false,
                        catalogError = "",
                        selectedTarget = reconciled
                    )
                    persistSelectedTarget(reconciled)
                    if (!silent) {
                        appendLog(
                            "Каталог устройств обновлён: ${result.catalog.devices.size} устройств",
                            LogKind.INFO
                        )
                    }
                }

                is GatewayCatalogResult.Error -> {
                    _ui.value = _ui.value.copy(
                        catalogLoading = false,
                        catalogError = result.message
                    )
                    if (!silent) {
                        appendLog("Не удалось загрузить каталог устройств: ${result.message}", LogKind.ERROR)
                    }
                }
            }
        }
    }

    private suspend fun persistSelectedTarget(target: HomeTargetSelection) {
        settings.setSelectedTargetKind(target.kind.storageValue)
        settings.setSelectedTargetDeviceType(target.deviceType)
        settings.setSelectedTargetDeviceId(target.deviceId)
        settings.setSelectedTargetControlProfile(target.controlProfile)
    }

    private fun reconcileSelectedTarget(
        catalog: DeviceCatalog?,
        areaName: String,
        contextEntityIds: List<String>,
        current: HomeTargetSelection
    ): HomeTargetSelection {
        if (areaName.isBlank()) {
            return HomeTargetSelection()
        }
        if (catalog == null) {
            return if (current.kind == HomeTargetKind.DEVICE) {
                current.copy(kind = HomeTargetKind.DEVICE_TYPE, deviceId = "")
            } else {
                current
            }
        }

        val devicesInArea = catalog.devices.filter { it.areaName == areaName }
        if (devicesInArea.isEmpty()) {
            return HomeTargetSelection()
        }

        if (current.kind == HomeTargetKind.DEVICE && current.deviceId.isNotBlank()) {
            val currentDevice = devicesInArea.firstOrNull { it.deviceId == current.deviceId }
            if (currentDevice != null) {
                return current.copy(
                    deviceType = currentDevice.deviceType,
                    controlProfile = currentDevice.controlProfile
                )
            }
        }

        if (current.kind == HomeTargetKind.DEVICE_TYPE && current.deviceType.isNotBlank()) {
            val devicesOfCurrentType = devicesInArea.filter { it.deviceType == current.deviceType }
            val hasCurrentType = devicesOfCurrentType.isNotEmpty()
            if (hasCurrentType) {
                val availableProfiles = devicesOfCurrentType
                    .map { it.controlProfile }
                    .distinct()
                val nextProfile = current.controlProfile.takeIf { it.isBlank() || it in availableProfiles }.orEmpty()
                return current.copy(deviceId = "", controlProfile = nextProfile)
            }
        }

        val contextDevice = resolveContextDevice(devicesInArea, contextEntityIds)
        if (contextDevice != null) {
            return HomeTargetSelection(
                kind = HomeTargetKind.DEVICE,
                deviceType = contextDevice.deviceType,
                deviceId = contextDevice.deviceId,
                controlProfile = contextDevice.controlProfile
            )
        }

        val preferredType = devicesInArea
            .map { it.deviceType }
            .distinct()
            .sortedBy(::deviceTypePriority)
            .firstOrNull()
            .orEmpty()

        return HomeTargetSelection(
            kind = HomeTargetKind.DEVICE_TYPE,
            deviceType = preferredType,
            deviceId = "",
            controlProfile = ""
        )
    }

    private fun resolveContextDevice(
        devicesInArea: List<DeviceCatalogDevice>,
        contextEntityIds: List<String>
    ): DeviceCatalogDevice? {
        if (contextEntityIds.isEmpty()) return null
        return contextEntityIds
            .asSequence()
            .mapNotNull { entityId -> devicesInArea.firstOrNull { it.entityId == entityId } }
            .firstOrNull()
    }

    private fun deviceTypePriority(deviceType: String): Int =
        when (deviceType.trim().lowercase(Locale.US)) {
            "light" -> 0
            "switch" -> 1
            else -> 9
        }

    private fun controlProfilePriority(profileId: String): Int =
        when (profileId.trim().lowercase(Locale.US)) {
            "color_scene" -> 0
            "tunable_white" -> 1
            "dimmable" -> 2
            "power_only" -> 3
            else -> 9
        }

    fun resendRecentCommand(text: String) {
        val trimmed = text.trim()
        if (trimmed.isBlank()) return
        clearClarification()
        appendLog("Повтор команды: $trimmed", LogKind.ACTION)
        sendText(trimmed, originalText = trimmed, asrMs = 0, commandSource = "text")
    }

    fun clearLogs() {
        _ui.value = _ui.value.copy(logs = emptyList())
    }

    fun startListening() {
        val state = _ui.value
        if (!state.asrReady || state.busy || state.isListening || state.isRecognizing) return

        pendingStopJob?.cancel()
        pendingStopJob = null
        listeningStartedAtMs = SystemClock.elapsedRealtime()
        lastVoiceActivityAtMs = listeningStartedAtMs
        speechEndedRealtimeAtMs = 0L
        stopRequestedAtMs = 0L

        _ui.value = state.copy(
            voiceUiState = VoiceUiState.ARMING,
            isListening = true,
            isFinishing = false,
            isRecognizing = false,
            lastError = "",
            lastAsrText = "",
            lastGatewayStatus = "",
            lastSayText = "",
            lastGatewayRequestRaw = "",
            lastGatewayResponseRaw = "",
            lastParserModeUsed = "",
            lastParsedStageSummary = "",
            lastValidatedStageSummary = "",
            lastExecutionStageSummary = "",
            parseStageMs = 0,
            validateStageMs = 0,
            executeStageMs = 0,
            llmStageMs = 0,
            llmPromptTokens = 0,
            llmCompletionTokens = 0,
            llmTotalTokens = 0,
            llmModel = "",
            netMs = 0,
            totalMs = 0,
            lastComparisonEngine = "",
            lastComparisonText = "",
            lastComparisonMs = 0,
            releaseToResultMs = 0L,
            lastAsrEmpty = false,
            audioLevel = 0f,
            speechDetected = false,
            speechActive = false,
            speechStartOffsetMs = 0L,
            speechEndOffsetMs = 0L
        )
        appendLog("Голосовой режим: запуск (${activeAsrType.label})", LogKind.ACTION)
        startListenWatchdog()

        currentAsr().startListening(
            onPartial = { /* ignore */ },
            onFinal = { _, _ -> },
            onError = { msg ->
                viewModelScope.launch {
                    _ui.value = _ui.value.copy(
                        voiceUiState = VoiceUiState.ERROR,
                        isListening = false,
                        isFinishing = false,
                        audioLevel = 0f
                    )
                    setError("ASR: $msg")
                }
            },
            onAudioLevel = ::handleAudioLevel,
            onSpeechActivityChanged = ::handleSpeechActivity
        )
    }

    fun requestStopListening() {
        val state = _ui.value
        if (!state.isListening || state.isFinishing) return
        pendingStopJob?.cancel()
        stopRequestedAtMs = SystemClock.elapsedRealtime()
        _ui.value = state.copy(
            voiceUiState = VoiceUiState.FINISHING,
            isFinishing = true
        )
        val finishingStartedAtMs = SystemClock.elapsedRealtime()
        pendingStopJob = viewModelScope.launch {
            while (isActive) {
                delay(FINISHING_POLL_MS)
                val current = _ui.value
                if (!current.isListening) break

                val now = SystemClock.elapsedRealtime()
                val finishingElapsed = now - finishingStartedAtMs
                val silenceElapsed = now - lastVoiceActivityAtMs
                val reachedSpeechEndStop =
                    finishingElapsed >= FINISHING_MIN_MS &&
                        current.speechDetected &&
                        !current.speechActive &&
                        speechEndedRealtimeAtMs > 0L &&
                        current.speechEndOffsetMs > 0L
                val reachedSilenceStop =
                    finishingElapsed >= FINISHING_MIN_MS &&
                        silenceElapsed >= FINISHING_SILENCE_MS
                val reachedHardStop = finishingElapsed >= FINISHING_MAX_MS

                if (reachedSpeechEndStop || reachedSilenceStop || reachedHardStop) {
                    stopListening()
                    break
                }
            }
        }
    }

    fun stopListening() {
        val state = _ui.value
        if (!state.isListening) return
        pendingStopJob?.cancel()
        pendingStopJob = null
        listenWatchdogJob?.cancel()
        listenWatchdogJob = null

        val asr = currentAsr()
        val primaryAsrType = activeAsrType
        val asrLabel = primaryAsrType.label
        val releaseStartedAtMs = if (stopRequestedAtMs > 0L) {
            stopRequestedAtMs
        } else {
            SystemClock.elapsedRealtime().also { stopRequestedAtMs = it }
        }
        _ui.value = state.copy(
            voiceUiState = VoiceUiState.RECOGNIZING,
            isListening = false,
            isFinishing = false,
            isRecognizing = true,
            audioLevel = 0f
        )
        appendLog("Голосовой режим: распознавание ($asrLabel)", LogKind.ACTION)

        stopDecodeJob?.cancel()
        val job = viewModelScope.launch {
            try {
                val capturedAudio = withContext(Dispatchers.Default) {
                    asr.stopListening(deliverFinal = false)
                }
                if (capturedAudio != null) {
                    appendLog(
                        "Segmenter: speech=${if (capturedAudio.speechDetected) "YES" else "NO"} speechMs=${capturedAudio.speechDurationMs} trimStartMs=${capturedAudio.leadingTrimMs} trimEndMs=${capturedAudio.trailingTrimMs}",
                        LogKind.INFO
                    )
                    saveLastClipArtifacts(primaryAsrType, capturedAudio)
                    val primaryDecode = decodeCapturedAudio(primaryAsrType, capturedAudio)
                    val releaseToResultMs = SystemClock.elapsedRealtime() - releaseStartedAtMs
                    _ui.value = _ui.value.copy(
                        voiceUiState = VoiceUiState.RECOGNIZING,
                        lastAsrText = primaryDecode.text,
                        asrMs = primaryDecode.decodeMs,
                        releaseToResultMs = releaseToResultMs,
                        lastAsrEmpty = primaryDecode.text.isBlank()
                    )
                    appendLog("ASR ${primaryDecode.engineType.label}: ${primaryDecode.text.ifBlank { "<empty>" }}", LogKind.ACTION)
                    appendAttemptMetricsLog(capturedAudio, releaseToResultMs, primaryDecode.text.isBlank())
                    writeLastClipMetadata(primaryDecode = primaryDecode)
                    compareCapturedAudio(primaryAsrType, capturedAudio)
                    val validationError = validateVoiceAttempt(capturedAudio, primaryDecode.text)
                    when (validationError) {
                        null -> sendText(
                            text = primaryDecode.text,
                            originalText = primaryDecode.text,
                            asrMs = primaryDecode.decodeMs,
                            commandSource = "voice"
                        )
                        else -> {
                            appendEvaluationRecord(runType = "voice")
                            setError(validationError)
                        }
                    }
                } else {
                    setError("ASR: no captured audio")
                }
            } catch (e: Exception) {
                _ui.value = _ui.value.copy(
                    isRecognizing = false,
                    audioLevel = 0f
                )
                setError("ASR stop error: ${e.message}")
                return@launch
            }

            _ui.value = _ui.value.copy(
                voiceUiState = if (_ui.value.lastError.isBlank()) VoiceUiState.IDLE else VoiceUiState.ERROR,
                isRecognizing = false,
                audioLevel = 0f
            )
            stopRequestedAtMs = 0L
        }
        job.invokeOnCompletion {
            if (stopDecodeJob === job) {
                stopDecodeJob = null
            }
        }
        stopDecodeJob = job
    }

    fun toggleListening() {
        if (_ui.value.isListening) stopListening() else startListening()
    }

    fun cancelListening() {
        if (!_ui.value.isListening) return
        pendingStopJob?.cancel()
        pendingStopJob = null
        listenWatchdogJob?.cancel()
        listenWatchdogJob = null
        stopRequestedAtMs = 0L
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.Default) {
                    currentAsr().stopListening(deliverFinal = false)
                }
            }
            _ui.value = _ui.value.copy(
                voiceUiState = VoiceUiState.IDLE,
                isListening = false,
                isFinishing = false,
                isRecognizing = false,
                audioLevel = 0f,
                speechDetected = false,
                speechActive = false
            )
            appendLog("Voice capture cancelled", LogKind.ACTION)
        }
    }

    fun sendDevText(text: String) {
        sendTextCommand(text)
    }

    fun previewScenario(text: String) {
        val trimmed = text.trim()
        if (trimmed.isBlank()) return

        val state = _ui.value
        val baseUrl = state.gatewayUrl.trim()
        val apiKey = state.apiKey.trim()

        if (baseUrl.isBlank()) {
            setError("Не задан Gateway URL")
            return
        }
        if (apiKey.isBlank()) {
            setError("Не задан X-API-Key")
            return
        }

        appendLog("Предпросмотр сценария: \"$trimmed\"", LogKind.ACTION)
        beginScenarioPreview(text = trimmed)

        viewModelScope.launch {
            setBusy(true)
            val startedAtMs = System.currentTimeMillis()
            try {
                val envelope = withContext(Dispatchers.IO) {
                    gateway.previewScenario(
                        baseUrl = baseUrl,
                        apiKey = apiKey,
                        text = trimmed,
                        selectedAreaName = state.selectedHomeAreaName.trim().ifBlank { null },
                        lastAreaName = selectedHomeAreaName(state).ifBlank { state.lastAreaName.trim() }.ifBlank { null },
                        lastEntityIds = state.lastEntityIds
                    )
                }
                applyScenarioPreviewEnvelope(envelope = envelope, startedAtMs = startedAtMs)
            } finally {
                setBusy(false)
            }
        }
    }

    fun saveScenarioPreview() {
        val state = _ui.value
        val baseUrl = state.gatewayUrl.trim()
        val apiKey = state.apiKey.trim()

        if (baseUrl.isBlank()) {
            setError("Не задан Gateway URL")
            return
        }
        if (apiKey.isBlank()) {
            setError("Не задан X-API-Key")
            return
        }
        if (state.scenarioPreviewStatus != "PREVIEW_READY" ||
            state.scenarioPreviewAutomationCount <= 0 ||
            state.scenarioPreviewAutomationsJson.isBlank()
        ) {
            _ui.value = _ui.value.copy(
                scenarioSaveStatus = "ERROR",
                scenarioSaveSayText = "Нет подготовленного сценария для сохранения."
            )
            appendLog("Scenario save skipped: preview result is empty", LogKind.ERROR)
            return
        }

        appendLog("Сохранение сценария в Home Assistant", LogKind.ACTION)
        beginScenarioSave()

        viewModelScope.launch {
            setBusy(true)
            val startedAtMs = System.currentTimeMillis()
            try {
                val envelope = withContext(Dispatchers.IO) {
                    gateway.saveScenario(
                        baseUrl = baseUrl,
                        apiKey = apiKey,
                        validatedBundleJson = state.scenarioPreviewValidatedBundleJson.ifBlank { null },
                        automationsJson = state.scenarioPreviewAutomationsJson
                    )
                }
                applyScenarioSaveEnvelope(envelope = envelope, startedAtMs = startedAtMs)
            } finally {
                setBusy(false)
            }
        }
    }

    fun refreshScenarioLibrary(silent: Boolean = false) {
        val state = _ui.value
        val baseUrl = state.gatewayUrl.trim()
        val apiKey = state.apiKey.trim()
        if (baseUrl.isBlank() || apiKey.isBlank()) {
            if (!silent) {
                setError("Нужны Gateway URL и X-API-Key")
            }
            return
        }

        viewModelScope.launch {
            _ui.value = _ui.value.copy(
                scenarioLibraryLoading = true,
                scenarioLibraryError = ""
            )
            val startedAtMs = System.currentTimeMillis()
            val envelope = withContext(Dispatchers.IO) {
                gateway.listScenarios(baseUrl = baseUrl, apiKey = apiKey)
            }
            val netMs = System.currentTimeMillis() - startedAtMs
            when (val res = envelope.result) {
                is GatewayScenarioListResult.Ok -> {
                    _ui.value = _ui.value.copy(
                        scenarioLibraryLoading = false,
                        scenarioLibraryError = "",
                        scenarioLibraryStorageFile = res.storageFile.orEmpty(),
                        scenarioLibraryFileAutomationCount = res.fileAutomationCount,
                        scenarioLibraryItems = res.items.map {
                            ScenarioLibraryEntry(
                                automationId = it.automationId,
                                alias = it.alias,
                                triggerSummary = it.triggerSummary,
                                actionSummary = it.actionSummary,
                                automationJson = it.automationJson
                            )
                        },
                        netMs = netMs,
                        totalMs = netMs
                    )
                    if (!silent) {
                        appendLog("Сценарии загружены: ${res.items.size}", LogKind.INFO)
                    }
                }

                is GatewayScenarioListResult.Error -> {
                    _ui.value = _ui.value.copy(
                        scenarioLibraryLoading = false,
                        scenarioLibraryError = res.message,
                        netMs = netMs,
                        totalMs = netMs
                    )
                    if (!silent) {
                        appendLog("Scenario list error: ${res.message}", LogKind.ERROR)
                    }
                }
            }
        }
    }

    fun upsertScenarioFromJson(automationJson: String) {
        val state = _ui.value
        val baseUrl = state.gatewayUrl.trim()
        val apiKey = state.apiKey.trim()

        if (baseUrl.isBlank()) {
            setError("Не задан Gateway URL")
            return
        }
        if (apiKey.isBlank()) {
            setError("Не задан X-API-Key")
            return
        }

        val normalizedJson = try {
            val obj = JSONObject(automationJson)
            val automationId = obj.optString("id", "").trim()
            if (automationId.isBlank()) {
                setError("В JSON сценария отсутствует поле id")
                return
            }
            obj.toString()
        } catch (_: Exception) {
            setError("Некорректный JSON сценария")
            return
        }

        appendLog("Обновление сценария вручную", LogKind.ACTION)
        beginScenarioSave()
        viewModelScope.launch {
            setBusy(true)
            val startedAtMs = System.currentTimeMillis()
            try {
                val envelope = withContext(Dispatchers.IO) {
                    gateway.upsertScenario(
                        baseUrl = baseUrl,
                        apiKey = apiKey,
                        automationJson = normalizedJson
                    )
                }
                applyScenarioSaveEnvelope(envelope = envelope, startedAtMs = startedAtMs)
                if (envelope.result is GatewayScenarioSaveResult.Ok) {
                    refreshScenarioLibrary(silent = true)
                }
            } finally {
                setBusy(false)
            }
        }
    }

    fun deleteScenarioById(automationId: String) {
        val id = automationId.trim()
        if (id.isBlank()) return
        val state = _ui.value
        val baseUrl = state.gatewayUrl.trim()
        val apiKey = state.apiKey.trim()
        if (baseUrl.isBlank()) {
            setError("Не задан Gateway URL")
            return
        }
        if (apiKey.isBlank()) {
            setError("Не задан X-API-Key")
            return
        }

        appendLog("Удаление сценария: $id", LogKind.ACTION)
        viewModelScope.launch {
            setBusy(true)
            val startedAtMs = System.currentTimeMillis()
            try {
                val envelope = withContext(Dispatchers.IO) {
                    gateway.deleteScenario(
                        baseUrl = baseUrl,
                        apiKey = apiKey,
                        automationId = id
                    )
                }
                applyScenarioDeleteEnvelope(envelope = envelope, startedAtMs = startedAtMs)
                if (envelope.result is GatewayScenarioDeleteResult.Ok) {
                    refreshScenarioLibrary(silent = true)
                }
            } finally {
                setBusy(false)
            }
        }
    }

    fun rerunLastSavedClipComparison() {
        if (_ui.value.isListening || _ui.value.isRecognizing || _ui.value.busy) return
        if (!lastClipWavFile.exists()) {
            setError("No saved voice clip")
            return
        }

        viewModelScope.launch {
            _ui.value = _ui.value.copy(
                voiceUiState = VoiceUiState.RECOGNIZING,
                isRecognizing = true,
                lastError = ""
            )
            try {
                val decoded = withContext(Dispatchers.IO) {
                    WavFileCodec.readMonoPcm16(lastClipWavFile)
                }
                require(decoded.sampleRate == ASR_SAMPLE_RATE) {
                    "Unsupported clip sample rate: ${decoded.sampleRate}"
                }

                val capturedAudio = CapturedAudio(
                    samples = decoded.samples,
                    durationMs = (decoded.samples.size * 1000L) / ASR_SAMPLE_RATE,
                    speechDurationMs = (decoded.samples.size * 1000L) / ASR_SAMPLE_RATE,
                    speechDetected = true
                )
                saveLastClipArtifacts(activeAsrType, capturedAudio)

                val primaryDecode = decodeCapturedAudio(activeAsrType, capturedAudio)
                _ui.value = _ui.value.copy(
                    lastAsrText = primaryDecode.text,
                    asrMs = primaryDecode.decodeMs,
                    releaseToResultMs = 0L,
                    lastAsrEmpty = primaryDecode.text.isBlank(),
                    lastComparisonEngine = "",
                    lastComparisonText = "",
                    lastComparisonMs = 0
                )
                writeLastClipMetadata(primaryDecode = primaryDecode)
                compareCapturedAudio(activeAsrType, capturedAudio)
                appendEvaluationRecord(runType = "rerun")
                appendLog("Rerun clip with ${primaryDecode.engineType.label}: ${primaryDecode.text.ifBlank { "<empty>" }}", LogKind.ACTION)
            } catch (e: Exception) {
                setError("Clip rerun error: ${e.message}")
            } finally {
                _ui.value = _ui.value.copy(
                    voiceUiState = if (_ui.value.lastError.isBlank()) VoiceUiState.IDLE else VoiceUiState.ERROR,
                    isRecognizing = false
                )
            }
        }
    }

    fun selectClarificationOption(option: String) {
        val state = _ui.value
        if (state.pendingOriginalText.isBlank()) return
        val followup = "${state.pendingOriginalText} $option".trim()
        clearClarification()
        appendLog("Выбор уточнения: $option", LogKind.ACTION)
        sendText(followup, originalText = followup, asrMs = 0, commandSource = "text")
    }

    private fun clearClarification() {
        _ui.value = _ui.value.copy(
            clarificationQuestion = "",
            clarificationOptions = emptyList(),
            pendingOriginalText = "",
            pendingClarificationSlot = ""
        )
    }

    private fun inferPendingClarificationSlot(question: String): String {
        val q = question.lowercase(Locale.getDefault())
        return when {
            "комнат" in q -> "target_area"
            "цвет" in q -> "color"
            "ярк" in q -> "brightness"
            "тепл" in q || "холод" in q || "бел" in q -> "color_temp"
            else -> ""
        }
    }

    private fun buildQuickActionDisplayText(
        actionId: String,
        areaName: String,
        deviceType: String,
        deviceId: String?
    ): String {
        val actionLabel = when (actionId.uppercase(Locale.US)) {
            "TURN_ON" -> "Включить"
            "TURN_OFF" -> "Выключить"
            "BRIGHTER" -> "Ярче"
            "DIMMER" -> "Тише"
            "WARMER" -> "Теплее"
            "COOLER" -> "Холоднее"
            "COZY" -> "Уютно"
            "MOVIE" -> "Кино"
            else -> actionId
        }
        val targetLabel = when {
            !deviceId.isNullOrBlank() -> {
                val deviceName = _ui.value.deviceCatalog
                    ?.devices
                    ?.firstOrNull { it.deviceId == deviceId }
                    ?.name
                    ?.trim()
                    .orEmpty()
                if (deviceName.isNotBlank()) {
                    deviceName
                } else {
                    deviceId
                }
            }

            areaName.isNotBlank() -> {
                val typeLabel = when (deviceType.lowercase(Locale.US)) {
                    "light" -> "свет"
                    "switch" -> "розетки"
                    else -> "устройства"
                }
                "$typeLabel · $areaName"
            }

            else -> when (deviceType.lowercase(Locale.US)) {
                "light" -> "свет"
                "switch" -> "розетки"
                else -> "устройства"
            }
        }
        return "$actionLabel · $targetLabel"
    }

    private fun beginGatewayCommand(commandText: String, commandSource: String) {
        _ui.value = _ui.value.copy(
            lastCommandText = commandText,
            lastCommandSource = commandSource,
            lastParserModeUsed = "",
            lastParsedStageSummary = "",
            lastValidatedStageSummary = "",
            lastExecutionStageSummary = "",
            parseStageMs = 0,
            validateStageMs = 0,
            executeStageMs = 0,
            llmStageMs = 0,
            llmPromptTokens = 0,
            llmCompletionTokens = 0,
            llmTotalTokens = 0,
            llmModel = ""
        )
    }

    private fun beginScenarioPreview(text: String) {
        _ui.value = _ui.value.copy(
            lastCommandText = text,
            lastCommandSource = "scenario",
            scenarioPreviewStatus = "",
            scenarioPreviewSayText = "",
            scenarioPreviewQuestion = "",
            scenarioPreviewTitle = "",
            scenarioPreviewRuleCount = 0,
            scenarioPreviewAutomationCount = 0,
            scenarioPreviewParseMs = 0,
            scenarioPreviewValidateMs = 0,
            scenarioPreviewCompileMs = 0,
            scenarioPreviewLlmMs = 0,
            scenarioPreviewLlmPromptTokens = 0,
            scenarioPreviewLlmCompletionTokens = 0,
            scenarioPreviewLlmTotalTokens = 0,
            scenarioPreviewLlmModel = "",
            scenarioPreviewParsedBundleJson = "",
            scenarioPreviewValidatedBundleJson = "",
            scenarioPreviewAutomationsJson = "",
            scenarioPreviewRequestRaw = "",
            scenarioPreviewResponseRaw = "",
            scenarioSaveStatus = "",
            scenarioSaveSayText = "",
            scenarioSaveSavedAutomationCount = 0,
            scenarioSaveFileAutomationCount = 0,
            scenarioSaveStorageFile = "",
            scenarioSaveIncludeDetected = false,
            scenarioSaveReloaded = false,
            scenarioSaveIncludeHint = "",
            scenarioSaveRequestRaw = "",
            scenarioSaveResponseRaw = ""
        )
    }

    private fun beginScenarioSave() {
        _ui.value = _ui.value.copy(
            scenarioSaveStatus = "",
            scenarioSaveSayText = "",
            scenarioSaveSavedAutomationCount = 0,
            scenarioSaveFileAutomationCount = 0,
            scenarioSaveStorageFile = "",
            scenarioSaveIncludeDetected = false,
            scenarioSaveReloaded = false,
            scenarioSaveIncludeHint = "",
            scenarioSaveRequestRaw = "",
            scenarioSaveResponseRaw = ""
        )
    }

    private suspend fun applyGatewayEnvelope(
        envelope: GatewayCallResult,
        originalText: String,
        asrMs: Long,
        commandSource: String,
        startedAtMs: Long
    ) {
        _ui.value = _ui.value.copy(
            lastGatewayRequestRaw = envelope.rawRequest,
            lastGatewayResponseRaw = envelope.rawResponse
        )
        val res = envelope.result
        val finishedAtMs = System.currentTimeMillis()
        val netMs = finishedAtMs - startedAtMs
        val totalMs = netMs + asrMs

        when (res) {
            is GatewayResult.Ok -> {
                val say = res.sayText
                val status = res.status

                _ui.value = _ui.value.copy(
                    lastGatewayStatus = status,
                    lastSayText = say,
                    lastError = "",
                    lastParserModeUsed = res.parserModeUsed,
                    lastParsedStageSummary = formatParsedStageSummary(res),
                    lastValidatedStageSummary = formatValidatedStageSummary(res),
                    lastExecutionStageSummary = formatExecutionStageSummary(res),
                    parseStageMs = res.timing.parseMs,
                    validateStageMs = res.timing.validateMs,
                    executeStageMs = res.timing.executeMs,
                    llmStageMs = res.timing.llm?.durationMs ?: 0L,
                    llmPromptTokens = res.timing.llm?.promptTokens ?: 0,
                    llmCompletionTokens = res.timing.llm?.completionTokens ?: 0,
                    llmTotalTokens = res.timing.llm?.totalTokens ?: 0,
                    llmModel = res.timing.llm?.model.orEmpty(),
                    netMs = netMs,
                    totalMs = totalMs
                )

                val ctx = res.contextSnapshot
                val areaName = ctx?.lastAreaName ?: res.contextUpdatesLastAreaName
                if (_ui.value.selectedHomeAreaName.isBlank() && !areaName.isNullOrBlank()) {
                    settings.setSelectedHomeAreaName(areaName)
                }
                if (!areaName.isNullOrBlank()) {
                    settings.setLastAreaName(areaName)
                }
                if (ctx != null) {
                    settings.setLastEntityIds(ctx.lastEntityIds)
                    if (ctx.lastBrightness != null) {
                        settings.setLastBrightness(ctx.lastBrightness)
                    }
                    if (ctx.explicitColor) {
                        settings.setLastColorName(ctx.lastColorName)
                        settings.setLastColorTempKelvin(null)
                    } else if (ctx.explicitColorTemp) {
                        settings.setLastColorTempKelvin(ctx.lastColorTempKelvin)
                        settings.setLastColorName(null)
                    }
                    _ui.value = _ui.value.copy(
                        selectedHomeAreaName = _ui.value.selectedHomeAreaName.ifBlank { areaName.orEmpty() },
                        lastAreaName = areaName ?: _ui.value.lastAreaName,
                        lastEntityIds = ctx.lastEntityIds,
                        lastColorName = if (ctx.explicitColor) ctx.lastColorName.orEmpty() else _ui.value.lastColorName,
                        lastBrightness = ctx.lastBrightness ?: _ui.value.lastBrightness,
                        lastColorTempKelvin = when {
                            ctx.explicitColor -> null
                            ctx.explicitColorTemp -> ctx.lastColorTempKelvin
                            else -> _ui.value.lastColorTempKelvin
                        }
                    )
                    val reconciled = reconcileSelectedTarget(
                        catalog = _ui.value.deviceCatalog,
                        areaName = selectedHomeAreaName(_ui.value),
                        contextEntityIds = _ui.value.lastEntityIds,
                        current = _ui.value.selectedTarget
                    )
                    _ui.value = _ui.value.copy(selectedTarget = reconciled)
                    persistSelectedTarget(reconciled)
                } else if (!areaName.isNullOrBlank()) {
                    _ui.value = _ui.value.copy(
                        selectedHomeAreaName = _ui.value.selectedHomeAreaName.ifBlank { areaName },
                        lastAreaName = areaName
                    )
                    val reconciled = reconcileSelectedTarget(
                        catalog = _ui.value.deviceCatalog,
                        areaName = selectedHomeAreaName(_ui.value),
                        contextEntityIds = _ui.value.lastEntityIds,
                        current = _ui.value.selectedTarget
                    )
                    _ui.value = _ui.value.copy(selectedTarget = reconciled)
                    persistSelectedTarget(reconciled)
                }

                if (status == "NEEDS_CLARIFICATION" && res.clarification != null) {
                    _ui.value = _ui.value.copy(
                        clarificationQuestion = res.clarification.question,
                        clarificationOptions = res.clarification.options,
                        pendingOriginalText = originalText,
                        pendingClarificationSlot = inferPendingClarificationSlot(res.clarification.question)
                    )
                    appendLog("Нужно уточнение: ${res.clarification.question}", LogKind.ACTION)
                    if (res.clarification.question.isNotBlank()) {
                        tts.speak(res.clarification.question)
                    }
                } else {
                    clearClarification()
                    if (say.isNotBlank()) tts.speak(say)
                }

                appendLog("Gateway: $status ${say.take(80)}", LogKind.INFO)
                if (_ui.value.lastParsedStageSummary.isNotBlank()) {
                    appendLog("Parsed: ${_ui.value.lastParsedStageSummary}", LogKind.INFO)
                }
                if (_ui.value.lastValidatedStageSummary.isNotBlank()) {
                    appendLog("Validated: ${_ui.value.lastValidatedStageSummary}", LogKind.INFO)
                }
                if (_ui.value.lastExecutionStageSummary.isNotBlank()) {
                    appendLog("Execution: ${_ui.value.lastExecutionStageSummary}", LogKind.INFO)
                }
                if (commandSource == "voice") {
                    writeLastClipMetadata()
                    appendEvaluationRecord(runType = "voice")
                }
                updateNetworkStatus(true, "OK: $status", netMs)
                recordRecentCommand(originalText, status)
            }

            is GatewayResult.Error -> {
                _ui.value = _ui.value.copy(
                    lastGatewayStatus = "ERROR",
                    lastSayText = "",
                    lastError = res.message,
                    lastParserModeUsed = "",
                    lastParsedStageSummary = "",
                    lastValidatedStageSummary = "",
                    lastExecutionStageSummary = "Transport error${if (res.code != null) " · HTTP ${res.code}" else ""}",
                    parseStageMs = 0,
                    validateStageMs = 0,
                    executeStageMs = 0,
                    llmStageMs = 0,
                    llmPromptTokens = 0,
                    llmCompletionTokens = 0,
                    llmTotalTokens = 0,
                    llmModel = "",
                    netMs = netMs,
                    totalMs = totalMs
                )
                tts.speak("Ошибка. ${res.message}")
                appendLog("Gateway ошибка: ${res.message}", LogKind.ERROR)
                if (commandSource == "voice") {
                    writeLastClipMetadata()
                    appendEvaluationRecord(runType = "voice")
                }
                updateNetworkStatus(false, res.message, netMs)
            }
        }
    }

    private fun applyScenarioPreviewEnvelope(
        envelope: GatewayScenarioPreviewCallResult,
        startedAtMs: Long
    ) {
        _ui.value = _ui.value.copy(
            scenarioPreviewRequestRaw = envelope.rawRequest,
            scenarioPreviewResponseRaw = envelope.rawResponse
        )
        val netMs = System.currentTimeMillis() - startedAtMs

        when (val res = envelope.result) {
            is GatewayScenarioPreviewResult.Ok -> {
                _ui.value = _ui.value.copy(
                    scenarioPreviewStatus = res.status,
                    scenarioPreviewSayText = res.sayText,
                    scenarioPreviewQuestion = res.clarification?.question.orEmpty(),
                    scenarioPreviewTitle = res.parsedSummary.title.orEmpty(),
                    scenarioPreviewRuleCount = res.parsedSummary.ruleCount,
                    scenarioPreviewAutomationCount = res.automationCount,
                    scenarioPreviewParseMs = res.timing.parseMs,
                    scenarioPreviewValidateMs = res.timing.validateMs,
                    scenarioPreviewCompileMs = res.timing.compileMs,
                    scenarioPreviewLlmMs = res.timing.llm?.durationMs ?: 0L,
                    scenarioPreviewLlmPromptTokens = res.timing.llm?.promptTokens ?: 0,
                    scenarioPreviewLlmCompletionTokens = res.timing.llm?.completionTokens ?: 0,
                    scenarioPreviewLlmTotalTokens = res.timing.llm?.totalTokens ?: 0,
                    scenarioPreviewLlmModel = res.timing.llm?.model.orEmpty(),
                    scenarioPreviewParsedBundleJson = res.parsedBundleJson,
                    scenarioPreviewValidatedBundleJson = res.validatedBundleJson.orEmpty(),
                    scenarioPreviewAutomationsJson = res.automationsJson,
                    lastGatewayStatus = res.status,
                    lastSayText = res.sayText,
                    lastError = "",
                    netMs = netMs,
                    totalMs = netMs
                )
                appendLog(
                    "Scenario preview: ${res.status} · rules=${res.parsedSummary.ruleCount} · automations=${res.automationCount}",
                    LogKind.INFO
                )
                if (res.clarification != null) {
                    appendLog("Scenario clarification: ${res.clarification.question}", LogKind.ACTION)
                }
                updateNetworkStatus(true, "OK: ${res.status}", netMs)
            }

            is GatewayScenarioPreviewResult.Error -> {
                _ui.value = _ui.value.copy(
                    scenarioPreviewStatus = "ERROR",
                    scenarioPreviewSayText = "",
                    scenarioPreviewQuestion = "",
                    scenarioPreviewTitle = "",
                    scenarioPreviewRuleCount = 0,
                    scenarioPreviewAutomationCount = 0,
                    scenarioPreviewParseMs = 0,
                    scenarioPreviewValidateMs = 0,
                    scenarioPreviewCompileMs = 0,
                    scenarioPreviewLlmMs = 0,
                    scenarioPreviewLlmPromptTokens = 0,
                    scenarioPreviewLlmCompletionTokens = 0,
                    scenarioPreviewLlmTotalTokens = 0,
                    scenarioPreviewLlmModel = "",
                    scenarioPreviewParsedBundleJson = "",
                    scenarioPreviewValidatedBundleJson = "",
                    scenarioPreviewAutomationsJson = "",
                    lastGatewayStatus = "ERROR",
                    lastSayText = "",
                    lastError = res.message,
                    netMs = netMs,
                    totalMs = netMs
                )
                appendLog("Scenario preview error: ${res.message}", LogKind.ERROR)
                updateNetworkStatus(false, res.message, netMs)
            }
        }
    }

    private fun applyScenarioSaveEnvelope(
        envelope: GatewayScenarioSaveCallResult,
        startedAtMs: Long
    ) {
        _ui.value = _ui.value.copy(
            scenarioSaveRequestRaw = envelope.rawRequest,
            scenarioSaveResponseRaw = envelope.rawResponse
        )
        val netMs = System.currentTimeMillis() - startedAtMs

        when (val res = envelope.result) {
            is GatewayScenarioSaveResult.Ok -> {
                _ui.value = _ui.value.copy(
                    scenarioSaveStatus = res.status,
                    scenarioSaveSayText = res.sayText,
                    scenarioSaveSavedAutomationCount = res.savedAutomationCount,
                    scenarioSaveFileAutomationCount = res.fileAutomationCount,
                    scenarioSaveStorageFile = res.storageFile.orEmpty(),
                    scenarioSaveIncludeDetected = res.includeDetected,
                    scenarioSaveReloaded = res.reloaded,
                    scenarioSaveIncludeHint = res.includeHint.orEmpty(),
                    lastGatewayStatus = res.status,
                    lastSayText = res.sayText,
                    lastError = "",
                    netMs = netMs,
                    totalMs = netMs
                )
                appendLog(
                    "Scenario save: ${res.status} · saved=${res.savedAutomationCount} · file=${res.fileAutomationCount}",
                    LogKind.INFO
                )
                if (res.includeHint.orEmpty().isNotBlank()) {
                    appendLog("Scenario include hint: ${res.includeHint}", LogKind.ACTION)
                }
                if (res.sayText.isNotBlank()) {
                    tts.speak(res.sayText)
                }
                updateNetworkStatus(true, "OK: ${res.status}", netMs)
                refreshScenarioLibrary(silent = true)
            }

            is GatewayScenarioSaveResult.Error -> {
                _ui.value = _ui.value.copy(
                    scenarioSaveStatus = "ERROR",
                    scenarioSaveSayText = "",
                    scenarioSaveSavedAutomationCount = 0,
                    scenarioSaveFileAutomationCount = 0,
                    scenarioSaveStorageFile = "",
                    scenarioSaveIncludeDetected = false,
                    scenarioSaveReloaded = false,
                    scenarioSaveIncludeHint = "",
                    lastGatewayStatus = "ERROR",
                    lastSayText = "",
                    lastError = res.message,
                    netMs = netMs,
                    totalMs = netMs
                )
                appendLog("Scenario save error: ${res.message}", LogKind.ERROR)
                updateNetworkStatus(false, res.message, netMs)
            }
        }
    }

    private fun applyScenarioDeleteEnvelope(
        envelope: GatewayScenarioDeleteCallResult,
        startedAtMs: Long
    ) {
        val netMs = System.currentTimeMillis() - startedAtMs
        when (val res = envelope.result) {
            is GatewayScenarioDeleteResult.Ok -> {
                _ui.value = _ui.value.copy(
                    scenarioSaveStatus = res.status,
                    scenarioSaveSayText = res.sayText,
                    scenarioSaveSavedAutomationCount = if (res.deletedAutomationId != null) 1 else 0,
                    scenarioSaveFileAutomationCount = res.fileAutomationCount,
                    scenarioSaveStorageFile = res.storageFile.orEmpty(),
                    scenarioSaveIncludeDetected = true,
                    scenarioSaveReloaded = res.status == "DELETED_ACTIVE",
                    scenarioSaveIncludeHint = "",
                    scenarioSaveRequestRaw = envelope.rawRequest,
                    scenarioSaveResponseRaw = envelope.rawResponse,
                    lastGatewayStatus = res.status,
                    lastSayText = res.sayText,
                    lastError = "",
                    netMs = netMs,
                    totalMs = netMs
                )
                appendLog(
                    "Scenario delete: ${res.status} · id=${res.deletedAutomationId ?: "not_found"}",
                    LogKind.INFO
                )
                if (res.sayText.isNotBlank()) {
                    tts.speak(res.sayText)
                }
                updateNetworkStatus(true, "OK: ${res.status}", netMs)
            }

            is GatewayScenarioDeleteResult.Error -> {
                _ui.value = _ui.value.copy(
                    scenarioSaveStatus = "ERROR",
                    scenarioSaveSayText = "",
                    scenarioSaveSavedAutomationCount = 0,
                    scenarioSaveFileAutomationCount = 0,
                    scenarioSaveStorageFile = "",
                    scenarioSaveIncludeDetected = false,
                    scenarioSaveReloaded = false,
                    scenarioSaveIncludeHint = "",
                    scenarioSaveRequestRaw = envelope.rawRequest,
                    scenarioSaveResponseRaw = envelope.rawResponse,
                    lastGatewayStatus = "ERROR",
                    lastSayText = "",
                    lastError = res.message,
                    netMs = netMs,
                    totalMs = netMs
                )
                appendLog("Scenario delete error: ${res.message}", LogKind.ERROR)
                updateNetworkStatus(false, res.message, netMs)
            }
        }
    }

    private fun sendText(
        text: String,
        originalText: String,
        asrMs: Long,
        commandSource: String
    ) {
        val s = _ui.value
        val baseUrl = s.gatewayUrl.trim()
        val apiKey = s.apiKey.trim()

        if (baseUrl.isBlank()) {
            if (commandSource == "voice") {
                appendEvaluationRecord(runType = "voice")
            }
            setError("Не задан Gateway URL")
            return
        }
        if (apiKey.isBlank()) {
            if (commandSource == "voice") {
                appendEvaluationRecord(runType = "voice")
            }
            setError("Не задан X-API-Key")
            return
        }

        appendLog("Отправка команды: \"$text\"", LogKind.ACTION)
        beginGatewayCommand(commandText = text, commandSource = commandSource)

        viewModelScope.launch {
            setBusy(true)
            val startedAtMs = System.currentTimeMillis()
            try {
                val envelope: GatewayCallResult = withContext(Dispatchers.IO) {
                    gateway.sendCommand(
                        baseUrl = baseUrl,
                        apiKey = apiKey,
                        text = text,
                        parserMode = s.parserMode,
                        dryRun = s.dryRun,
                        selectedAreaName = s.selectedHomeAreaName.trim().ifBlank { null },
                        lastAreaName = selectedHomeAreaName(s).ifBlank { s.lastAreaName.trim() }.ifBlank { null },
                        lastEntityIds = s.lastEntityIds,
                        lastColorName = s.lastColorName.ifBlank { null },
                        lastBrightness = s.lastBrightness,
                        lastColorTempKelvin = s.lastColorTempKelvin,
                        pendingClarificationSlot = s.pendingClarificationSlot.ifBlank { null }
                    )
                }
                applyGatewayEnvelope(
                    envelope = envelope,
                    originalText = originalText,
                    asrMs = asrMs,
                    commandSource = commandSource,
                    startedAtMs = startedAtMs
                )
            } finally {
                setBusy(false)
            }
        }
    }

    private suspend fun decodeCapturedAudio(
        engineType: AsrEngineType,
        capturedAudio: CapturedAudio
    ): DecodeSnapshot {
        val t0 = SystemClock.elapsedRealtime()
        val text = withContext(Dispatchers.Default) {
            asrEngines.getValue(engineType).decodeAudio(capturedAudio.samples)
        }
        return DecodeSnapshot(
            engineType = engineType,
            text = text,
            decodeMs = SystemClock.elapsedRealtime() - t0
        )
    }

    private fun saveLastClipArtifacts(
        primaryAsrType: AsrEngineType,
        capturedAudio: CapturedAudio
    ) {
        val capturedAtMs = System.currentTimeMillis()
        lastClipInfo = LastClipInfo(
            clipId = "clip_$capturedAtMs",
            capturedAtMs = capturedAtMs,
            activeAsrType = primaryAsrType,
            parserMode = _ui.value.parserMode,
            capturedAudio = capturedAudio
        )
        runCatching {
            WavFileCodec.writeMonoPcm16(
                file = lastClipWavFile,
                samples = capturedAudio.samples,
                sampleRate = ASR_SAMPLE_RATE
            )
            _ui.value = _ui.value.copy(lastClipWavPath = lastClipWavFile.absolutePath)
            writeLastClipMetadata()
        }.onFailure { e ->
            setError("Failed to save clip: ${e.message}")
        }
    }

    private fun writeLastClipMetadata(
        primaryDecode: DecodeSnapshot? = null,
        comparisonDecode: DecodeSnapshot? = null
    ) {
        val clipInfo = lastClipInfo ?: return
        val state = _ui.value
        runCatching {
            val metadata = JSONObject().apply {
                put("clip_id", clipInfo.clipId)
                put("captured_at_ms", clipInfo.capturedAtMs)
                put("captured_at_iso", synchronized(logFormatter) {
                    logFormatter.format(Date(clipInfo.capturedAtMs))
                })
                put("wav_path", lastClipWavFile.absolutePath)
                put("sample_rate", ASR_SAMPLE_RATE)
                put("active_asr_engine", clipInfo.activeAsrType.storageValue)
                put("active_asr_label", clipInfo.activeAsrType.label)
                put("parser_mode", clipInfo.parserMode)
                put(
                    "capture",
                    JSONObject().apply {
                        put("duration_ms", clipInfo.capturedAudio.durationMs)
                        put("speech_duration_ms", clipInfo.capturedAudio.speechDurationMs)
                        put("speech_detected", clipInfo.capturedAudio.speechDetected)
                        put("leading_trim_ms", clipInfo.capturedAudio.leadingTrimMs)
                        put("trailing_trim_ms", clipInfo.capturedAudio.trailingTrimMs)
                        put("sample_count", clipInfo.capturedAudio.samples.size)
                        put("peak_level", clipInfo.capturedAudio.peakLevel)
                        put("clipping_detected", clipInfo.capturedAudio.clippingDetected)
                        put("clipped_sample_count", clipInfo.capturedAudio.clippedSampleCount)
                        put("dc_offset", clipInfo.capturedAudio.dcOffset)
                        put("normalization_gain", clipInfo.capturedAudio.normalizationGain)
                    }
                )
                put(
                    "speech_window",
                    JSONObject().apply {
                        put("speech_detected", state.speechDetected)
                        put("speech_active", state.speechActive)
                        put("speech_start_offset_ms", state.speechStartOffsetMs)
                        put("speech_end_offset_ms", state.speechEndOffsetMs)
                        put("press_to_speech_start_ms", state.speechStartOffsetMs)
                    }
                )
                put(
                    "primary_result",
                    JSONObject().apply {
                        val engine = primaryDecode?.engineType ?: clipInfo.activeAsrType
                        put("engine", engine.storageValue)
                        put("engine_label", engine.label)
                        put("text", primaryDecode?.text ?: state.lastAsrText)
                        put("decode_ms", primaryDecode?.decodeMs ?: state.asrMs)
                        put("empty_result", state.lastAsrEmpty)
                        put("release_to_result_ms", state.releaseToResultMs)
                    }
                )
                if (state.lastComparisonEngine.isNotBlank() || comparisonDecode != null) {
                    put(
                        "comparison_result",
                        JSONObject().apply {
                            val engine = comparisonDecode?.engineType
                            put("engine", engine?.storageValue ?: state.lastComparisonEngine.lowercase(Locale.US))
                            put("engine_label", engine?.label ?: state.lastComparisonEngine)
                            put("text", comparisonDecode?.text ?: state.lastComparisonText)
                            put("decode_ms", comparisonDecode?.decodeMs ?: state.lastComparisonMs)
                        }
                    )
                }
                put(
                    "gateway",
                    JSONObject().apply {
                        put("status", state.lastGatewayStatus)
                        put("parser_mode_used", state.lastParserModeUsed)
                        put("parsed_summary", state.lastParsedStageSummary)
                        put("validated_summary", state.lastValidatedStageSummary)
                        put("execution_summary", state.lastExecutionStageSummary)
                        put("net_ms", state.netMs)
                        put("total_ms", state.totalMs)
                        put(
                            "timing_ms",
                            JSONObject().apply {
                                put("parse", state.parseStageMs)
                                put("validate", state.validateStageMs)
                                put("execute", state.executeStageMs)
                                if (state.llmStageMs > 0L || state.llmPromptTokens > 0 || state.llmCompletionTokens > 0) {
                                    put(
                                        "llm",
                                        JSONObject().apply {
                                            put("duration_ms", state.llmStageMs)
                                            put("prompt_tokens", state.llmPromptTokens)
                                            put("completion_tokens", state.llmCompletionTokens)
                                            put("total_tokens", state.llmTotalTokens)
                                            if (state.llmModel.isNotBlank()) {
                                                put("model", state.llmModel)
                                            }
                                        }
                                    )
                                }
                            }
                        )
                    }
                )
            }
            lastClipMetadataFile.writeText(metadata.toString(2))
            _ui.value = _ui.value.copy(lastClipMetadataPath = lastClipMetadataFile.absolutePath)
        }.onFailure { e ->
            setError("Failed to write clip metadata: ${e.message}")
        }
    }

    private fun appendEvaluationRecord(runType: String) {
        val clipInfo = lastClipInfo ?: return
        val state = _ui.value
        val record = JSONObject().apply {
            put("clip_id", clipInfo.clipId)
            put("run_type", runType)
            put("captured_at_ms", clipInfo.capturedAtMs)
            put("captured_at_iso", synchronized(logFormatter) {
                logFormatter.format(Date(clipInfo.capturedAtMs))
            })
            put("wav_path", lastClipWavFile.absolutePath)
            put("metadata_path", lastClipMetadataFile.absolutePath)
            put("active_engine", clipInfo.activeAsrType.storageValue)
            put("active_engine_label", clipInfo.activeAsrType.label)
            put("parser_mode_requested", clipInfo.parserMode)
            put("parser_mode_used", state.lastParserModeUsed)
            put("asr_text", state.lastAsrText)
            put("asr_ms", state.asrMs)
            put("comparison_engine", state.lastComparisonEngine)
            put("comparison_text", state.lastComparisonText)
            put("comparison_ms", state.lastComparisonMs)
            put("gateway_status", state.lastGatewayStatus)
            put("parsed_summary", state.lastParsedStageSummary)
            put("validated_summary", state.lastValidatedStageSummary)
            put("execution_summary", state.lastExecutionStageSummary)
            put("llm_ms", state.llmStageMs)
            put("llm_prompt_tokens", state.llmPromptTokens)
            put("llm_completion_tokens", state.llmCompletionTokens)
            put("llm_total_tokens", state.llmTotalTokens)
            put("llm_model", state.llmModel)
            put("net_ms", state.netMs)
            put("total_ms", state.totalMs)
            put("press_to_speech_start_ms", state.speechStartOffsetMs)
            put("release_to_result_ms", state.releaseToResultMs)
            put("empty_result", state.lastAsrEmpty)
            put("speech_detected", clipInfo.capturedAudio.speechDetected)
            put("speech_duration_ms", clipInfo.capturedAudio.speechDurationMs)
            put("capture_duration_ms", clipInfo.capturedAudio.durationMs)
            put("leading_trim_ms", clipInfo.capturedAudio.leadingTrimMs)
            put("trailing_trim_ms", clipInfo.capturedAudio.trailingTrimMs)
            put("sample_count", clipInfo.capturedAudio.samples.size)
            put("peak_level", clipInfo.capturedAudio.peakLevel)
            put("clipping_detected", clipInfo.capturedAudio.clippingDetected)
            put("clipped_sample_count", clipInfo.capturedAudio.clippedSampleCount)
            put("dc_offset", clipInfo.capturedAudio.dcOffset)
            put("normalization_gain", clipInfo.capturedAudio.normalizationGain)
            put("error", state.lastError)
        }

        runCatching {
            appendJsonlRecord(record)
            appendCsvRecord(record)
            _ui.value = _ui.value.copy(
                evalHistoryJsonlPath = evalHistoryJsonlFile.absolutePath,
                evalHistoryCsvPath = evalHistoryCsvFile.absolutePath,
                evalHistoryCount = state.evalHistoryCount + 1
            )
        }.onFailure { e ->
            setError("Failed to append evaluation history: ${e.message}")
        }
    }

    private fun appendAttemptMetricsLog(
        capturedAudio: CapturedAudio,
        releaseToResultMs: Long,
        emptyResult: Boolean
    ) {
        appendLog(
            "Metrics: captureMs=${capturedAudio.durationMs} speechMs=${capturedAudio.speechDurationMs} pressToSpeechMs=${_ui.value.speechStartOffsetMs} releaseToResultMs=$releaseToResultMs clipping=${capturedAudio.clippingDetected} clippedSamples=${capturedAudio.clippedSampleCount} peak=${"%.3f".format(Locale.US, capturedAudio.peakLevel)} dcOffset=${"%.5f".format(Locale.US, capturedAudio.dcOffset)} gain=${"%.2f".format(Locale.US, capturedAudio.normalizationGain)} empty=$emptyResult",
            LogKind.INFO
        )
    }

    private fun appendJsonlRecord(record: JSONObject) {
        evalHistoryJsonlFile.parentFile?.mkdirs()
        evalHistoryJsonlFile.appendText(record.toString() + "\n")
    }

    private fun appendCsvRecord(record: JSONObject) {
        evalHistoryCsvFile.parentFile?.mkdirs()
        if (!evalHistoryCsvFile.exists()) {
            evalHistoryCsvFile.writeText(
                listOf(
                    "clip_id",
                    "run_type",
                    "captured_at_iso",
                    "active_engine",
                    "parser_mode_requested",
                    "parser_mode_used",
                    "asr_text",
                    "asr_ms",
                    "comparison_engine",
                    "comparison_text",
                    "comparison_ms",
                    "gateway_status",
                    "parsed_summary",
                    "validated_summary",
                    "execution_summary",
                    "net_ms",
                    "total_ms",
                    "press_to_speech_start_ms",
                    "release_to_result_ms",
                    "empty_result",
                    "speech_detected",
                    "speech_duration_ms",
                    "capture_duration_ms",
                    "leading_trim_ms",
                    "trailing_trim_ms",
                    "sample_count",
                    "peak_level",
                    "clipping_detected",
                    "clipped_sample_count",
                    "dc_offset",
                    "normalization_gain",
                    "error",
                    "wav_path",
                    "metadata_path"
                ).joinToString(",") + "\n"
            )
        }

        val row = listOf(
            record.optString("clip_id"),
            record.optString("run_type"),
            record.optString("captured_at_iso"),
            record.optString("active_engine"),
            record.optString("parser_mode_requested"),
            record.optString("parser_mode_used"),
            record.optString("asr_text"),
            record.optLong("asr_ms").toString(),
            record.optString("comparison_engine"),
            record.optString("comparison_text"),
            record.optLong("comparison_ms").toString(),
            record.optString("gateway_status"),
            record.optString("parsed_summary"),
            record.optString("validated_summary"),
            record.optString("execution_summary"),
            record.optLong("net_ms").toString(),
            record.optLong("total_ms").toString(),
            record.optLong("press_to_speech_start_ms").toString(),
            record.optLong("release_to_result_ms").toString(),
            record.optBoolean("empty_result").toString(),
            record.optBoolean("speech_detected").toString(),
            record.optLong("speech_duration_ms").toString(),
            record.optLong("capture_duration_ms").toString(),
            record.optLong("leading_trim_ms").toString(),
            record.optLong("trailing_trim_ms").toString(),
            record.optInt("sample_count").toString(),
            record.optDouble("peak_level").toString(),
            record.optBoolean("clipping_detected").toString(),
            record.optInt("clipped_sample_count").toString(),
            record.optDouble("dc_offset").toString(),
            record.optDouble("normalization_gain").toString(),
            record.optString("error"),
            record.optString("wav_path"),
            record.optString("metadata_path")
        ).joinToString(",") { csvEscape(it) }
        evalHistoryCsvFile.appendText(row + "\n")
    }

    private fun csvEscape(value: String): String =
        "\"" + value.replace("\"", "\"\"").replace("\r", " ").replace("\n", " ") + "\""

    private fun loadEvalHistoryCount(): Int {
        if (!evalHistoryJsonlFile.exists()) return 0
        return runCatching {
            evalHistoryJsonlFile.useLines { lines -> lines.count { it.isNotBlank() } }
        }.getOrDefault(0)
    }

    private fun setBusy(v: Boolean) {
        _ui.value = _ui.value.copy(busy = v)
    }

    private fun selectedHomeAreaName(state: UiState = _ui.value): String =
        state.selectedHomeAreaName.trim().ifBlank { state.lastAreaName.trim() }

    private fun validateVoiceAttempt(capturedAudio: CapturedAudio, text: String): String? =
        when {
            !capturedAudio.speechDetected -> "Не расслышал речь, повторите"
            capturedAudio.durationMs < MIN_CAPTURE_DURATION_MS -> "Слишком короткое нажатие, удерживайте кнопку дольше"
            capturedAudio.speechDurationMs < MIN_SPEECH_DURATION_MS -> "Фраза слишком короткая, повторите"
            capturedAudio.peakLevel < MIN_PEAK_LEVEL -> "Слишком тихо, скажите команду громче"
            text.isBlank() -> "Не расслышал, повторите"
            else -> null
        }

    private fun formatParsedStageSummary(res: GatewayResult.Ok): String {
        val parsed = res.parsedStage ?: return ""
        return buildString {
            append("actions=${parsed.actionCount}")
            parsed.firstIntent?.let { append(" · intent=$it") }
            parsed.firstTargetAreaName?.let { append(" · area=$it") }
            parsed.firstTargetScope?.let { append(" · scope=$it") }
            append(" · clarification=${if (parsed.clarificationNeeded) "yes" else "no"}")
        }
    }

    private fun formatValidatedStageSummary(res: GatewayResult.Ok): String {
        val validated = res.validatedStage ?: return ""
        return buildString {
            validated.status?.let { append("status=$it") }
            validated.reasonCode?.let {
                if (isNotEmpty()) append(" · ")
                append("reason=$it")
            }
            if (isNotEmpty()) append(" · ")
            append("actions=${validated.actionCount}")
            append(" · warnings=${validated.warningCount}")
            validated.firstIntent?.let { append(" · intent=$it") }
            validated.firstAreaName?.let { append(" · area=$it") }
        }
    }

    private fun formatExecutionStageSummary(res: GatewayResult.Ok): String =
        buildString {
            append("status=${res.status}")
            append(" · calls=${res.executionStage.callCount}")
            append(" · errors=${res.executionStage.errorCount}")
            res.executionStage.firstService?.let { append(" · service=$it") }
            res.executionStage.firstErrorCode?.let { append(" · error=$it") }
        }
    private fun setError(msg: String) {
        _ui.value = _ui.value.copy(
            voiceUiState = VoiceUiState.ERROR,
            lastError = msg
        )
        appendLog("Ошибка: $msg", LogKind.ERROR)
    }

    private fun appendLog(message: String, kind: LogKind = LogKind.INFO) {
        val entry = LogEntry(message = message, kind = kind)
        _ui.value = _ui.value.let { current ->
            val updated = (current.logs + entry).takeLast(50)
            current.copy(logs = updated)
        }
        persistLog(entry)
    }

    private fun persistLog(entry: LogEntry) {
        runCatching {
            val stamp = synchronized(logFormatter) {
                logFormatter.format(Date(entry.timestamp))
            }
            logFile.appendText("$stamp\t${entry.kind.name}\t${entry.message}\n")
        }.onFailure { e ->
            Log.e("MainViewModel", "Failed to write log file", e)
        }
        refreshLogPreview()
    }

    fun refreshDiagnostics() {
        refreshLogPreview()
    }

    private fun refreshLogPreview() {
        val preview = if (logFile.exists()) {
            runCatching {
                val lines = logFile.readLines()
                lines.takeLast(5).joinToString("\n")
            }.getOrDefault("")
        } else ""
        _ui.value = _ui.value.copy(logPreview = preview)
    }

    override fun onCleared() {
        super.onCleared()
        pendingStopJob?.cancel()
        pendingStopJob = null
        listenWatchdogJob?.cancel()
        listenWatchdogJob = null
        asrPrepareJob?.cancel()
        stopDecodeJob?.cancel()
        asrEngines.values.forEach { it.close() }
        tts.close()
    }

    private fun currentAsr(): AsrEngine = asrEngines.getValue(activeAsrType)

    private fun switchAsrEngine(type: AsrEngineType) {
        pendingStopJob?.cancel()
        pendingStopJob = null
        listenWatchdogJob?.cancel()
        listenWatchdogJob = null
        stopDecodeJob?.cancel()
        _ui.value = _ui.value.copy(
            voiceUiState = VoiceUiState.IDLE,
            isListening = false,
            isFinishing = false,
            isRecognizing = false,
            audioLevel = 0f,
            asrReady = false,
            asrEngine = type.storageValue
        )

        asrPrepareJob?.cancel()
        activeAsrType = type
        val targetType = type
        asrPrepareJob = viewModelScope.launch {
            val ok = withContext(Dispatchers.IO) {
                currentAsr().prepareModelIfNeeded(
                    onError = { msg -> setError("${targetType.label}: $msg") }
                )
            }
            if (activeAsrType != targetType) return@launch
            _ui.value = _ui.value.copy(asrReady = ok)
            appendLog(
                if (ok) "${targetType.label} готов к запуску"
                else "${targetType.label} не готов"
            )

            warmUpComparisonEngine(targetType)
        }
    }

    private fun handleAudioLevel(level: Float) {
        val clamped = level.coerceIn(0f, 1f)
        val now = SystemClock.elapsedRealtime()
        _ui.update { current ->
            if (current.isListening && clamped >= FINISHING_SPEECH_LEVEL_THRESHOLD) {
                lastVoiceActivityAtMs = now
            }
            if (current.isListening) {
                current.copy(
                    voiceUiState =
                        if (current.voiceUiState == VoiceUiState.ARMING) VoiceUiState.LISTENING
                        else current.voiceUiState,
                    audioLevel = clamped
                )
            } else {
                current
            }
        }
    }

    private fun handleSpeechActivity(state: SpeechActivityState) {
        val now = SystemClock.elapsedRealtime()
        if (state.speechActive) {
            lastVoiceActivityAtMs = now
            speechEndedRealtimeAtMs = 0L
        } else if (state.speechDetected && state.speechEndOffsetMs != null) {
            speechEndedRealtimeAtMs = now
        }

        _ui.update { current ->
            if (!current.isListening && !current.isFinishing) return@update current
            current.copy(
                speechDetected = state.speechDetected,
                speechActive = state.speechActive,
                speechStartOffsetMs = state.speechStartOffsetMs ?: current.speechStartOffsetMs,
                speechEndOffsetMs = state.speechEndOffsetMs ?: 0L
            )
        }

        if (state.speechStartOffsetMs != null && state.speechActive) {
            appendLog("Speech start detected at ${state.speechStartOffsetMs} ms", LogKind.INFO)
        } else if (state.speechEndOffsetMs != null && !state.speechActive) {
            appendLog("Speech end detected at ${state.speechEndOffsetMs} ms", LogKind.INFO)
        }
    }

    private suspend fun compareCapturedAudio(
        primaryType: AsrEngineType,
        capturedAudio: CapturedAudio?
    ) {
        if (capturedAudio == null || capturedAudio.samples.isEmpty()) return

        val comparisonType = AsrEngineType.entries.firstOrNull { it != primaryType } ?: return
        val comparisonAsr = asrEngines.getValue(comparisonType)

        val prepared = withContext(Dispatchers.IO) {
            comparisonAsr.prepareModelIfNeeded(
                onError = { msg ->
                    appendLog("ASR compare ${comparisonType.label}: $msg", LogKind.ERROR)
                }
            )
        }
        if (!prepared) return

        val comparisonDecode = decodeCapturedAudio(comparisonType, capturedAudio)

        _ui.value = _ui.value.copy(
            lastComparisonEngine = comparisonType.label,
            lastComparisonText = comparisonDecode.text,
            lastComparisonMs = comparisonDecode.decodeMs
        )
        writeLastClipMetadata(comparisonDecode = comparisonDecode)
        appendLog(
            "ASR compare ${comparisonType.label}: ${comparisonDecode.text.ifBlank { "<empty>" }}",
            LogKind.INFO
        )
    }

    private fun warmUpComparisonEngine(activeType: AsrEngineType) {
        val comparisonType = AsrEngineType.entries.firstOrNull { it != activeType } ?: return
        viewModelScope.launch {
            val ok = withContext(Dispatchers.IO) {
                asrEngines.getValue(comparisonType).prepareModelIfNeeded(
                    onError = { msg ->
                        appendLog("ASR compare ${comparisonType.label}: $msg", LogKind.ERROR)
                    }
                )
            }
            appendLog(
                if (ok) "${comparisonType.label} comparison decoder ready"
                else "${comparisonType.label} comparison decoder unavailable"
            )
        }
    }

    private fun startListenWatchdog() {
        listenWatchdogJob?.cancel()
        val job = viewModelScope.launch {
            while (isActive) {
                delay(200)
                if (!_ui.value.isListening) break
                val now = SystemClock.elapsedRealtime()
                if (now - listeningStartedAtMs > MAX_LISTENING_MS) {
                    appendLog("Ограничение записи: достигнут лимит времени", LogKind.ACTION)
                    stopListening()
                    break
                }
            }
        }
        job.invokeOnCompletion { listenWatchdogJob = null }
        listenWatchdogJob = job
    }

    private fun updateNetworkStatus(
        ok: Boolean,
        message: String,
        latencyMs: Long?,
        detailLines: List<String>? = null
    ) {
        val previous = _ui.value.networkStatus
        _ui.value = _ui.value.copy(
            networkStatus = NetworkStatusInfo(
                label = message,
                ok = ok,
                latencyMs = latencyMs,
                checkedAt = System.currentTimeMillis(),
                detailLines = detailLines ?: previous.detailLines
            )
        )
    }

    private fun recordRecentCommand(text: String, status: String) {
        val entry = RecentCommand(text = text, status = status)
        val updated = (listOf(entry) + _ui.value.recentCommands)
            .distinctBy { it.text }
            .take(10)
        _ui.value = _ui.value.copy(recentCommands = updated)
        persistRecentCommands(updated)
    }

    private fun loadRecentCommands(): List<RecentCommand> {
        if (!recentCommandsFile.exists()) return emptyList()
        return runCatching {
            val json = recentCommandsFile.readText()
            val arr = JSONArray(json)
            buildList {
                for (i in 0 until arr.length()) {
                    val obj = arr.optJSONObject(i) ?: continue
                    val text = obj.optString("text", "")
                    if (text.isBlank()) continue
                    add(
                        RecentCommand(
                            text = text,
                            status = obj.optString("status", ""),
                            timestamp = obj.optLong("timestamp", System.currentTimeMillis())
                        )
                    )
                }
            }
        }.getOrElse { emptyList() }
    }

    private fun persistRecentCommands(list: List<RecentCommand>) {
        runCatching {
            val arr = JSONArray()
            list.forEach { entry ->
                arr.put(
                    JSONObject().apply {
                        put("text", entry.text)
                        put("status", entry.status)
                        put("timestamp", entry.timestamp)
                    }
                )
            }
            recentCommandsFile.writeText(arr.toString())
        }.onFailure { e ->
            Log.e("MainViewModel", "Failed to persist recent commands", e)
        }
    }
}



