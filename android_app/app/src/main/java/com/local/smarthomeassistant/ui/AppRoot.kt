@file:OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class)

package com.local.smarthomeassistant.ui

import android.view.MotionEvent
import android.view.SoundEffectConstants
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.clickable
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AcUnit
import androidx.compose.material.icons.outlined.Bathtub
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.ColorLens
import androidx.compose.material.icons.outlined.DarkMode
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.FlashOn
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Hotel
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Kitchen
import androidx.compose.material.icons.outlined.LightMode
import androidx.compose.material.icons.outlined.MeetingRoom
import androidx.compose.material.icons.outlined.ModeNight
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.Mic
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.PowerOff
import androidx.compose.material.icons.outlined.PowerSettingsNew
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.StopCircle
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.VisibilityOff
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material.icons.outlined.WbIncandescent
import androidx.compose.material.icons.outlined.WbSunny
import androidx.compose.material.icons.outlined.Weekend
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.local.smarthomeassistant.HomeTargetKind
import com.local.smarthomeassistant.LogEntry
import com.local.smarthomeassistant.LogKind
import com.local.smarthomeassistant.MainViewModel
import com.local.smarthomeassistant.RecentCommand
import com.local.smarthomeassistant.UiState
import com.local.smarthomeassistant.VoiceUiState
import com.local.smarthomeassistant.asr.AsrEngineType
import com.local.smarthomeassistant.net.DeviceCapabilitySummary
import com.local.smarthomeassistant.net.DeviceCatalogDevice
import com.local.smarthomeassistant.net.DeviceCatalogTargetProfile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs

private enum class AppTab(
    val title: String,
    val label: String,
    val icon: androidx.compose.ui.graphics.vector.ImageVector,
    val contentDescription: String
) {
    HOME(
        title = "Управление",
        label = "Управление",
        icon = Icons.Outlined.Home,
        contentDescription = "Основной экран управления"
    ),
    SCENARIOS(
        title = "Сценарии",
        label = "Сценарии",
        icon = Icons.Outlined.Notifications,
        contentDescription = "Экран сценариев"
    ),
    DEV(
        title = "Разработчик",
        label = "Разработчик",
        icon = Icons.Outlined.Settings,
        contentDescription = "Меню разработчика"
    )
}

private enum class LogFilter(val label: String) {
    ALL("Все"),
    ACTIONS("Действия"),
    ERRORS("Ошибки")
}

private data class HomeQuickAction(
    val actionId: String,
    val title: String,
    val subtitle: String,
    val icon: ImageVector,
    val prominent: Boolean = false
)

private data class HomeQuickActionTarget(
    val areaName: String,
    val deviceType: String,
    val deviceId: String?,
    val controlProfile: String,
    val label: String,
    val kind: HomeTargetKind,
    val supportedQuickActions: List<String>,
    val capabilities: DeviceCapabilitySummary,
    val supportedByBackend: Boolean
)

private data class QuickActionUiModel(
    val target: HomeQuickActionTarget,
    val typeOptions: List<String>,
    val profileOptions: List<DeviceCatalogTargetProfile>,
    val devicesOfSelectedType: List<DeviceCatalogDevice>
)

private data class HomeAreaOption(
    val label: String,
    val icon: ImageVector
)

private val HomeAreaOptions = listOf(
    HomeAreaOption("Спальня", Icons.Outlined.Hotel),
    HomeAreaOption("Кухня", Icons.Outlined.Kitchen),
    HomeAreaOption("Гостиная", Icons.Outlined.Weekend),
    HomeAreaOption("Коридор", Icons.Outlined.MeetingRoom),
    HomeAreaOption("Ванная", Icons.Outlined.Bathtub)
)

private val HomeLightQuickActions = listOf(
    HomeQuickAction(
        actionId = "TURN_ON",
        title = "Включить",
        subtitle = "Включить свет",
        icon = Icons.Outlined.PowerSettingsNew,
        prominent = true
    ),
    HomeQuickAction(
        actionId = "TURN_OFF",
        title = "Выключить",
        subtitle = "Выключить свет",
        icon = Icons.Outlined.PowerOff,
        prominent = true
    ),
    HomeQuickAction(
        actionId = "BRIGHTER",
        title = "Ярче",
        subtitle = "Добавить яркость",
        icon = Icons.Outlined.LightMode
    ),
    HomeQuickAction(
        actionId = "DIMMER",
        title = "Тише",
        subtitle = "Снизить яркость",
        icon = Icons.Outlined.DarkMode
    ),
    HomeQuickAction(
        actionId = "WARMER",
        title = "Теплее",
        subtitle = "Сделать теплее",
        icon = Icons.Outlined.WbSunny
    ),
    HomeQuickAction(
        actionId = "COOLER",
        title = "Холоднее",
        subtitle = "Сделать холоднее",
        icon = Icons.Outlined.AcUnit
    ),
    HomeQuickAction(
        actionId = "COZY",
        title = "Уютно",
        subtitle = "Мягкий свет",
        icon = Icons.Outlined.ModeNight
    ),
    HomeQuickAction(
        actionId = "MOVIE",
        title = "Кино",
        subtitle = "Сцена кинотеатра",
        icon = Icons.Outlined.Movie
    )
)

private val HomeSwitchQuickActions = listOf(
    HomeQuickAction(
        actionId = "TURN_ON",
        title = "Включить",
        subtitle = "Подать питание",
        icon = Icons.Outlined.PowerSettingsNew,
        prominent = true
    ),
    HomeQuickAction(
        actionId = "TURN_OFF",
        title = "Выключить",
        subtitle = "Отключить питание",
        icon = Icons.Outlined.PowerOff,
        prominent = true
    )
)

private fun areaOptionFor(area: String): HomeAreaOption =
    HomeAreaOptions.firstOrNull { it.label == area.trim() } ?: HomeAreaOption(
        label = area.trim().ifBlank { "Комната" },
        icon = Icons.Outlined.Home
    )

private fun deviceTypeLabel(deviceType: String, plural: Boolean = true): String =
    when (deviceType.trim().lowercase(Locale.US)) {
        "light" -> if (plural) "Свет" else "Лампа"
        "switch" -> if (plural) "Розетки" else "Розетка"
        else -> if (plural) "Устройства" else "Устройство"
    }

