package com.local.smarthomeassistant.net

data class DeviceCapabilitySummary(
    val onOff: Boolean,
    val brightness: Boolean,
    val rgb: Boolean,
    val colorTemp: Boolean,
    val transition: Boolean
)

data class DeviceCatalogDevice(
    val deviceId: String,
    val name: String,
    val deviceType: String,
    val areaId: String?,
    val areaName: String?,
    val entityId: String?,
    val controlProfile: String,
    val supportedQuickActions: List<String>,
    val capabilities: DeviceCapabilitySummary
)

data class DeviceCatalogTargetProfile(
    val deviceType: String,
    val profileId: String,
    val label: String,
    val supportedQuickActions: List<String>,
    val deviceIds: List<String>
)

data class DeviceCatalogArea(
    val areaId: String,
    val name: String,
    val deviceTypes: List<String>,
    val deviceIds: List<String>,
    val targetProfiles: List<DeviceCatalogTargetProfile>
)

data class DeviceCatalog(
    val schemaVersion: String,
    val areas: List<DeviceCatalogArea>,
    val devices: List<DeviceCatalogDevice>
)

data class Clarification(
    val needed: Boolean,
    val question: String,
    val options: List<String>
)

data class ParsedStageSummary(
    val actionCount: Int,
    val clarificationNeeded: Boolean,
    val firstIntent: String?,
    val firstTargetScope: String?,
    val firstTargetAreaName: String?
)

data class ValidatedStageSummary(
    val status: String?,
    val reasonCode: String?,
    val actionCount: Int,
    val warningCount: Int,
    val firstIntent: String?,
    val firstAreaName: String?
)

data class ExecutionStageSummary(
    val callCount: Int,
    val errorCount: Int,
    val firstService: String?,
    val firstErrorCode: String?
)

data class GatewayTimingSummary(
    val parseMs: Long,
    val validateMs: Long,
    val executeMs: Long,
    val llm: GatewayLlmTimingSummary? = null
)

data class GatewayLlmTimingSummary(
    val durationMs: Long,
    val promptTokens: Int,
    val completionTokens: Int,
    val totalTokens: Int,
    val model: String?
)

data class ConversationContextSnapshot(
    val lastAreaName: String?,
    val lastEntityIds: List<String>,
    val lastColorName: String?,
    val lastBrightness: Int?,
    val lastColorTempKelvin: Int?,
    val explicitColor: Boolean,
    val explicitColorTemp: Boolean
)

sealed class GatewayResult {
    data class Ok(
        val status: String,
        val sayText: String,
        val clarification: Clarification?,
        val contextUpdatesLastAreaName: String?,
        val contextSnapshot: ConversationContextSnapshot?,
        val parserModeUsed: String,
        val parsedStage: ParsedStageSummary?,
        val validatedStage: ValidatedStageSummary?,
        val executionStage: ExecutionStageSummary,
        val timing: GatewayTimingSummary
    ) : GatewayResult()

    data class Error(
        val code: Int?,
        val message: String
    ) : GatewayResult()
}

data class GatewayPingResult(
    val ok: Boolean,
    val message: String,
    val latencyMs: Long?,
    val gatewayReachable: Boolean = false,
    val detailLines: List<String> = emptyList()
)

sealed class GatewayCatalogResult {
    data class Ok(
        val catalog: DeviceCatalog
    ) : GatewayCatalogResult()

    data class Error(
        val code: Int?,
        val message: String
    ) : GatewayCatalogResult()
}

data class GatewayCallResult(
    val result: GatewayResult,
    val rawRequest: String,
    val rawResponse: String
)

data class ScenarioPreviewClarification(
    val needed: Boolean,
    val question: String,
    val missingFields: List<String>
)

data class ScenarioPreviewTimingSummary(
    val parseMs: Long,
    val validateMs: Long,
    val compileMs: Long,
    val llm: GatewayLlmTimingSummary? = null
)

data class ScenarioPreviewSummary(
    val title: String?,
    val ruleCount: Int,
    val clarificationNeeded: Boolean
)

sealed class GatewayScenarioPreviewResult {
    data class Ok(
        val status: String,
        val sayText: String,
        val clarification: ScenarioPreviewClarification?,
        val parsedSummary: ScenarioPreviewSummary,
        val automationCount: Int,
        val timing: ScenarioPreviewTimingSummary,
        val parsedBundleJson: String,
        val validatedBundleJson: String?,
        val automationsJson: String
    ) : GatewayScenarioPreviewResult()

    data class Error(
        val code: Int?,
        val message: String
    ) : GatewayScenarioPreviewResult()
}

data class GatewayScenarioPreviewCallResult(
    val result: GatewayScenarioPreviewResult,
    val rawRequest: String,
    val rawResponse: String
)

sealed class GatewayScenarioSaveResult {
    data class Ok(
        val status: String,
        val sayText: String,
        val savedAutomationCount: Int,
        val fileAutomationCount: Int,
        val storageFile: String?,
        val includeDetected: Boolean,
        val reloaded: Boolean,
        val includeHint: String?
    ) : GatewayScenarioSaveResult()

    data class Error(
        val code: Int?,
        val message: String
    ) : GatewayScenarioSaveResult()
}

data class GatewayScenarioSaveCallResult(
    val result: GatewayScenarioSaveResult,
    val rawRequest: String,
    val rawResponse: String
)

data class GatewayScenarioListItem(
    val automationId: String,
    val alias: String,
    val triggerSummary: String,
    val actionSummary: String,
    val automationJson: String
)

sealed class GatewayScenarioListResult {
    data class Ok(
        val storageFile: String?,
        val fileAutomationCount: Int,
        val items: List<GatewayScenarioListItem>
    ) : GatewayScenarioListResult()

    data class Error(
        val code: Int?,
        val message: String
    ) : GatewayScenarioListResult()
}

data class GatewayScenarioListCallResult(
    val result: GatewayScenarioListResult,
    val rawRequest: String,
    val rawResponse: String
)

sealed class GatewayScenarioDeleteResult {
    data class Ok(
        val status: String,
        val sayText: String,
        val deletedAutomationId: String?,
        val fileAutomationCount: Int,
        val storageFile: String?
    ) : GatewayScenarioDeleteResult()

    data class Error(
        val code: Int?,
        val message: String
    ) : GatewayScenarioDeleteResult()
}

data class GatewayScenarioDeleteCallResult(
    val result: GatewayScenarioDeleteResult,
    val rawRequest: String,
    val rawResponse: String
)
