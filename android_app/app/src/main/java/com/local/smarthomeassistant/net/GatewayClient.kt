package com.local.smarthomeassistant.net

import android.util.Log
import androidx.annotation.VisibleForTesting
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class GatewayClient {

    private val client = OkHttpClient.Builder()
        .callTimeout(45, TimeUnit.SECONDS)
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .build()

    fun ping(baseUrl: String, apiKey: String?, liveMode: Boolean): GatewayPingResult {
        val normalizedBaseUrl = normalizeBaseUrl(baseUrl)
        val readinessUrl = normalizedBaseUrl + "/v1/readiness"
        val healthUrl = normalizedBaseUrl + "/health"
        val safeKey = normalizeApiKey(apiKey.orEmpty())
        val t0 = System.currentTimeMillis()

        return try {
            client.newCall(buildGetRequest(readinessUrl, safeKey)).execute().use { resp ->
                val latency = System.currentTimeMillis() - t0
                val body = resp.body?.string().orEmpty()

                if (resp.code == 404) {
                    return fallbackHealthPing(healthUrl, safeKey, t0)
                }
                if (resp.isSuccessful) {
                    parseGatewayReadiness(body, latency, liveMode)
                } else {
                    val detail = extractJsonDetail(body)
                    val msg = if (detail.isNotBlank()) detail else "HTTP ${resp.code}"
                    GatewayPingResult(
                        ok = false,
                        message = msg,
                        latencyMs = latency,
                        gatewayReachable = false
                    )
                }
            }
        } catch (e: IOException) {
            GatewayPingResult(ok = false, message = "Network error: ${e.message}", latencyMs = null)
        } catch (e: Exception) {
            GatewayPingResult(ok = false, message = "Unknown error: ${e.message}", latencyMs = null)
        }
    }

    fun fetchCatalog(baseUrl: String, apiKey: String?): GatewayCatalogResult {
        val url = normalizeBaseUrl(baseUrl) + "/v1/catalog"
        val safeKey = normalizeApiKey(apiKey.orEmpty())

        val builder = Request.Builder()
            .url(url)
            .get()
            .header("Accept", "application/json")

        if (safeKey.isNotEmpty()) {
            builder.header("X-API-Key", safeKey)
        }

        return try {
            client.newCall(builder.build()).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    val detail = extractJsonDetail(body)
                    val message = if (detail.isNotBlank()) detail else "HTTP ${resp.code}"
                    GatewayCatalogResult.Error(code = resp.code, message = message)
                } else {
                    GatewayCatalogResult.Ok(parseDeviceCatalog(body))
                }
            }
        } catch (e: IOException) {
            GatewayCatalogResult.Error(code = null, message = "Network error: ${e.message}")
        } catch (e: Exception) {
            GatewayCatalogResult.Error(code = null, message = "Parse/unknown error: ${e.message}")
        }
    }

    fun sendCommand(
        baseUrl: String,
        apiKey: String,
        text: String,
        parserMode: String,
        dryRun: Boolean,
        selectedAreaName: String?,
        lastAreaName: String?,
        lastEntityIds: List<String>,
        lastColorName: String?,
        lastBrightness: Int?,
        lastColorTempKelvin: Int?,
        pendingClarificationSlot: String?
    ): GatewayCallResult {
        val url = normalizeBaseUrl(baseUrl) + "/v1/command"
        val safeKey = normalizeApiKey(apiKey)

        val dotCount = safeKey.count { it == '.' }
        Log.i(
            "GatewayClient",
            "sendCommand: url=$url key.safeLen=${safeKey.length} key.dotCount=$dotCount key.sha6=${sha256Prefix6(safeKey)}"
        )

        val bodyJson = JSONObject().apply {
            put("text", text)
            put("parser_mode", parserMode)
            put("dry_run", dryRun)
            val contextJson = JSONObject().apply {
                if (!selectedAreaName.isNullOrBlank()) put("selected_area_name", selectedAreaName)
                if (!lastAreaName.isNullOrBlank()) put("last_area_name", lastAreaName)
                if (lastEntityIds.isNotEmpty()) {
                    put("last_entity_ids", JSONArray().apply { lastEntityIds.forEach { put(it) } })
                }
                if (!lastColorName.isNullOrBlank()) put("last_color_name", lastColorName)
                if (lastBrightness != null) put("last_brightness", lastBrightness)
                if (lastColorTempKelvin != null) put("last_color_temp_kelvin", lastColorTempKelvin)
                if (!pendingClarificationSlot.isNullOrBlank()) {
                    put("pending_clarification_slot", pendingClarificationSlot)
                }
            }
            if (contextJson.length() > 0) {
                put("context", contextJson)
            }
        }

        val mediaType = "application/json; charset=utf-8".toMediaType()
        val bodyText = bodyJson.toString()
        val body = bodyText.toRequestBody(mediaType)

        val builder = Request.Builder()
            .url(url)
            .post(body)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")

        val headerAdded = safeKey.isNotEmpty()
        if (headerAdded) {
            builder.header("X-API-Key", safeKey)
        }

        Log.i("GatewayClient", "request: header.X-API-Key.added=$headerAdded body.len=${bodyJson.toString().length}")

        val req = builder.build()

        return try {
            client.newCall(req).execute().use { resp ->
                val code = resp.code
                val respBody = resp.body?.string().orEmpty()

                Log.i("GatewayClient", "response: code=$code body.len=${respBody.length}")

                if (!resp.isSuccessful) {
                    val detail = extractJsonDetail(respBody)
                    val msg = when (code) {
                        401 -> "HTTP 401: Invalid or missing X-API-Key"
                        403 -> "HTTP 403: Forbidden"
                        400 -> "HTTP 400: Bad Request"
                        else -> "HTTP $code"
                    }

                    val msgWithDetail = if (detail.isNotBlank()) "$msg. detail=$detail" else msg
                    val bodyPreview = respBody.take(300).replace("\n", " ").replace("\r", " ")
                    val finalMsg = if (bodyPreview.isNotBlank() && detail.isBlank()) {
                        "$msgWithDetail. body=$bodyPreview"
                    } else {
                        msgWithDetail
                    }

                    val error = GatewayResult.Error(code = code, message = finalMsg)
                    return GatewayCallResult(error, bodyText, respBody)
                }

                val ok = parseOk(respBody)
                GatewayCallResult(ok, bodyText, respBody)
            }
        } catch (e: IOException) {
            GatewayCallResult(
                GatewayResult.Error(code = null, message = "Network error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        } catch (e: Exception) {
            GatewayCallResult(
                GatewayResult.Error(code = null, message = "Parse/unknown error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        }
    }

    fun sendQuickAction(
        baseUrl: String,
        apiKey: String,
        actionId: String,
        dryRun: Boolean,
        areaName: String?,
        deviceType: String,
        deviceId: String?
    ): GatewayCallResult {
        val url = normalizeBaseUrl(baseUrl) + "/v1/quick-action"
        val safeKey = normalizeApiKey(apiKey)

        val bodyJson = JSONObject().apply {
            put("action_id", actionId)
            put("dry_run", dryRun)
            put(
                "target",
                JSONObject().apply {
                    put("device_type", deviceType)
                    if (!areaName.isNullOrBlank()) put("area_name", areaName)
                    if (!deviceId.isNullOrBlank()) put("device_id", deviceId)
                }
            )
        }

        val mediaType = "application/json; charset=utf-8".toMediaType()
        val bodyText = bodyJson.toString()
        val body = bodyText.toRequestBody(mediaType)

        val builder = Request.Builder()
            .url(url)
            .post(body)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")

        if (safeKey.isNotEmpty()) {
            builder.header("X-API-Key", safeKey)
        }

        return try {
            client.newCall(builder.build()).execute().use { resp ->
                val code = resp.code
                val respBody = resp.body?.string().orEmpty()

                if (!resp.isSuccessful) {
                    val detail = extractJsonDetail(respBody)
                    val message = if (detail.isNotBlank()) "HTTP $code. detail=$detail" else "HTTP $code"
                    GatewayCallResult(
                        GatewayResult.Error(code = code, message = message),
                        bodyText,
                        respBody
                    )
                } else {
                    GatewayCallResult(parseOk(respBody), bodyText, respBody)
                }
            }
        } catch (e: IOException) {
            GatewayCallResult(
                GatewayResult.Error(code = null, message = "Network error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        } catch (e: Exception) {
            GatewayCallResult(
                GatewayResult.Error(code = null, message = "Parse/unknown error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        }
    }

    fun previewScenario(
        baseUrl: String,
        apiKey: String,
        text: String,
        selectedAreaName: String?,
        lastAreaName: String?,
        lastEntityIds: List<String>
    ): GatewayScenarioPreviewCallResult {
        val url = normalizeBaseUrl(baseUrl) + "/v1/scenario/preview"
        val safeKey = normalizeApiKey(apiKey)

        val bodyJson = JSONObject().apply {
            put("text", text)
            val contextJson = JSONObject().apply {
                if (!selectedAreaName.isNullOrBlank()) put("selected_area_name", selectedAreaName)
                if (!lastAreaName.isNullOrBlank()) put("last_area_name", lastAreaName)
                if (lastEntityIds.isNotEmpty()) {
                    put("last_entity_ids", JSONArray().apply { lastEntityIds.forEach { put(it) } })
                }
            }
            if (contextJson.length() > 0) {
                put("context", contextJson)
            }
        }

        val mediaType = "application/json; charset=utf-8".toMediaType()
        val bodyText = bodyJson.toString()
        val body = bodyText.toRequestBody(mediaType)

        val builder = Request.Builder()
            .url(url)
            .post(body)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")

        if (safeKey.isNotEmpty()) {
            builder.header("X-API-Key", safeKey)
        }

        return try {
            client.newCall(builder.build()).execute().use { resp ->
                val code = resp.code
                val respBody = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    val detail = extractJsonDetail(respBody)
                    val message = if (detail.isNotBlank()) "HTTP $code. detail=$detail" else "HTTP $code"
                    GatewayScenarioPreviewCallResult(
                        GatewayScenarioPreviewResult.Error(code = code, message = message),
                        bodyText,
                        respBody
                    )
                } else {
                    GatewayScenarioPreviewCallResult(parseScenarioPreviewOk(respBody), bodyText, respBody)
                }
            }
        } catch (e: IOException) {
            GatewayScenarioPreviewCallResult(
                GatewayScenarioPreviewResult.Error(code = null, message = "Network error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        } catch (e: Exception) {
            GatewayScenarioPreviewCallResult(
                GatewayScenarioPreviewResult.Error(code = null, message = "Parse/unknown error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        }
    }

    fun saveScenario(
        baseUrl: String,
        apiKey: String,
        validatedBundleJson: String?,
        automationsJson: String
    ): GatewayScenarioSaveCallResult {
        val url = normalizeBaseUrl(baseUrl) + "/v1/scenario/save"
        val safeKey = normalizeApiKey(apiKey)

        val bodyJson = JSONObject().apply {
            put("auto_activate", true)
            if (!validatedBundleJson.isNullOrBlank()) {
                put("validated_bundle", JSONObject(validatedBundleJson))
            }
            put("automations", JSONArray(automationsJson))
        }

        val mediaType = "application/json; charset=utf-8".toMediaType()
        val bodyText = bodyJson.toString()
        val body = bodyText.toRequestBody(mediaType)

        val builder = Request.Builder()
            .url(url)
            .post(body)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")

        if (safeKey.isNotEmpty()) {
            builder.header("X-API-Key", safeKey)
        }

        return try {
            client.newCall(builder.build()).execute().use { resp ->
                val code = resp.code
                val respBody = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    val detail = extractJsonDetail(respBody)
                    val message = if (detail.isNotBlank()) "HTTP $code. detail=$detail" else "HTTP $code"
                    GatewayScenarioSaveCallResult(
                        GatewayScenarioSaveResult.Error(code = code, message = message),
                        bodyText,
                        respBody
                    )
                } else {
                    GatewayScenarioSaveCallResult(parseScenarioSaveOk(respBody), bodyText, respBody)
                }
            }
        } catch (e: IOException) {
            GatewayScenarioSaveCallResult(
                GatewayScenarioSaveResult.Error(code = null, message = "Network error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        } catch (e: Exception) {
            GatewayScenarioSaveCallResult(
                GatewayScenarioSaveResult.Error(code = null, message = "Parse/unknown error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        }
    }

    fun upsertScenario(
        baseUrl: String,
        apiKey: String,
        automationJson: String
    ): GatewayScenarioSaveCallResult {
        val url = normalizeBaseUrl(baseUrl) + "/v1/scenario/upsert"
        val safeKey = normalizeApiKey(apiKey)

        val bodyJson = JSONObject().apply {
            put("auto_activate", true)
            put("automation", JSONObject(automationJson))
        }

        val mediaType = "application/json; charset=utf-8".toMediaType()
        val bodyText = bodyJson.toString()
        val body = bodyText.toRequestBody(mediaType)

        val builder = Request.Builder()
            .url(url)
            .post(body)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")

        if (safeKey.isNotEmpty()) {
            builder.header("X-API-Key", safeKey)
        }

        return try {
            client.newCall(builder.build()).execute().use { resp ->
                val code = resp.code
                val respBody = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    val detail = extractJsonDetail(respBody)
                    val message = if (detail.isNotBlank()) "HTTP $code. detail=$detail" else "HTTP $code"
                    GatewayScenarioSaveCallResult(
                        GatewayScenarioSaveResult.Error(code = code, message = message),
                        bodyText,
                        respBody
                    )
                } else {
                    GatewayScenarioSaveCallResult(parseScenarioSaveOk(respBody), bodyText, respBody)
                }
            }
        } catch (e: IOException) {
            GatewayScenarioSaveCallResult(
                GatewayScenarioSaveResult.Error(code = null, message = "Network error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        } catch (e: Exception) {
            GatewayScenarioSaveCallResult(
                GatewayScenarioSaveResult.Error(code = null, message = "Parse/unknown error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        }
    }

    fun listScenarios(
        baseUrl: String,
        apiKey: String
    ): GatewayScenarioListCallResult {
        val url = normalizeBaseUrl(baseUrl) + "/v1/scenario/list"
        val safeKey = normalizeApiKey(apiKey)
        val rawRequest = "GET $url"

        val builder = Request.Builder()
            .url(url)
            .get()
            .header("Accept", "application/json")

        if (safeKey.isNotEmpty()) {
            builder.header("X-API-Key", safeKey)
        }

        return try {
            client.newCall(builder.build()).execute().use { resp ->
                val code = resp.code
                val respBody = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    val detail = extractJsonDetail(respBody)
                    val message = if (detail.isNotBlank()) "HTTP $code. detail=$detail" else "HTTP $code"
                    GatewayScenarioListCallResult(
                        GatewayScenarioListResult.Error(code = code, message = message),
                        rawRequest,
                        respBody
                    )
                } else {
                    GatewayScenarioListCallResult(parseScenarioListOk(respBody), rawRequest, respBody)
                }
            }
        } catch (e: IOException) {
            GatewayScenarioListCallResult(
                GatewayScenarioListResult.Error(code = null, message = "Network error: ${e.message}"),
                rawRequest,
                e.message.orEmpty()
            )
        } catch (e: Exception) {
            GatewayScenarioListCallResult(
                GatewayScenarioListResult.Error(code = null, message = "Parse/unknown error: ${e.message}"),
                rawRequest,
                e.message.orEmpty()
            )
        }
    }

    fun deleteScenario(
        baseUrl: String,
        apiKey: String,
        automationId: String
    ): GatewayScenarioDeleteCallResult {
        val url = normalizeBaseUrl(baseUrl) + "/v1/scenario/delete"
        val safeKey = normalizeApiKey(apiKey)

        val bodyJson = JSONObject().apply {
            put("automation_id", automationId)
            put("auto_activate", true)
        }

        val mediaType = "application/json; charset=utf-8".toMediaType()
        val bodyText = bodyJson.toString()
        val body = bodyText.toRequestBody(mediaType)

        val builder = Request.Builder()
            .url(url)
            .post(body)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")

        if (safeKey.isNotEmpty()) {
            builder.header("X-API-Key", safeKey)
        }

        return try {
            client.newCall(builder.build()).execute().use { resp ->
                val code = resp.code
                val respBody = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    val detail = extractJsonDetail(respBody)
                    val message = if (detail.isNotBlank()) "HTTP $code. detail=$detail" else "HTTP $code"
                    GatewayScenarioDeleteCallResult(
                        GatewayScenarioDeleteResult.Error(code = code, message = message),
                        bodyText,
                        respBody
                    )
                } else {
                    GatewayScenarioDeleteCallResult(parseScenarioDeleteOk(respBody), bodyText, respBody)
                }
            }
        } catch (e: IOException) {
            GatewayScenarioDeleteCallResult(
                GatewayScenarioDeleteResult.Error(code = null, message = "Network error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        } catch (e: Exception) {
            GatewayScenarioDeleteCallResult(
                GatewayScenarioDeleteResult.Error(code = null, message = "Parse/unknown error: ${e.message}"),
                bodyText,
                e.message.orEmpty()
            )
        }
    }

    private fun parseOk(jsonText: String): GatewayResult.Ok = parseGatewayOk(jsonText)

    private fun buildGetRequest(url: String, apiKey: String): Request {
        val builder = Request.Builder()
            .url(url)
            .get()
            .header("Accept", "application/json")

        if (apiKey.isNotEmpty()) {
            builder.header("X-API-Key", apiKey)
        }
        return builder.build()
    }

    private fun fallbackHealthPing(url: String, apiKey: String, startedAtMs: Long): GatewayPingResult {
        client.newCall(buildGetRequest(url, apiKey)).execute().use { resp ->
            val latency = System.currentTimeMillis() - startedAtMs
            val body = resp.body?.string().orEmpty()
            return if (resp.isSuccessful) {
                GatewayPingResult(
                    ok = true,
                    message = "Gateway available (${resp.code})",
                    latencyMs = latency,
                    gatewayReachable = true
                )
            } else {
                val detail = extractJsonDetail(body)
                val msg = if (detail.isNotBlank()) detail else "HTTP ${resp.code}"
                GatewayPingResult(
                    ok = false,
                    message = msg,
                    latencyMs = latency,
                    gatewayReachable = false
                )
            }
        }
    }

    private fun sha256Prefix6(s: String): String {
        if (s.isBlank()) return ""
        val md = MessageDigest.getInstance("SHA-256")
        val dig = md.digest(s.toByteArray(Charsets.UTF_8))
        return dig.take(6).joinToString("") { "%02x".format(it) }
    }
}

internal fun normalizeBaseUrl(baseUrl: String): String {
    val trimmed = baseUrl.trim().removeSuffix("/")
    return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed else "http://$trimmed"
}

internal fun extractJsonDetail(body: String): String {
    if (body.isBlank()) return ""
    return try {
        JSONObject(body).optString("detail", "")
    } catch (_: Exception) {
        ""
    }
}

@VisibleForTesting
internal fun parseGatewayReadiness(
    jsonText: String,
    latencyMs: Long,
    liveMode: Boolean
): GatewayPingResult {
    val root = JSONObject(jsonText)
    val gatewayObj = root.optJSONObject("gateway")
    val haObj = root.optJSONObject("home_assistant")
    val llmObj = root.optJSONObject("llm")

    val gatewayOk = gatewayObj?.optBoolean("ok", root.optBoolean("ok", false)) == true
    val readyForLive = root.optBoolean("ready_for_live_commands", false)
    val haConfigured = haObj?.optBoolean("configured", false) == true
    val haOk = haObj?.optBoolean("ok", false) == true
    val llmConfigured = llmObj?.optBoolean("configured", false) == true
    val llmOk = llmObj?.optBoolean("ok", false) == true

    val detailLines = buildList {
        val gatewayDetail = gatewayObj?.optString("detail", "").orEmpty().ifBlank {
            if (gatewayOk) "reachable" else "unavailable"
        }
        val haDetail = haObj?.optString("detail", "").orEmpty().ifBlank {
            when {
                haOk -> "reachable"
                !haConfigured -> "not configured"
                else -> "unavailable"
            }
        }
        val llmDetail = llmObj?.optString("detail", "").orEmpty().ifBlank {
            when {
                llmOk -> "configured"
                !llmConfigured -> "not configured"
                else -> "unavailable"
            }
        }
        add("Gateway: $gatewayDetail")
        add("Home Assistant: $haDetail")
        add("LLM: $llmDetail")
    }

    val ok = gatewayOk && (!liveMode || readyForLive)
    val message = when {
        !gatewayOk -> "Gateway unavailable"
        liveMode && !readyForLive -> "Gateway available, Home Assistant is not ready"
        liveMode -> "Ready for live commands"
        else -> "Gateway available"
    }

    return GatewayPingResult(
        ok = ok,
        message = message,
        latencyMs = latencyMs,
        gatewayReachable = gatewayOk,
        detailLines = detailLines
    )
}

@VisibleForTesting
internal fun normalizeApiKey(raw: String): String {
    val trimmed = raw.trim()
    val withoutPrefix = if (trimmed.contains(":") &&
        trimmed.substringBefore(":").contains("X-API-Key", ignoreCase = true)
    ) {
        trimmed.substringAfter(":").trim()
    } else {
        trimmed
    }

    val noWs = withoutPrefix.replace(Regex("\\s+"), "")

    return noWs.filter { ch ->
        ch.isLetterOrDigit() || ch == '.' || ch == '-' || ch == '_'
    }
}

@VisibleForTesting
internal fun parseGatewayOk(jsonText: String): GatewayResult.Ok {
    val root = JSONObject(jsonText)

    val status = root.optString("status", "EXECUTED")
    val say = root.optString("say_text", "")
    val parserModeUsed = root.optString("parser_mode_used", "rules")

    val clarObj = root.optJSONObject("clarification")
    val clarification = if (clarObj != null && clarObj.optBoolean("needed", false)) {
        val question = clarObj.optString("question", "")
        val optionsJson = clarObj.optJSONArray("options") ?: JSONArray()
        val options = buildList {
            for (i in 0 until optionsJson.length()) add(optionsJson.optString(i))
        }
        Clarification(needed = true, question = question, options = options)
    } else null

    var lastArea: String? = null
    var lastEntityIds: List<String> = emptyList()
    var lastColorName: String? = null
    var lastBrightness: Int? = null
    var lastColorTempKelvin: Int? = null
    var explicitColor = false
    var explicitColorTemp = false
    val parsedCommand = root.optJSONObject("parsed_command")
    val validated = root.optJSONObject("validated_command")
    val normalized = validated?.optJSONObject("normalized")
    val ctxUpdates = normalized?.optJSONObject("context_updates")
    if (ctxUpdates != null) {
        lastArea = ctxUpdates.optString("last_area_name", "").ifBlank { null }
        lastEntityIds = jsonArrayToStringList(ctxUpdates.optJSONArray("last_entity_ids"))
    }

    val firstParsedAction = parsedCommand
        ?.optJSONArray("actions")
        ?.optJSONObject(0)
    val firstParsedTarget = firstParsedAction?.optJSONObject("target")
    if (lastArea.isNullOrBlank()) {
        lastArea = firstParsedTarget?.optString("area_name", "")?.ifBlank { null }
    }
    if (lastEntityIds.isEmpty()) {
        lastEntityIds = jsonArrayToStringList(firstParsedTarget?.optJSONArray("entity_ids"))
    }

    val params = firstParsedAction?.optJSONObject("params")
    val colorObj = params?.optJSONObject("color")
    if (colorObj != null && !colorObj.isNull("rgb")) {
        explicitColor = true
        lastColorName = colorObj.optString("name", "").ifBlank { null }
    }
    if (params != null && params.has("brightness") && !params.isNull("brightness")) {
        lastBrightness = params.optInt("brightness")
    }
    if (params != null && params.has("color_temp_kelvin") && !params.isNull("color_temp_kelvin")) {
        explicitColorTemp = true
        lastColorTempKelvin = params.optInt("color_temp_kelvin")
    }

    val timingObj = root.optJSONObject("timing_ms")
    val llmObj = timingObj?.optJSONObject("llm")

    return GatewayResult.Ok(
        status = status,
        sayText = say,
        clarification = clarification,
        contextUpdatesLastAreaName = lastArea,
        contextSnapshot = ConversationContextSnapshot(
            lastAreaName = lastArea,
            lastEntityIds = lastEntityIds,
            lastColorName = lastColorName,
            lastBrightness = lastBrightness,
            lastColorTempKelvin = lastColorTempKelvin,
            explicitColor = explicitColor,
            explicitColorTemp = explicitColorTemp
        ),
        parserModeUsed = parserModeUsed,
        parsedStage = parseParsedStageSummary(parsedCommand),
        validatedStage = parseValidatedStageSummary(validated),
        executionStage = parseExecutionStageSummary(root),
        timing = GatewayTimingSummary(
            parseMs = timingObj?.optLong("parse", 0L) ?: 0L,
            validateMs = timingObj?.optLong("validate", 0L) ?: 0L,
            executeMs = timingObj?.optLong("execute", 0L) ?: 0L,
            llm = llmObj?.let {
                GatewayLlmTimingSummary(
                    durationMs = it.optLong("duration_ms", 0L),
                    promptTokens = it.optInt("prompt_tokens", 0),
                    completionTokens = it.optInt("completion_tokens", 0),
                    totalTokens = it.optInt("total_tokens", 0),
                    model = it.optString("model", "").ifBlank { null }
                )
            }
        )
    )
}

@VisibleForTesting
internal fun parseDeviceCatalog(jsonText: String): DeviceCatalog {
    val root = JSONObject(jsonText)
    val areasJson = root.optJSONArray("areas") ?: JSONArray()
    val devicesJson = root.optJSONArray("devices") ?: JSONArray()

    val areas = buildList {
        for (i in 0 until areasJson.length()) {
            val obj = areasJson.optJSONObject(i) ?: continue
            add(
                DeviceCatalogArea(
                    areaId = obj.optString("area_id", ""),
                    name = obj.optString("name", ""),
                    deviceTypes = jsonArrayToStringList(obj.optJSONArray("device_types")),
                    deviceIds = jsonArrayToStringList(obj.optJSONArray("device_ids")),
                    targetProfiles = buildList {
                        val profilesJson = obj.optJSONArray("target_profiles") ?: JSONArray()
                        for (j in 0 until profilesJson.length()) {
                            val profileObj = profilesJson.optJSONObject(j) ?: continue
                            add(
                                DeviceCatalogTargetProfile(
                                    deviceType = profileObj.optString("device_type", ""),
                                    profileId = profileObj.optString("profile_id", ""),
                                    label = profileObj.optString("label", ""),
                                    supportedQuickActions = jsonArrayToStringList(profileObj.optJSONArray("supported_quick_actions")),
                                    deviceIds = jsonArrayToStringList(profileObj.optJSONArray("device_ids"))
                                )
                            )
                        }
                    }
                )
            )
        }
    }

    val devices = buildList {
        for (i in 0 until devicesJson.length()) {
            val obj = devicesJson.optJSONObject(i) ?: continue
            val caps = obj.optJSONObject("capabilities")
            add(
                DeviceCatalogDevice(
                    deviceId = obj.optString("device_id", ""),
                    name = obj.optString("name", ""),
                    deviceType = obj.optString("device_type", ""),
                    areaId = obj.optString("area_id", "").ifBlank { null },
                    areaName = obj.optString("area_name", "").ifBlank { null },
                    entityId = obj.optString("entity_id", "").ifBlank { null },
                    controlProfile = obj.optString("control_profile", "power_only"),
                    supportedQuickActions = jsonArrayToStringList(obj.optJSONArray("supported_quick_actions")),
                    capabilities = DeviceCapabilitySummary(
                        onOff = caps?.optBoolean("on_off", false) == true,
                        brightness = caps?.optBoolean("brightness", false) == true,
                        rgb = caps?.optBoolean("rgb", false) == true,
                        colorTemp = caps?.optBoolean("color_temp", false) == true,
                        transition = caps?.optBoolean("transition", false) == true
                    )
                )
            )
        }
    }

    return DeviceCatalog(
        schemaVersion = root.optString("schema_version", "1.0"),
        areas = areas,
        devices = devices
    )
}

private fun jsonArrayToStringList(arr: JSONArray?): List<String> = buildList {
    if (arr == null) return@buildList
    for (i in 0 until arr.length()) {
        val value = arr.optString(i, "").trim()
        if (value.isNotBlank()) add(value)
    }
}

private fun parseParsedStageSummary(parsed: JSONObject?): ParsedStageSummary? {
    if (parsed == null) return null
    val actions = parsed.optJSONArray("actions")
    val firstAction = actions?.optJSONObject(0)
    val firstTarget = firstAction?.optJSONObject("target")
    return ParsedStageSummary(
        actionCount = actions?.length() ?: 0,
        clarificationNeeded = parsed.optJSONObject("clarification")?.optBoolean("needed", false) == true,
        firstIntent = firstAction?.optString("intent", "")?.ifBlank { null },
        firstTargetScope = firstTarget?.optString("scope", "")?.ifBlank { null },
        firstTargetAreaName = firstTarget?.optString("area_name", "")?.ifBlank { null }
    )
}

private fun parseValidatedStageSummary(validated: JSONObject?): ValidatedStageSummary? {
    if (validated == null) return null
    val warnings = validated.optJSONArray("warnings")
    val normalizedActions = validated.optJSONObject("normalized")?.optJSONArray("actions")
    val firstAction = normalizedActions?.optJSONObject(0)
    val firstTarget = firstAction?.optJSONObject("target")
    return ValidatedStageSummary(
        status = validated.optString("status", "").ifBlank { null },
        reasonCode = validated.optString("reason_code", "").ifBlank { null },
        actionCount = normalizedActions?.length() ?: 0,
        warningCount = warnings?.length() ?: 0,
        firstIntent = firstAction?.optString("intent", "")?.ifBlank { null },
        firstAreaName = firstTarget?.optString("area_name", "")?.ifBlank { null }
    )
}

private fun parseExecutionStageSummary(root: JSONObject): ExecutionStageSummary {
    val calls = root.optJSONArray("calls")
    val errors = root.optJSONArray("errors")
    val firstCall = calls?.optJSONObject(0)
    val firstError = errors?.optJSONObject(0)
    return ExecutionStageSummary(
        callCount = calls?.length() ?: 0,
        errorCount = errors?.length() ?: 0,
        firstService = firstCall?.optString("service", "")?.ifBlank { null },
        firstErrorCode = firstError?.optString("code", "")?.ifBlank { null }
    )
}

@VisibleForTesting
internal fun parseScenarioPreviewOk(jsonText: String): GatewayScenarioPreviewResult.Ok {
    val root = JSONObject(jsonText)
    val status = root.optString("status", "PREVIEW_READY")
    val say = root.optString("say_text", "")

    val clarificationObj = root.optJSONObject("clarification")
    val clarification = if (clarificationObj != null && clarificationObj.optBoolean("needed", false)) {
        ScenarioPreviewClarification(
            needed = true,
            question = clarificationObj.optString("question", ""),
            missingFields = jsonArrayToStringList(clarificationObj.optJSONArray("missing_fields"))
        )
    } else null

    val parsedBundle = root.optJSONObject("parsed_bundle")
    val validatedBundle = root.optJSONObject("validated_bundle")
    val timingObj = root.optJSONObject("timing_ms")
    val llmObj = timingObj?.optJSONObject("llm")
    val automationsArray = root.optJSONArray("automations") ?: JSONArray()

    return GatewayScenarioPreviewResult.Ok(
        status = status,
        sayText = say,
        clarification = clarification,
        parsedSummary = ScenarioPreviewSummary(
            title = parsedBundle?.optString("title", "")?.ifBlank { null },
            ruleCount = parsedBundle?.optJSONArray("rules")?.length() ?: 0,
            clarificationNeeded = clarification != null
        ),
        automationCount = automationsArray.length(),
        timing = ScenarioPreviewTimingSummary(
            parseMs = timingObj?.optLong("parse", 0L) ?: 0L,
            validateMs = timingObj?.optLong("validate", 0L) ?: 0L,
            compileMs = timingObj?.optLong("compile", 0L) ?: 0L,
            llm = llmObj?.let {
                GatewayLlmTimingSummary(
                    durationMs = it.optLong("duration_ms", 0L),
                    promptTokens = it.optInt("prompt_tokens", 0),
                    completionTokens = it.optInt("completion_tokens", 0),
                    totalTokens = it.optInt("total_tokens", 0),
                    model = it.optString("model", "").ifBlank { null }
                )
            }
        ),
        parsedBundleJson = parsedBundle?.toString(2).orEmpty(),
        validatedBundleJson = validatedBundle?.toString(2),
        automationsJson = automationsArray.toString(2)
    )
}

@VisibleForTesting
internal fun parseScenarioSaveOk(jsonText: String): GatewayScenarioSaveResult.Ok {
    val root = JSONObject(jsonText)
    return GatewayScenarioSaveResult.Ok(
        status = root.optString("status", "ERROR"),
        sayText = root.optString("say_text", ""),
        savedAutomationCount = root.optInt("saved_automation_count", 0),
        fileAutomationCount = root.optInt("file_automation_count", 0),
        storageFile = root.optString("storage_file", "").ifBlank { null },
        includeDetected = root.optBoolean("include_detected", false),
        reloaded = root.optBoolean("reloaded", false),
        includeHint = root.optString("include_hint", "").ifBlank { null }
    )
}

@VisibleForTesting
internal fun parseScenarioListOk(jsonText: String): GatewayScenarioListResult.Ok {
    val root = JSONObject(jsonText)
    val itemsJson = root.optJSONArray("items") ?: JSONArray()
    val items = buildList {
        for (i in 0 until itemsJson.length()) {
            val item = itemsJson.optJSONObject(i) ?: continue
            add(
                GatewayScenarioListItem(
                    automationId = item.optString("automation_id", ""),
                    alias = item.optString("alias", ""),
                    triggerSummary = item.optString("trigger_summary", ""),
                    actionSummary = item.optString("action_summary", ""),
                    automationJson = item.optJSONObject("automation")?.toString(2).orEmpty()
                )
            )
        }
    }
    return GatewayScenarioListResult.Ok(
        storageFile = root.optString("storage_file", "").ifBlank { null },
        fileAutomationCount = root.optInt("file_automation_count", 0),
        items = items
    )
}

@VisibleForTesting
internal fun parseScenarioDeleteOk(jsonText: String): GatewayScenarioDeleteResult.Ok {
    val root = JSONObject(jsonText)
    return GatewayScenarioDeleteResult.Ok(
        status = root.optString("status", "ERROR"),
        sayText = root.optString("say_text", ""),
        deletedAutomationId = root.optString("deleted_automation_id", "").ifBlank { null },
        fileAutomationCount = root.optInt("file_automation_count", 0),
        storageFile = root.optString("storage_file", "").ifBlank { null }
    )
}