private fun deviceTypeIcon(deviceType: String): ImageVector =
    when (deviceType.trim().lowercase(Locale.US)) {
        "light" -> Icons.Outlined.LightMode
        "switch" -> Icons.Outlined.PowerSettingsNew
        else -> Icons.Outlined.Settings
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

private fun controlProfileLabel(profileId: String): String =
    when (profileId.trim().lowercase(Locale.US)) {
        "color_scene" -> "Цвет и сцены"
        "tunable_white" -> "Белый свет"
        "dimmable" -> "Яркость"
        "power_only" -> "Питание"
        else -> "Профиль"
    }

private fun controlProfileIcon(profileId: String): ImageVector =
    when (profileId.trim().lowercase(Locale.US)) {
        "color_scene" -> Icons.Outlined.ColorLens
        "tunable_white" -> Icons.Outlined.WbIncandescent
        "dimmable" -> Icons.Outlined.LightMode
        "power_only" -> Icons.Outlined.PowerSettingsNew
        else -> Icons.Outlined.Settings
    }

private fun isBrokenDeviceName(name: String): Boolean {
    val trimmed = name.trim()
    return trimmed.contains("Р") && trimmed.contains("С")
}

private fun deviceDisplayName(device: DeviceCatalogDevice, siblingsOfSameType: List<DeviceCatalogDevice>): String {
    val raw = device.name.trim()
    if (raw.isNotBlank() && !isBrokenDeviceName(raw)) {
        return raw
    }
    val index = siblingsOfSameType.indexOfFirst { it.deviceId == device.deviceId }
        .takeIf { it >= 0 }
        ?.plus(1)
        ?: 1
    return "${deviceTypeLabel(device.deviceType, plural = false)} $index"
}

private fun intersectCapabilities(devices: List<DeviceCatalogDevice>): DeviceCapabilitySummary {
    if (devices.isEmpty()) {
        return DeviceCapabilitySummary(
            onOff = false,
            brightness = false,
            rgb = false,
            colorTemp = false,
            transition = false
        )
    }
    return DeviceCapabilitySummary(
        onOff = devices.all { it.capabilities.onOff },
        brightness = devices.all { it.capabilities.brightness },
        rgb = devices.all { it.capabilities.rgb },
        colorTemp = devices.all { it.capabilities.colorTemp },
        transition = devices.all { it.capabilities.transition }
    )
}

private fun intersectSupportedQuickActions(devices: List<DeviceCatalogDevice>): List<String> {
    if (devices.isEmpty()) return emptyList()
    val shared = devices
        .map { it.supportedQuickActions.toSet() }
        .reduce { acc, actions -> acc.intersect(actions) }
    return devices.first().supportedQuickActions.filter { it in shared }
}

private fun fallbackQuickActionTarget(state: UiState): HomeQuickActionTarget? {
    val areaName = state.selectedHomeAreaName.trim().ifBlank { state.lastAreaName.trim() }
    if (areaName.isBlank()) return null
    return HomeQuickActionTarget(
        areaName = areaName,
        deviceType = "light",
        deviceId = null,
        controlProfile = "",
        label = "Свет",
        kind = if (state.lastEntityIds.isNotEmpty()) HomeTargetKind.DEVICE else HomeTargetKind.DEVICE_TYPE,
        supportedQuickActions = HomeLightQuickActions.map { it.actionId },
        capabilities = DeviceCapabilitySummary(
            onOff = true,
            brightness = true,
            rgb = true,
            colorTemp = true,
            transition = true
        ),
        supportedByBackend = true
    )
}

private fun resolveQuickActionUiModel(state: UiState): QuickActionUiModel? {
    val areaName = state.selectedHomeAreaName.trim().ifBlank { state.lastAreaName.trim() }
    if (areaName.isBlank()) return null

    val catalog = state.deviceCatalog
    if (catalog == null) {
        val target = fallbackQuickActionTarget(state) ?: return null
        return QuickActionUiModel(
            target = target,
            typeOptions = emptyList(),
            profileOptions = emptyList(),
            devicesOfSelectedType = emptyList()
        )
    }

    val devicesInArea = catalog.devices
        .filter { it.areaName == areaName }
        .sortedWith(compareBy({ deviceTypePriority(it.deviceType) }, { it.name }))

    if (devicesInArea.isEmpty()) {
        val target = fallbackQuickActionTarget(state) ?: return null
        return QuickActionUiModel(
            target = target,
            typeOptions = emptyList(),
            profileOptions = emptyList(),
            devicesOfSelectedType = emptyList()
        )
    }

    val typeOptions = devicesInArea
        .map { it.deviceType.trim().lowercase(Locale.US) }
        .distinct()
        .sortedBy(::deviceTypePriority)

    val selectedType = state.selectedTarget.deviceType
        .trim()
        .lowercase(Locale.US)
        .takeIf { it in typeOptions }
        ?: typeOptions.first()

    val devicesOfSelectedType = devicesInArea.filter { it.deviceType.trim().lowercase(Locale.US) == selectedType }
    val profileOptions = catalog.areas
        .firstOrNull { it.name == areaName }
        ?.targetProfiles
        ?.filter { it.deviceType.trim().lowercase(Locale.US) == selectedType }
        ?.sortedBy { controlProfilePriority(it.profileId) }
        .orEmpty()
    val selectedDevice = if (state.selectedTarget.kind == HomeTargetKind.DEVICE) {
        devicesOfSelectedType.firstOrNull { it.deviceId == state.selectedTarget.deviceId }
    } else {
        null
    }
    val selectedProfile = state.selectedTarget.controlProfile
        .trim()
        .lowercase(Locale.US)
        .takeIf { profile -> profile.isNotBlank() && profileOptions.any { it.profileId == profile } }
        .orEmpty()
    val targetDevices = when {
        selectedDevice != null -> listOf(selectedDevice)
        selectedProfile.isNotBlank() -> {
            devicesOfSelectedType.filter { it.controlProfile.trim().lowercase(Locale.US) == selectedProfile }
        }
        else -> devicesOfSelectedType
    }
    val supportedQuickActions = intersectSupportedQuickActions(targetDevices)
    val target = HomeQuickActionTarget(
        areaName = areaName,
        deviceType = selectedType,
        deviceId = selectedDevice?.deviceId,
        controlProfile = selectedProfile,
        label = selectedDevice?.let { deviceDisplayName(it, devicesOfSelectedType) }
            ?: profileOptions.firstOrNull { it.profileId == selectedProfile }?.label
            ?: deviceTypeLabel(selectedType, plural = true),
        kind = if (selectedDevice != null) HomeTargetKind.DEVICE else HomeTargetKind.DEVICE_TYPE,
        supportedQuickActions = supportedQuickActions,
        capabilities = intersectCapabilities(targetDevices),
        supportedByBackend = supportedQuickActions.isNotEmpty()
    )

    return QuickActionUiModel(
        target = target,
        typeOptions = typeOptions,
        profileOptions = profileOptions,
        devicesOfSelectedType = devicesOfSelectedType
    )
}

private fun quickActionsForTarget(target: HomeQuickActionTarget): List<HomeQuickAction> {
    if (!target.supportedByBackend) return emptyList()
    val candidates = when (target.deviceType) {
        "light" -> HomeLightQuickActions
        "switch" -> HomeSwitchQuickActions
        else -> emptyList()
    }
    return candidates.filter { it.actionId in target.supportedQuickActions }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppRoot(vm: MainViewModel) {
    val state by vm.ui.collectAsState()
    var currentTab by rememberSaveable { mutableStateOf(AppTab.HOME) }
    val availableTabs = remember(state.developerModeEnabled) {
        if (state.developerModeEnabled) AppTab.entries else AppTab.entries.filter { it != AppTab.DEV }
    }
    LaunchedEffect(state.developerModeEnabled) {
        if (!state.developerModeEnabled && currentTab == AppTab.DEV) {
            currentTab = AppTab.HOME
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(currentTab.title) }
            )
        },
        bottomBar = {
            NavigationBar {
                availableTabs.forEach { tab ->
                    NavigationBarItem(
                        selected = currentTab == tab,
                        onClick = { currentTab = tab },
                        icon = { Icon(imageVector = tab.icon, contentDescription = tab.contentDescription) },
                        label = { Text(tab.label) }
                    )
                }
            }
        }
    ) { innerPadding ->
        Box(modifier = Modifier.padding(innerPadding)) {
            Crossfade(targetState = currentTab, label = "tab") { tab ->
                when (tab) {
                    AppTab.HOME -> HomeScreen(
                        state = state,
                        onStartListening = vm::startListening,
                        onStopListening = vm::requestStopListening,
                        onCancelListening = vm::cancelListening,
                        onClarification = vm::selectClarificationOption,
                        onSelectArea = vm::selectHomeArea,
                        onSelectTargetDeviceType = vm::selectHomeTargetDeviceType,
                        onSelectTargetDevice = vm::selectHomeTargetDevice,
                        onSelectTargetControlProfile = vm::selectHomeTargetControlProfile,
                        onRunQuickAction = vm::runHomeQuickAction,
                        onSendText = vm::sendTextCommand
                    )

                    AppTab.SCENARIOS -> ScenarioScreen(
                        state = state,
                        onSelectArea = vm::selectHomeArea,
                        onPreviewScenario = vm::previewScenario,
                        onSaveScenario = vm::saveScenarioPreview,
                        onRefreshScenarioLibrary = vm::refreshScenarioLibrary,
                        onUpsertScenario = vm::upsertScenarioFromJson,
                        onDeleteScenario = vm::deleteScenarioById,
                        onDeveloperModeChange = vm::onDeveloperModeChanged
                    )

                    AppTab.DEV -> SettingsScreen(
                        state = state,
                        onGatewayChange = vm::onGatewayUrlChanged,
                        onApiKeyChange = vm::onApiKeyChanged,
                        onPingGateway = vm::pingGateway,
                        onDryRunChange = vm::onDryRunChanged,
                        onAsrEngineChange = vm::onAsrEngineChanged,
                        onParserChange = vm::onParserModeChanged,
                        onSpeechRateChange = vm::onSpeechRateChanged,
                        onSpeechPitchChange = vm::onSpeechPitchChanged,
                        onRefreshDiagnostics = vm::refreshDiagnostics,
                        onRerunLastClip = vm::rerunLastSavedClipComparison,
                        onSendText = vm::sendDevText,
                        onResendCommand = vm::resendRecentCommand,
                        onClearLogs = vm::clearLogs,
                        onDeveloperModeChange = vm::onDeveloperModeChanged
                    )
                }
            }
        }
    }
}

@Composable
private fun HomeScreen(
    state: UiState,
    onStartListening: () -> Unit,
    onStopListening: () -> Unit,
    onCancelListening: () -> Unit,
    onClarification: (String) -> Unit,
    onSelectArea: (String) -> Unit,
    onSelectTargetDeviceType: (String) -> Unit,
    onSelectTargetDevice: (String) -> Unit,
    onSelectTargetControlProfile: (String) -> Unit,
    onRunQuickAction: (String, String, String, String?) -> Unit,
    onSendText: (String) -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
            .animateContentSize(),
        verticalArrangement = Arrangement.spacedBy(20.dp)
    ) {
        RoomContextCard(
            state = state,
            onSelectArea = onSelectArea
        )
        VoiceControlCard(
            state = state,
            onStartListening = onStartListening,
            onStopListening = onStopListening,
            onCancelListening = onCancelListening
        )
        LastCommandCard(state = state)
        QuickActionsCard(
            state = state,
            onSelectTargetDeviceType = onSelectTargetDeviceType,
            onSelectTargetDevice = onSelectTargetDevice,
            onSelectTargetControlProfile = onSelectTargetControlProfile,
            onRunQuickAction = onRunQuickAction
        )
        HomeTextCommandCard(
            state = state,
            onSend = onSendText
        )
        AnimatedVisibility(visible = state.clarificationQuestion.isNotBlank()) {
            ClarificationCard(state = state, onClarification = onClarification)
        }
    }
}

@Composable
private fun ScenarioScreen(
    state: UiState,
    onSelectArea: (String) -> Unit,
    onPreviewScenario: (String) -> Unit,
    onSaveScenario: () -> Unit,
    onRefreshScenarioLibrary: (Boolean) -> Unit,
    onUpsertScenario: (String) -> Unit,
    onDeleteScenario: (String) -> Unit,
    onDeveloperModeChange: (Boolean) -> Unit
) {
    val selectedArea = state.selectedHomeAreaName.trim().ifBlank { state.lastAreaName.trim() }
    val visibleAreas = remember(selectedArea) {
        if (selectedArea.isBlank() || HomeAreaOptions.any { it.label == selectedArea }) {
            HomeAreaOptions
        } else {
            HomeAreaOptions + areaOptionFor(selectedArea)
        }
    }
    LaunchedEffect(Unit) {
        onRefreshScenarioLibrary(true)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
            .animateContentSize(),
        verticalArrangement = Arrangement.spacedBy(20.dp)
    ) {
        ElevatedCard {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                SectionHeader(
                    icon = Icons.Outlined.Notifications,
                    title = "Создание сценариев",
                    subtitle = "LLM переводит естественную фразу в preview automation для Home Assistant."
                )
                Text(
                    text = "Экран сначала строит и проверяет preview, затем сохраняет сценарий в Home Assistant отдельной кнопкой.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        ElevatedCard {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                SectionHeader(
                    title = "Комната по умолчанию",
                    subtitle = if (selectedArea.isBlank()) {
                        "Если комната не названа в фразе, будет использован выбранный контекст."
                    } else {
                        "Если в сценарии не указана комната, будет использована: $selectedArea"
                    }
                )
                visibleAreas.chunked(3).forEach { rowItems ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        rowItems.forEach { area ->
                            FilterChip(
                                selected = area.label == selectedArea,
                                onClick = { onSelectArea(area.label) },
                                label = { Text(area.label, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                                leadingIcon = {
                                    Icon(
                                        imageVector = area.icon,
                                        contentDescription = null,
                                        modifier = Modifier.size(18.dp)
                                    )
                                },
                                modifier = Modifier.weight(1f)
                            )
                        }
                        repeat(3 - rowItems.size) {
                            Spacer(modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
        }

        DevScenarioPreviewCard(
            state = state,
            enabled = !state.busy,
            onPreview = onPreviewScenario,
            onSave = onSaveScenario,
            showTechnicalDetails = state.developerModeEnabled
        )

        ScenarioLibraryCard(
            state = state,
            enabled = !state.busy,
            onRefresh = { onRefreshScenarioLibrary(false) },
            onUpsert = onUpsertScenario,
            onDelete = onDeleteScenario
        )

        ElevatedCard {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                SectionHeader(
                    title = "Примеры фраз",
                    subtitle = "Подходят для первых проверок authoring-пайплайна."
                )
                Text(
                    text = "• Каждый день в 20:00 включай в спальне тёплый свет, а в 00:00 выключай его.",
                    style = MaterialTheme.typography.bodySmall
                )
                Text(
                    text = "• Если после 19:00 в спальне есть движение и освещённость ниже 30 люкс, включай свет на 40%.",
                    style = MaterialTheme.typography.bodySmall
                )
                Text(
                    text = "• Когда дома никого нет, выключай все розетки в гостиной.",
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }

        if (state.lastCommandSource == "scenario") {
            LastCommandCard(state = state)
        }

        ElevatedCard {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    Text("Режим разработчика", style = MaterialTheme.typography.titleMedium)
                    Text(
                        text = "Показывает отдельную вкладку с диагностикой и тестовыми инструментами.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Switch(
                    checked = state.developerModeEnabled,
                    onCheckedChange = onDeveloperModeChange
                )
            }
        }
    }
}

@Composable
private fun RoomContextCard(
    state: UiState,
    onSelectArea: (String) -> Unit
) {
    val selectedArea = state.selectedHomeAreaName.trim().ifBlank { state.lastAreaName.trim() }
    val visibleAreas = remember(selectedArea) {
        if (selectedArea.isBlank() || HomeAreaOptions.any { it.label == selectedArea }) {
            HomeAreaOptions
        } else {
            HomeAreaOptions + areaOptionFor(selectedArea)
        }
    }
    val summaryItems = buildList {
        if (state.lastBrightness != null) add(Triple(Icons.Outlined.LightMode, "Яркость", "${state.lastBrightness}%"))
        if (state.lastColorName.isNotBlank()) {
            add(Triple(Icons.Outlined.ColorLens, "Цвет", state.lastColorName))
        } else if (state.lastColorTempKelvin != null) {
            add(Triple(Icons.Outlined.WbIncandescent, "Температура", "${state.lastColorTempKelvin} K"))
        }
    }

    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            SectionHeader(
                title = "Комната",
                subtitle = if (selectedArea.isBlank()) "Выберите комнату" else null
            )
            visibleAreas.chunked(3).forEach { rowItems ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    rowItems.forEach { area ->
                        FilterChip(
                            selected = area.label == selectedArea,
                            onClick = { onSelectArea(area.label) },
                            label = { Text(area.label, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                            leadingIcon = {
                                Icon(
                                    imageVector = area.icon,
                                    contentDescription = null,
                                    modifier = Modifier.size(18.dp)
                                )
                            },
                            modifier = Modifier.weight(1f)
                        )
                    }
                    repeat(3 - rowItems.size) {
                        Spacer(modifier = Modifier.weight(1f))
                    }
                }
            }
            if (summaryItems.isNotEmpty()) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    summaryItems.take(3).forEach { (icon, label, value) ->
                        ContextBadge(
                            icon = icon,
                            label = label,
                            value = value,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ContextBadge(
    icon: ImageVector,
    label: String,
    value: String,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier,
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = MaterialTheme.shapes.medium
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Surface(
                color = MaterialTheme.colorScheme.primary.copy(alpha = 0.10f),
                shape = CircleShape
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    modifier = Modifier
                        .padding(8.dp)
                        .size(16.dp),
                    tint = MaterialTheme.colorScheme.primary
                )
            }
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = value,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

@Composable
private fun SectionHeader(
    icon: ImageVector? = null,
    title: String,
    subtitle: String? = null
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (icon != null) {
            Surface(
                color = MaterialTheme.colorScheme.secondaryContainer,
                shape = CircleShape
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    modifier = Modifier
                        .padding(10.dp)
                        .size(20.dp),
                    tint = MaterialTheme.colorScheme.onSecondaryContainer
                )
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
            if (!subtitle.isNullOrBlank()) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun QuickActionsCard(
    state: UiState,
    onSelectTargetDeviceType: (String) -> Unit,
    onSelectTargetDevice: (String) -> Unit,
    onSelectTargetControlProfile: (String) -> Unit,
    onRunQuickAction: (String, String, String, String?) -> Unit
) {
    val selectedArea = state.selectedHomeAreaName.trim().ifBlank { state.lastAreaName.trim() }
    val enabled = !state.busy && selectedArea.isNotBlank()
    val quickActionUi = remember(
        state.selectedHomeAreaName,
        state.lastAreaName,
        state.deviceCatalog,
        state.selectedTarget,
        state.lastEntityIds
    ) {
        resolveQuickActionUiModel(state)
    }
    val quickActions = quickActionUi?.let { quickActionsForTarget(it.target) }.orEmpty()

    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            SectionHeader(
                title = "Быстрые действия",
                subtitle = if (selectedArea.isBlank()) {
                    "Сначала выберите комнату"
                } else if (quickActionUi?.target?.supportedByBackend == false) {
                    "Для этого типа устройства быстрые действия появятся позже"
                } else {
                    null
                }
            )

            if (selectedArea.isNotBlank() && quickActionUi != null) {
                QuickActionTargetSummary(
                    areaName = selectedArea,
                    target = quickActionUi.target
                )

                if (quickActionUi.typeOptions.size > 1) {
                    HomeStringFilterSection(
                        title = "Тип",
                        rows = quickActionUi.typeOptions.chunked(3),
                        selectedValue = quickActionUi.target.deviceType,
                        onSelect = onSelectTargetDeviceType
                    ) { deviceType ->
                        HomeFilterChipLabel(
                            icon = deviceTypeIcon(deviceType),
                            text = deviceTypeLabel(deviceType, plural = true)
                        )
                    }
                }

                if (quickActionUi.profileOptions.isNotEmpty() && quickActionUi.target.kind != HomeTargetKind.DEVICE) {
                    val profileIds = listOf("") + quickActionUi.profileOptions.map { it.profileId }
                    HomeStringFilterSection(
                        title = "Профиль",
                        rows = profileIds.chunked(2),
                        selectedValue = quickActionUi.target.controlProfile,
                        onSelect = onSelectTargetControlProfile
                    ) { profileId ->
                        if (profileId.isBlank()) {
                            HomeFilterChipLabel(
                                icon = deviceTypeIcon(quickActionUi.target.deviceType),
                                text = "Авто"
                            )
                        } else {
                            val profile = quickActionUi.profileOptions.firstOrNull { it.profileId == profileId }
                            HomeFilterChipLabel(
                                icon = controlProfileIcon(profileId),
                                text = profile?.label?.ifBlank { controlProfileLabel(profileId) }
                                    ?: controlProfileLabel(profileId)
                            )
                        }
                    }
                }

                if (quickActionUi.devicesOfSelectedType.size > 1) {
                    val selectedDeviceId = if (quickActionUi.target.kind == HomeTargetKind.DEVICE) {
                        state.selectedTarget.deviceId
                    } else {
                        ""
                    }
                    val allOption = DeviceCatalogDevice(
                        deviceId = "",
                        name = "Все",
                        deviceType = quickActionUi.target.deviceType,
                        areaId = null,
                        areaName = selectedArea,
                        entityId = null,
                        controlProfile = quickActionUi.target.controlProfile,
                        supportedQuickActions = quickActionUi.target.supportedQuickActions,
                        capabilities = quickActionUi.target.capabilities
                    )
                    HomeDeviceFilterSection(
                        title = "Устройство",
                        rows = (listOf(allOption) + quickActionUi.devicesOfSelectedType).chunked(2),
                        selectedValue = selectedDeviceId,
                        onSelect = { deviceId ->
                            if (deviceId.isBlank()) {
                                onSelectTargetDeviceType(quickActionUi.target.deviceType)
                            } else {
                                onSelectTargetDevice(deviceId)
                            }
                        }
                    ) { device ->
                        if (device.deviceId.isBlank()) {
                            HomeFilterChipLabel(
                                icon = deviceTypeIcon(device.deviceType),
                                text = "Все ${deviceTypeLabel(device.deviceType, plural = true).lowercase(Locale.US)}"
                            )
                        } else {
                            HomeFilterChipLabel(
                                icon = deviceTypeIcon(device.deviceType),
                                text = deviceDisplayName(device, quickActionUi.devicesOfSelectedType)
                            )
                        }
                    }
                }
            }

            if (selectedArea.isBlank()) return@ElevatedCard
            if (quickActionUi?.target?.supportedByBackend == false) {
                Text(
                    text = "Для этого типа устройства быстрые действия появятся позже. Выбор цели уже сохранён.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                return@ElevatedCard
            }

            quickActions.chunked(2).forEach { rowItems ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    rowItems.forEach { action ->
                        val buttonModifier = Modifier.weight(1f)
                        if (action.prominent) {
                            Button(
                                onClick = {
                                    val target = quickActionUi?.target ?: return@Button
                                    onRunQuickAction(
                                        action.actionId,
                                        target.areaName,
                                        target.deviceType,
                                        target.deviceId
                                    )
                                },
                                enabled = enabled,
                                modifier = buttonModifier.height(72.dp),
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                                    contentColor = MaterialTheme.colorScheme.onPrimaryContainer
                                ),
                                contentPadding = PaddingValues(horizontal = 14.dp, vertical = 10.dp)
                            ) {
                                QuickActionContent(
                                    action = action,
                                    prominent = true
                                )
                            }
                        } else {
                            OutlinedButton(
                                onClick = {
                                    val target = quickActionUi?.target ?: return@OutlinedButton
                                    onRunQuickAction(
                                        action.actionId,
                                        target.areaName,
                                        target.deviceType,
                                        target.deviceId
                                    )
                                },
                                enabled = enabled,
                                modifier = buttonModifier.height(72.dp),
                                contentPadding = PaddingValues(horizontal = 14.dp, vertical = 10.dp)
                            ) {
                                QuickActionContent(
                                    action = action,
                                    prominent = false
                                )
                            }
                        }
                    }
                    if (rowItems.size < 2) {
                        Spacer(modifier = Modifier.weight(1f))
                    }
                }
            }
        }
    }
}

@Composable
private fun QuickActionTargetSummary(
    areaName: String,
    target: HomeQuickActionTarget
) {
    val summaryItems = buildList {
        add(Triple(deviceTypeIcon(target.deviceType), "Тип", deviceTypeLabel(target.deviceType, plural = true)))
        if (target.controlProfile.isNotBlank()) {
            add(Triple(controlProfileIcon(target.controlProfile), "Профиль", controlProfileLabel(target.controlProfile)))
        }
        add(
            Triple(
                when (target.kind) {
                    HomeTargetKind.DEVICE -> Icons.Outlined.Info
                    HomeTargetKind.DEVICE_TYPE -> Icons.Outlined.Visibility
                },
                if (target.kind == HomeTargetKind.DEVICE) "Цель" else "Охват",
                target.label
            )
        )
    }

    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
        shape = MaterialTheme.shapes.large
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text(
                text = areaName,
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            summaryItems.chunked(2).forEach { rowItems ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    rowItems.forEach { (icon, label, value) ->
                        ContextBadge(
                            icon = icon,
                            label = label,
                            value = value,
                            modifier = Modifier.weight(1f)
                        )
                    }
                    repeat(2 - rowItems.size) {
                        Spacer(modifier = Modifier.weight(1f))
                    }
                }
            }
        }
    }
}

@Composable
private fun HomeStringFilterSection(
    title: String,
    rows: List<List<String>>,
    selectedValue: String,
    onSelect: (String) -> Unit,
    content: @Composable (String) -> Unit
) {
    Text(
        text = title,
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
    rows.forEach { rowItems ->
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            rowItems.forEach { value ->
                FilterChip(
                    selected = value == selectedValue,
                    onClick = { onSelect(value) },
                    label = { content(value) },
                    modifier = Modifier.weight(1f)
                )
            }
            repeat(3 - rowItems.size) {
                Spacer(modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun HomeDeviceFilterSection(
    title: String,
    rows: List<List<DeviceCatalogDevice>>,
    selectedValue: String,
    onSelect: (String) -> Unit,
    content: @Composable (DeviceCatalogDevice) -> Unit
) {
    Text(
        text = title,
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
    rows.forEach { rowItems ->
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            rowItems.forEach { device ->
                FilterChip(
                    selected = device.deviceId == selectedValue,
                    onClick = { onSelect(device.deviceId) },
                    label = { content(device) },
                    modifier = Modifier.weight(1f)
                )
            }
            repeat(2 - rowItems.size) {
                Spacer(modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun HomeFilterChipLabel(
    icon: ImageVector,
    text: String
) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            modifier = Modifier.size(16.dp)
        )
        Text(
            text = text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun QuickActionContent(
    action: HomeQuickAction,
    prominent: Boolean
) {
    val badgeColor = if (prominent) {
        MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.10f)
    } else {
        MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)
    }
    val iconTint = if (prominent) {
        MaterialTheme.colorScheme.onPrimaryContainer
    } else {
        MaterialTheme.colorScheme.primary
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Surface(
            color = badgeColor,
            shape = CircleShape
        ) {
            Icon(
                imageVector = action.icon,
                contentDescription = null,
                modifier = Modifier
                    .padding(9.dp)
                    .size(17.dp),
                tint = iconTint
            )
        }
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp),
            horizontalAlignment = Alignment.Start
        ) {
            Text(
                text = action.title,
                maxLines = 1,
                fontWeight = if (prominent) FontWeight.SemiBold else FontWeight.Medium
            )
        }
    }
}

@Composable
private fun HomeTextCommandCard(
    state: UiState,
    onSend: (String) -> Unit
) {
    var text by rememberSaveable { mutableStateOf("") }
    val selectedArea = state.selectedHomeAreaName.trim().ifBlank { state.lastAreaName.trim() }

    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            SectionHeader(
                title = "Текстовая команда",
                subtitle = if (selectedArea.isBlank()) {
                    "Можно указать комнату прямо в тексте"
                } else {
                    null
                }
            )
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text("Что сделать") },
                placeholder = {
                    Text(
                        if (selectedArea.isBlank()) {
                            "Например: включи свет в спальне"
                        } else {
                            "Например: сделай теплее"
                        }
                    )
                },
                modifier = Modifier.fillMaxWidth(),
                supportingText = if (selectedArea.isBlank()) {
                    {
                        Text("Если комната не выбрана, укажите её в команде.")
                    }
                } else {
                    null
                }
            )
            Button(
                onClick = {
                    val trimmed = text.trim()
                    if (trimmed.isNotBlank()) {
                        onSend(trimmed)
                        text = ""
                    }
                },
                enabled = !state.busy && text.trim().isNotBlank(),
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Outlined.Send,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.size(8.dp))
                Text("Отправить")
            }
        }
    }
}


@Composable
private fun VoiceControlCard(
    state: UiState,
    onStartListening: () -> Unit,
    onStopListening: () -> Unit,
    onCancelListening: () -> Unit
) {
    var touchStartX by remember { mutableStateOf(0f) }
    var touchStartY by remember { mutableStateOf(0f) }
    var cancelGestureArmed by remember { mutableStateOf(false) }
    val haptic = LocalHapticFeedback.current
    val view = LocalView.current
    val cancelThresholdPx = with(LocalDensity.current) { 72.dp.toPx() }
    val cancelButtonShiftX by animateFloatAsState(
        targetValue = if (cancelGestureArmed) 18f else 0f,
        animationSpec = tween(durationMillis = 160, easing = FastOutSlowInEasing),
        label = "cancelShiftX"
    )
    val cancelButtonShiftY by animateFloatAsState(
        targetValue = if (cancelGestureArmed) -10f else 0f,
        animationSpec = tween(durationMillis = 160, easing = FastOutSlowInEasing),
        label = "cancelShiftY"
    )
    val cancelButtonScale by animateFloatAsState(
        targetValue = if (cancelGestureArmed) 0.92f else 1f,
        animationSpec = tween(durationMillis = 160, easing = FastOutSlowInEasing),
        label = "cancelScale"
    )
    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = "Голосовое управление",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(160.dp)
            ) {
                ListeningPulse(isActive = state.isListening)
                FilledIconButton(
                    onClick = {},
                    enabled = !state.busy && state.asrReady && !state.isRecognizing,
                    modifier = Modifier
                        .size(88.dp)
                        .graphicsLayer {
                            translationX = cancelButtonShiftX
                            translationY = cancelButtonShiftY
                            scaleX = cancelButtonScale
                            scaleY = cancelButtonScale
                        }
                        .pointerInteropFilter { event ->
                            when (event.action) {
                                MotionEvent.ACTION_DOWN -> {
                                    touchStartX = event.x
                                    touchStartY = event.y
                                    cancelGestureArmed = false
                                    if (!state.busy && state.asrReady && !state.isListening && !state.isRecognizing) {
                                        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                        onStartListening()
                                    }
                                    true
                                }
                                MotionEvent.ACTION_MOVE -> {
                                    if (state.isListening) {
                                        val dx = event.x - touchStartX
                                        val dy = event.y - touchStartY
                                        cancelGestureArmed =
                                            abs(dx) >= cancelThresholdPx || abs(dy) >= cancelThresholdPx
                                    }
                                    true
                                }
                                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                                    if (state.isListening) {
                                        if (cancelGestureArmed || event.action == MotionEvent.ACTION_CANCEL) {
                                            onCancelListening()
                                        } else {
                                            haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                            view.playSoundEffect(SoundEffectConstants.CLICK)
                                            onStopListening()
                                        }
                                    }
                                    cancelGestureArmed = false
                                    true
                                }
                                else -> false
                            }
                        }
                ) {
                    val icon = if (state.isListening) Icons.Outlined.StopCircle else Icons.Outlined.Mic
                    Icon(icon, contentDescription = "Голосовое управление")
                }
            }
            AnimatedVisibility(visible = state.isListening || state.isFinishing) {
                CancelGestureHint(
                    cancelGestureArmed = cancelGestureArmed,
                    isFinishing = state.isFinishing
                )
            }
            LevelMeter(level = state.audioLevel, isActive = state.isListening)
            val voiceStatusText = when (state.voiceUiState) {
                VoiceUiState.IDLE -> "Нажмите и удерживайте"
                VoiceUiState.ARMING -> "Подготавливаю микрофон..."
                VoiceUiState.LISTENING ->
                    when {
                        cancelGestureArmed -> "Отпустите палец, чтобы отменить"
                        state.speechActive -> "Слушаю"
                        state.speechDetected -> "Пауза в речи. Отпустите кнопку или продолжайте говорить"
                        else -> "Слушаю"
                    }
                VoiceUiState.FINISHING -> "Завершаю фразу"
                VoiceUiState.RECOGNIZING -> "Распознаю"
                VoiceUiState.ERROR -> "Не расслышал, повторите"
            }
            Text(
                text = voiceStatusText,
                style = MaterialTheme.typography.bodyMedium
            )
            AnimatedVisibility(visible = state.lastError.isNotBlank() && state.voiceUiState == VoiceUiState.ERROR) {
                Text(
                    text = state.lastError,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error
                )
            }
        }
    }
}

@Composable
private fun ListeningPulse(isActive: Boolean) {
    if (!isActive) return

    val transition = rememberInfiniteTransition(label = "pulse")
    val scale by transition.animateFloat(
        initialValue = 0.9f,
        targetValue = 1.3f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 900, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulseScale"
    )
    Box(
        modifier = Modifier
            .size(140.dp)
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
            }
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.2f))
    )
}

@Composable
private fun CancelGestureHint(
    cancelGestureArmed: Boolean,
    isFinishing: Boolean
) {
    val containerColor = when {
        cancelGestureArmed -> MaterialTheme.colorScheme.errorContainer
        isFinishing -> MaterialTheme.colorScheme.secondaryContainer
        else -> MaterialTheme.colorScheme.surfaceVariant
    }
    val contentColor = when {
        cancelGestureArmed -> MaterialTheme.colorScheme.onErrorContainer
        isFinishing -> MaterialTheme.colorScheme.onSecondaryContainer
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    val hintText = when {
        cancelGestureArmed -> "Отпустите, чтобы отменить"
        isFinishing -> "Фраза принята"
        else -> "Уведите палец в сторону для отмены"
    }

    Surface(
        color = containerColor,
        contentColor = contentColor,
        shape = MaterialTheme.shapes.large
    ) {
        Text(
            text = hintText,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
            style = MaterialTheme.typography.labelLarge
        )
    }
}

@Composable
private fun LevelMeter(level: Float, isActive: Boolean) {
    val animatedLevel by animateFloatAsState(
        targetValue = if (isActive) level else 0f,
        animationSpec = tween(durationMillis = 200, easing = FastOutSlowInEasing),
        label = "audioLevel"
    )
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        LinearProgressIndicator(
            progress = { animatedLevel },
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
        )
        Text(
            text = "Уровень голоса",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun DevTextSender(
    enabled: Boolean,
    onSend: (String) -> Unit
) {
    var text by rememberSaveable { mutableStateOf("") }

    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text("Текстовая проверка", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text("Введите текст") },
                modifier = Modifier.fillMaxWidth()
            )
            Button(
                onClick = {
                    val trimmed = text.trim()
                    if (trimmed.isNotBlank()) {
                        onSend(trimmed)
                        text = ""
                    }
                },
                enabled = enabled,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Отправить")
            }
        }
    }
}

@Composable
private fun LastCommandCard(state: UiState) {
    val commandText = state.lastCommandText.trim()
    if (commandText.isBlank()) return

    val sourceLabel = when (state.lastCommandSource.lowercase()) {
        "voice" -> "Голос"
        "text" -> "Текст"
        "quick" -> "Быстро"
        "scenario" -> "Сценарий"
        else -> ""
    }
    val commandLine = if (sourceLabel.isBlank()) {
        commandText
    } else {
        "$sourceLabel: $commandText"
    }

    val answerLine = when {
        state.lastError.isNotBlank() -> "Ошибка: ${state.lastError}"
        state.lastSayText.isNotBlank() -> state.lastSayText
        else -> null
    }

    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Text("Последняя команда", style = MaterialTheme.typography.titleMedium)
            Text(
                text = commandLine,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            if (!answerLine.isNullOrBlank()) {
                Text(
                    text = answerLine,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun DevScenarioPreviewCard(
    state: UiState,
    enabled: Boolean,
    onPreview: (String) -> Unit,
    onSave: () -> Unit,
    showTechnicalDetails: Boolean
) {
    var text by rememberSaveable { mutableStateOf("") }
    val hasResult = state.scenarioPreviewStatus.isNotBlank() ||
        state.scenarioPreviewParsedBundleJson.isNotBlank() ||
        state.scenarioPreviewAutomationsJson.isNotBlank()
    val canSave = enabled &&
        state.scenarioPreviewStatus == "PREVIEW_READY" &&
        state.scenarioPreviewAutomationCount > 0 &&
        state.scenarioPreviewAutomationsJson.isNotBlank()

    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text("Предпросмотр сценария", style = MaterialTheme.typography.titleMedium)
            Text(
                text = "LLM строит структуру automation и позволяет сохранить результат в Home Assistant.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text("Опишите сценарий") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3
            )
            Button(
                onClick = {
                    val trimmed = text.trim()
                    if (trimmed.isNotBlank()) {
                        onPreview(trimmed)
                    }
                },
                enabled = enabled,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Построить сценарий")
            }
            OutlinedButton(
                onClick = onSave,
                enabled = canSave,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Сохранить в Home Assistant")
            }
            if (hasResult) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        text = buildString {
                            append("Статус: ${state.scenarioPreviewStatus.ifBlank { "—" }}")
                            if (state.scenarioPreviewTitle.isNotBlank()) {
                                append(" · ${state.scenarioPreviewTitle}")
                            }
                        },
                        style = MaterialTheme.typography.labelLarge
                    )
                    Text(
                        text = "Правил: ${state.scenarioPreviewRuleCount} · automation: ${state.scenarioPreviewAutomationCount}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    if (state.scenarioPreviewSayText.isNotBlank()) {
                        Text(state.scenarioPreviewSayText, style = MaterialTheme.typography.bodyMedium)
                    }
                    if (state.scenarioPreviewQuestion.isNotBlank()) {
                        Text(
                            text = "Нужно уточнение: ${state.scenarioPreviewQuestion}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                    if (showTechnicalDetails) {
                        Text(
                            text = buildString {
                                append("parse=${state.scenarioPreviewParseMs} ms")
                                append(" · validate=${state.scenarioPreviewValidateMs} ms")
                                append(" · compile=${state.scenarioPreviewCompileMs} ms")
                                if (state.scenarioPreviewLlmMs > 0L) {
                                    append(" · llm=${state.scenarioPreviewLlmMs} ms")
                                }
                            },
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    if (showTechnicalDetails && (state.scenarioPreviewLlmPromptTokens > 0 || state.scenarioPreviewLlmCompletionTokens > 0)) {
                        Text(
                            text = buildString {
                                append("prompt=${state.scenarioPreviewLlmPromptTokens}")
                                append(" · completion=${state.scenarioPreviewLlmCompletionTokens}")
                                append(" · total=${state.scenarioPreviewLlmTotalTokens}")
                                if (state.scenarioPreviewLlmModel.isNotBlank()) {
                                    append(" · ${state.scenarioPreviewLlmModel}")
                                }
                            },
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    if (showTechnicalDetails && state.scenarioPreviewParsedBundleJson.isNotBlank()) {
                        JsonPreviewBlock("Parsed bundle", state.scenarioPreviewParsedBundleJson)
                    }
                    if (showTechnicalDetails && state.scenarioPreviewValidatedBundleJson.isNotBlank()) {
                        JsonPreviewBlock("Validated bundle", state.scenarioPreviewValidatedBundleJson)
                    }
                    if (showTechnicalDetails && state.scenarioPreviewAutomationsJson.isNotBlank()) {
                        JsonPreviewBlock("Automations", state.scenarioPreviewAutomationsJson)
                    }
                    if (state.scenarioSaveStatus.isNotBlank()) {
                        Text(
                            text = "Сохранение: ${state.scenarioSaveStatus}",
                            style = MaterialTheme.typography.labelLarge
                        )
                        Text(
                            text = "Сохранено: ${state.scenarioSaveSavedAutomationCount} · в файле: ${state.scenarioSaveFileAutomationCount}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        if (state.scenarioSaveSayText.isNotBlank()) {
                            Text(
                                text = state.scenarioSaveSayText,
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                        if (state.scenarioSaveIncludeHint.isNotBlank()) {
                            Text(
                                text = state.scenarioSaveIncludeHint,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.primary
                            )
                        }
                        if (state.scenarioSaveStorageFile.isNotBlank()) {
                            Text(
                                text = "Файл: ${state.scenarioSaveStorageFile}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ScenarioLibraryCard(
    state: UiState,
    enabled: Boolean,
    onRefresh: () -> Unit,
    onUpsert: (String) -> Unit,
    onDelete: (String) -> Unit
) {
    var editorVisible by rememberSaveable { mutableStateOf(false) }
    var editorTitle by rememberSaveable { mutableStateOf("") }
    var editorText by rememberSaveable { mutableStateOf("") }
    var deleteCandidateId by rememberSaveable { mutableStateOf("") }

    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    Text("Сохранённые сценарии", style = MaterialTheme.typography.titleMedium)
                    Text(
                        text = "Можно редактировать JSON вручную и удалять сценарии.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                OutlinedButton(
                    onClick = onRefresh,
                    enabled = enabled && !state.scenarioLibraryLoading
                ) {
                    Text("Обновить")
                }
            }

            if (state.scenarioLibraryLoading) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }
            if (state.scenarioLibraryError.isNotBlank()) {
                Text(
                    text = state.scenarioLibraryError,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error
                )
            }

            if (state.scenarioLibraryStorageFile.isNotBlank()) {
                Text(
                    text = "Файл: ${state.scenarioLibraryStorageFile}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            if (state.scenarioLibraryItems.isEmpty() && !state.scenarioLibraryLoading) {
                Text(
                    text = "Пока нет сохранённых сценариев. Создайте первый через блок предпросмотра выше.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            } else {
                state.scenarioLibraryItems.forEach { item ->
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
                        shape = MaterialTheme.shapes.medium
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Text(item.alias, style = MaterialTheme.typography.titleSmall)
                            Text(
                                text = "ID: ${item.automationId}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                text = "${item.triggerSummary} · ${item.actionSummary}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedButton(
                                    onClick = {
                                        editorTitle = item.alias
                                        editorText = item.automationJson
                                        editorVisible = true
                                    },
                                    enabled = enabled,
                                    modifier = Modifier.weight(1f)
                                ) {
                                    Text("Редактировать JSON")
                                }
                                TextButton(
                                    onClick = { deleteCandidateId = item.automationId },
                                    enabled = enabled,
                                    modifier = Modifier.weight(1f)
                                ) {
                                    Text("Удалить")
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (editorVisible) {
        AlertDialog(
            onDismissRequest = { editorVisible = false },
            title = { Text("Редактирование: $editorTitle") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = editorText,
                        onValueChange = { editorText = it },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 10,
                        label = { Text("Automation JSON") }
                    )
                    Text(
                        text = "Нужно сохранить корректный JSON-объект automation с полем id.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onUpsert(editorText)
                        editorVisible = false
                    },
                    enabled = enabled && editorText.isNotBlank()
                ) {
                    Text("Сохранить")
                }
            },
            dismissButton = {
                TextButton(onClick = { editorVisible = false }) { Text("Отмена") }
            }
        )
    }

    if (deleteCandidateId.isNotBlank()) {
        AlertDialog(
            onDismissRequest = { deleteCandidateId = "" },
            title = { Text("Удалить сценарий?") },
            text = { Text("ID: $deleteCandidateId") },
            confirmButton = {
                TextButton(
                    onClick = {
                        onDelete(deleteCandidateId)
                        deleteCandidateId = ""
                    },
                    enabled = enabled
                ) { Text("Удалить") }
            },
            dismissButton = {
                TextButton(onClick = { deleteCandidateId = "" }) { Text("Отмена") }
            }
        )
    }
}

@Composable
private fun JsonPreviewBlock(
    title: String,
    value: String
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.labelLarge)
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.medium,
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f)
        ) {
            SelectionContainer {
                Text(
                    text = value,
                    modifier = Modifier.padding(12.dp),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun ClarificationCard(
    state: UiState,
    onClarification: (String) -> Unit
) {
    if (state.clarificationQuestion.isBlank()) return

    ElevatedCard(colors = CardDefaults.elevatedCardColors()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text("Нужно уточнение", style = MaterialTheme.typography.titleMedium)
            Text(state.clarificationQuestion)
            state.clarificationOptions.forEach { option ->
                Button(
                    onClick = { onClarification(option) },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(option, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

@Composable
private fun RecentCommandsCard(
    commands: List<RecentCommand>,
    onResend: (String) -> Unit
) {
    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text("Недавние команды", style = MaterialTheme.typography.titleMedium)
            if (commands.isEmpty()) {
                Text(
                    text = "Здесь появятся успешно выполненные команды.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            } else {
                val timeFormatter = remember {
                    SimpleDateFormat("HH:mm:ss", Locale.getDefault())
                }
                commands.take(5).forEach { cmd ->
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Button(
                            onClick = { onResend(cmd.text) },
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(cmd.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        Text(
                            text = "${timeFormatter.format(Date(cmd.timestamp))} · ${cmd.status}",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TipsCard(onDismiss: () -> Unit) {
    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text("Советы по началу", style = MaterialTheme.typography.titleMedium)
            Text("• Удерживайте кнопку микрофона и говорите, когда увидите активный индикатор.", style = MaterialTheme.typography.bodySmall)
            Text("• Нужна диагностика? Раскройте детали под кнопкой, чтобы увидеть состояние связи.", style = MaterialTheme.typography.bodySmall)
            Text("• Потренируйтесь с текстовым вводом ниже, прежде чем отдавать команды голосом.", style = MaterialTheme.typography.bodySmall)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End
            ) {
                TextButton(onClick = onDismiss) {
                    Text("Понятно")
                }
            }
        }
    }
}

@Composable
private fun DeveloperLogsCard(
    logs: List<LogEntry>,
    onClear: () -> Unit
) {
    val displayLogs = remember(logs) { logs.takeLast(6).asReversed() }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("Последние события", style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = onClear, enabled = logs.isNotEmpty()) {
                Text("Очистить")
            }
        }
        if (displayLogs.isEmpty()) {
            Text(
                text = "Журнал пока пуст.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        } else {
            displayLogs.forEach { entry ->
                LogEntryCard(entry)
            }
        }
    }
}

@Composable
private fun DeveloperConnectionCard(
    state: UiState,
    onPingGateway: () -> Unit
) {
    val networkStatus = state.networkStatus
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text("Соединение", style = MaterialTheme.typography.titleMedium)
        Text(
            text = networkStatus.label,
            style = MaterialTheme.typography.bodyMedium,
            color = if (networkStatus.ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
        )
        networkStatus.detailLines.forEach { line ->
            Text(
                text = line,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        if (networkStatus.latencyMs != null) {
            Text(
                text = "Задержка: ${networkStatus.latencyMs} мс",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        OutlinedButton(
            onClick = onPingGateway,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Проверить соединение")
        }
    }
}

@Composable
private fun DeveloperSectionCard(
    title: String,
    subtitle: String,
    expanded: Boolean,
    onToggle: () -> Unit,
    content: @Composable () -> Unit
) {
    ElevatedCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .animateContentSize()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(MaterialTheme.shapes.medium)
                    .clickable(onClick = onToggle)
                    .padding(vertical = 2.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(2.dp)
                ) {
                    Text(title, style = MaterialTheme.typography.titleMedium)
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = if (expanded) 2 else 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                IconButton(onClick = onToggle) {
                    Icon(
                        imageVector = Icons.Outlined.ExpandMore,
                        contentDescription = title,
                        modifier = Modifier.graphicsLayer {
                            rotationZ = if (expanded) 180f else 0f
                        }
                    )
                }
            }
            AnimatedVisibility(visible = expanded) {
                Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    content()
                }
            }
        }
    }
}

@Composable
private fun SettingsScreen(
    state: UiState,
    onGatewayChange: (String) -> Unit,
    onApiKeyChange: (String) -> Unit,
    onPingGateway: () -> Unit,
    onDryRunChange: (Boolean) -> Unit,
    onAsrEngineChange: (String) -> Unit,
    onParserChange: (String) -> Unit,
    onSpeechRateChange: (Float) -> Unit,
    onSpeechPitchChange: (Float) -> Unit,
    onRefreshDiagnostics: () -> Unit,
    onRerunLastClip: () -> Unit,
    onSendText: (String) -> Unit,
    onResendCommand: (String) -> Unit,
    onClearLogs: () -> Unit,
    onDeveloperModeChange: (Boolean) -> Unit
) {
    var showDiagnostics by rememberSaveable { mutableStateOf(false) }
    var connectionExpanded by rememberSaveable { mutableStateOf(true) }
    var toolsExpanded by rememberSaveable { mutableStateOf(false) }
    var speechExpanded by rememberSaveable { mutableStateOf(false) }
    var diagnosticsExpanded by rememberSaveable { mutableStateOf(false) }
    var apiKeyVisible by rememberSaveable { mutableStateOf(false) }
    val engineLabel = remember(state.asrEngine) { AsrEngineType.fromStorage(state.asrEngine).label }
    val networkSubtitle = buildString {
        append(state.networkStatus.label)
        append(" · ")
        append(if (state.dryRun) "dry_run" else "live")
    }
    val toolsSubtitle = buildString {
        append("${state.recentCommands.size} команд")
        append(" · ")
        append("${state.logs.size} событий")
    }
    val speechSubtitle = buildString {
        append(engineLabel)
        append(" · ")
        append(state.parserMode)
        append(" · TTS ")
        append("%.2f".format(state.speechRate))
        append("x/")
        append("%.2f".format(state.speechPitch))
        append("x")
    }
    val diagnosticsSubtitle = buildString {
        append("${state.evalHistoryCount} прогонов")
        if (state.lastClipWavPath.isNotBlank()) {
            append(" · есть клип")
        }
        if (state.lastAreaName.isNotBlank()) {
            append(" · ${state.lastAreaName}")
        }
    }
    val allExpanded = connectionExpanded && toolsExpanded && speechExpanded && diagnosticsExpanded
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Text("Меню разработчика", style = MaterialTheme.typography.titleMedium)
                Text(
                    text = "Настройки, тесты и диагностика собраны в сворачиваемые секции.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            TextButton(
                onClick = {
                    val next = !allExpanded
                    connectionExpanded = next
                    toolsExpanded = next
                    speechExpanded = next
                    diagnosticsExpanded = next
                }
            ) {
                Text(if (allExpanded) "Свернуть всё" else "Развернуть всё")
            }
        }

        ElevatedCard {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    Text("Вкладка разработчика", style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = "Скрывает или показывает отдельную вкладку с диагностикой.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Switch(
                    checked = state.developerModeEnabled,
                    onCheckedChange = onDeveloperModeChange
                )
            }
        }

        DeveloperSectionCard(
            title = "Соединение и gateway",
            subtitle = networkSubtitle,
            expanded = connectionExpanded,
            onToggle = { connectionExpanded = !connectionExpanded }
        ) {
            DeveloperConnectionCard(
                state = state,
                onPingGateway = onPingGateway
            )
            OutlinedTextField(
                value = state.gatewayUrl,
                onValueChange = onGatewayChange,
                label = { Text("Gateway URL") },
                modifier = Modifier.fillMaxWidth(),
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Next
                )
            )
            OutlinedTextField(
                value = state.apiKey,
                onValueChange = onApiKeyChange,
                label = { Text("X-API-Key") },
                modifier = Modifier.fillMaxWidth(),
                visualTransformation = if (apiKeyVisible) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    val icon = if (apiKeyVisible) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility
                    IconButton(onClick = { apiKeyVisible = !apiKeyVisible }) {
                        Icon(imageVector = icon, contentDescription = "API key visibility")
                    }
                },
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                    keyboardType = KeyboardType.Password,
                    imeAction = ImeAction.Done
                )
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text("dry_run")
                    Text(
                        text = "Команды не будут отправляться в Home Assistant.",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Switch(checked = state.dryRun, onCheckedChange = onDryRunChange)
            }
        }

        DeveloperSectionCard(
            title = "Инструменты тестирования",
            subtitle = toolsSubtitle,
            expanded = toolsExpanded,
            onToggle = { toolsExpanded = !toolsExpanded }
        ) {
            DevTextSender(enabled = !state.busy, onSend = onSendText)
            RecentCommandsCard(commands = state.recentCommands, onResend = onResendCommand)
            DeveloperLogsCard(
                logs = state.logs,
                onClear = onClearLogs
            )
        }

        DeveloperSectionCard(
            title = "ASR, parser и TTS",
            subtitle = speechSubtitle,
            expanded = speechExpanded,
            onToggle = { speechExpanded = !speechExpanded }
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Голосовой движок", style = MaterialTheme.typography.titleMedium)
                val engineOptions = listOf(
                    Triple(AsrEngineType.VOSK.storageValue, "Vosk", "Локальный офлайн-движок на базе Vosk."),
                    Triple(AsrEngineType.SHERPA.storageValue, "Sherpa", "Локальный Sherpa-ONNX для сравнительных тестов.")
                )
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    engineOptions.forEach { (value, label, desc) ->
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            FilterChip(
                                selected = state.asrEngine == value,
                                enabled = !state.isListening && !state.isRecognizing,
                                onClick = { onAsrEngineChange(value) },
                                label = { Text(label) }
                            )
                            Text(
                                text = desc,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(start = 4.dp)
                            )
                        }
                    }
                }
            }

            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Parser mode", style = MaterialTheme.typography.titleMedium)
                val parserOptions = listOf(
                    Triple("rules", "Правила", "Детерминированный парсер, максимальная стабильность."),
                    Triple("llm_safe", "LLM + правила", "Сначала быстрые правила, затем LLM только для сложных формулировок."),
                    Triple("llm", "Только LLM", "Экспериментальный режим без подстраховки.")
                )
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    parserOptions.forEach { (value, label, desc) ->
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            FilterChip(
                                selected = state.parserMode == value,
                                onClick = { onParserChange(value) },
                                label = { Text(label) }
                            )
                            Text(
                                text = desc,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(start = 4.dp)
                            )
                        }
                    }
                }
            }

            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("TTS", style = MaterialTheme.typography.titleMedium)
                SpeechSlider(
                    label = "Скорость речи: ${"%.2f".format(state.speechRate)}x",
                    value = state.speechRate,
                    onChange = onSpeechRateChange
                )
                SpeechSlider(
                    label = "Тон голоса: ${"%.2f".format(state.speechPitch)}x",
                    value = state.speechPitch,
                    onChange = onSpeechPitchChange
                )
            }
        }

        DeveloperSectionCard(
            title = "Диагностика и журнал",
            subtitle = diagnosticsSubtitle,
            expanded = diagnosticsExpanded,
            onToggle = { diagnosticsExpanded = !diagnosticsExpanded }
        ) {
            OutlinedButton(
                onClick = { showDiagnostics = true },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Открыть диагностику")
            }
            ElevatedCard {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text("Последняя зона", style = MaterialTheme.typography.titleMedium)
                    Text(
                        if (state.lastAreaName.isBlank()) "Нет данных" else state.lastAreaName,
                        style = MaterialTheme.typography.bodyLarge
                    )
                    Text(
                        text = "Голосовой движок: $engineLabel · ${if (state.asrReady) "готов" else "подготовка..."}",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
        if (showDiagnostics) {
            DiagnosticsDialog(
                state = state,
                onDismiss = { showDiagnostics = false },
                onRefresh = onRefreshDiagnostics,
                onRerunLastClip = onRerunLastClip
            )
        }
    }
}

@Composable
private fun NotificationsScreen(
    state: UiState,
    onClear: () -> Unit,
    onRefreshDiagnostics: () -> Unit
) {
    val logs = state.logs
    var filter by rememberSaveable { mutableStateOf(LogFilter.ALL) }
    val filteredLogs = remember(logs, filter) {
        when (filter) {
            LogFilter.ALL -> logs
            LogFilter.ACTIONS -> logs.filter { it.kind == LogKind.ACTION }
            LogFilter.ERRORS -> logs.filter { it.kind == LogKind.ERROR }
        }
    }
    val displayLogs = remember(filteredLogs) { filteredLogs.asReversed() }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("Журнал действий", style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = onClear, enabled = logs.isNotEmpty()) {
                Text("Очистить")
            }
        }
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(vertical = 12.dp)
        ) {
            LogFilter.entries.forEach { item ->
                FilterChip(
                    selected = filter == item,
                    onClick = { filter = item },
                    label = { Text(item.label) }
                )
            }
        }

        if (displayLogs.isEmpty()) {
            Spacer(modifier = Modifier.height(32.dp))
            Text(
                "Пока нет событий по выбранному фильтру.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(displayLogs) { entry ->
                    LogEntryCard(entry)
                }
            }
        }
    }
}

@Composable
private fun LogEntryCard(entry: LogEntry) {
    val formatter = remember {
        SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    }
    val time = remember(entry.timestamp) { formatter.format(Date(entry.timestamp)) }
    val icon = when (entry.kind) {
        LogKind.ERROR -> Icons.Outlined.Warning
        LogKind.ACTION -> Icons.Outlined.PlayArrow
        LogKind.INFO -> Icons.Outlined.Info
    }
    val tint = when (entry.kind) {
        LogKind.ERROR -> MaterialTheme.colorScheme.error
        LogKind.ACTION -> MaterialTheme.colorScheme.primary
        LogKind.INFO -> MaterialTheme.colorScheme.secondary
    }

    ElevatedCard {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = icon,
                contentDescription = entry.kind.name,
                tint = tint,
                modifier = Modifier.size(24.dp)
            )
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    text = time,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(entry.message, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
private fun DiagnosticBlock(
    title: String,
    value: String
) {
    val clipboard = LocalClipboardManager.current
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(title, style = MaterialTheme.typography.labelMedium)
            TextButton(onClick = {
                clipboard.setText(AnnotatedString(value))
            }, enabled = value.isNotBlank()) {
                Text("Копировать")
            }
        }
        SelectionContainer {
            Text(
                text = if (value.isBlank()) "Нет данных..." else value,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun DiagnosticsDialog(
    state: UiState,
    onDismiss: () -> Unit,
    onRefresh: () -> Unit,
    onRerunLastClip: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = { onRefresh(); onDismiss() }) { Text("Обновить") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Закрыть") }
        },
        title = { Text("Диагностика") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    text = "Файл логов: ${state.logFilePath}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                OutlinedButton(
                    onClick = onRerunLastClip,
                    enabled = state.lastClipWavPath.isNotBlank() && !state.isRecognizing,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Повторно прогнать последний клип")
                }
                DiagnosticBlock("Last clip WAV", state.lastClipWavPath)
                DiagnosticBlock("Last clip metadata", state.lastClipMetadataPath)
                DiagnosticBlock("Eval history JSONL", state.evalHistoryJsonlPath)
                DiagnosticBlock("Eval history CSV", state.evalHistoryCsvPath)
                DiagnosticBlock("Eval history count", state.evalHistoryCount.toString())
                DiagnosticBlock("Press to speech start", "${state.speechStartOffsetMs} ms")
                DiagnosticBlock("Release to result", "${state.releaseToResultMs} ms")
                DiagnosticBlock("Empty ASR result", state.lastAsrEmpty.toString())
                if (state.lastComparisonEngine.isNotBlank()) {
                    DiagnosticBlock(
                        "ASR compare ${state.lastComparisonEngine} (${state.lastComparisonMs} ms)",
                        if (state.lastComparisonText.isBlank()) "<empty>" else state.lastComparisonText
                    )
                }
                if (state.lastParserModeUsed.isNotBlank()) {
                    DiagnosticBlock("Parser mode used", state.lastParserModeUsed)
                }
                if (state.lastParsedStageSummary.isNotBlank()) {
                    DiagnosticBlock("Parsed stage", state.lastParsedStageSummary)
                }
                if (state.lastValidatedStageSummary.isNotBlank()) {
                    DiagnosticBlock("Validated stage", state.lastValidatedStageSummary)
                }
                if (state.lastExecutionStageSummary.isNotBlank()) {
                    DiagnosticBlock("Execution stage", state.lastExecutionStageSummary)
                }
                if (state.parseStageMs > 0L || state.validateStageMs > 0L || state.executeStageMs > 0L) {
                    DiagnosticBlock(
                        "Pipeline timing",
                        buildString {
                            append("parse=${state.parseStageMs} ms\n")
                            append("validate=${state.validateStageMs} ms\n")
                            append("execute=${state.executeStageMs} ms")
                            if (state.llmStageMs > 0L || state.llmPromptTokens > 0 || state.llmCompletionTokens > 0) {
                                append("\nllm=${state.llmStageMs} ms")
                                append("\nprompt_tokens=${state.llmPromptTokens}")
                                append("\ncompletion_tokens=${state.llmCompletionTokens}")
                                append("\ntotal_tokens=${state.llmTotalTokens}")
                                if (state.llmModel.isNotBlank()) {
                                    append("\nmodel=${state.llmModel}")
                                }
                            }
                        }
                    )
                }
                DiagnosticBlock("Последние записи", state.logPreview)
                DiagnosticBlock("RAW запрос", state.lastGatewayRequestRaw)
                DiagnosticBlock("RAW ответ", state.lastGatewayResponseRaw)
                if (state.scenarioPreviewRequestRaw.isNotBlank()) {
                    DiagnosticBlock("Scenario preview request", state.scenarioPreviewRequestRaw)
                }
                if (state.scenarioPreviewResponseRaw.isNotBlank()) {
                    DiagnosticBlock("Scenario preview response", state.scenarioPreviewResponseRaw)
                }
                if (state.scenarioSaveRequestRaw.isNotBlank()) {
                    DiagnosticBlock("Scenario save request", state.scenarioSaveRequestRaw)
                }
                if (state.scenarioSaveResponseRaw.isNotBlank()) {
                    DiagnosticBlock("Scenario save response", state.scenarioSaveResponseRaw)
                }
            }
        }
    )
}

@Composable
private fun SpeechSlider(
    label: String,
    value: Float,
    onChange: (Float) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Slider(
            value = value,
            onValueChange = onChange,
            valueRange = 0.5f..1.5f,
            steps = 5,
            colors = SliderDefaults.colors(
                thumbColor = MaterialTheme.colorScheme.primary,
                activeTrackColor = MaterialTheme.colorScheme.primary
            )
        )
    }
}

