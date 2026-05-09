package com.local.smarthomeassistant.net

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GatewayClientUtilsTest {

    @Test
    fun normalizeBaseUrl_addsHttpSchemeWhenMissing() {
        assertEquals("http://example", normalizeBaseUrl("example"))
        assertEquals("https://secure", normalizeBaseUrl("https://secure"))
        assertEquals("http://host", normalizeBaseUrl(" host/"))
    }

    @Test
    fun normalizeApiKey_stripsHeaderAndWhitespace() {
        val raw = "X-API-Key:   abc.def _ghi\n"
        val normalized = normalizeApiKey(raw)
        assertEquals("abc.def_ghi", normalized)
        assertFalse(normalized.contains(" "))
    }

    @Test
    fun parseGatewayOk_extractsClarificationContextAndLlmTiming() {
        val json = JSONObject().apply {
            put("status", "NEEDS_CLARIFICATION")
            put("say_text", "Повторите")
            put("clarification", JSONObject().apply {
                put("needed", true)
                put("question", "Какую комнату?")
                put("options", listOf("кухня", "гостиная"))
            })
            put("validated_command", JSONObject().apply {
                put("normalized", JSONObject().apply {
                    put("context_updates", JSONObject().apply {
                        put("last_area_name", "кухня")
                        put("last_entity_ids", listOf("light.kitchen_strip"))
                    })
                })
            })
            put("parsed_command", JSONObject().apply {
                put("actions", listOf(
                    JSONObject().apply {
                        put("intent", "SET_COLOR")
                        put("target", JSONObject().apply {
                            put("scope", "ENTITY")
                            put("area_name", JSONObject.NULL)
                            put("entity_ids", listOf("light.kitchen_strip"))
                        })
                        put("params", JSONObject().apply {
                            put("brightness", 33)
                            put("brightness_delta", JSONObject.NULL)
                            put("color_temp_kelvin", JSONObject.NULL)
                            put("color_temp_delta_k", JSONObject.NULL)
                            put("transition_s", JSONObject.NULL)
                            put("color", JSONObject().apply {
                                put("mode", "rgb")
                                put("name", "orange")
                                put("rgb", listOf(255, 120, 0))
                            })
                        })
                    }
                ))
            })
            put("timing_ms", JSONObject().apply {
                put("parse", 120)
                put("validate", 0)
                put("execute", 0)
                put("llm", JSONObject().apply {
                    put("duration_ms", 1180)
                    put("prompt_tokens", 321)
                    put("completion_tokens", 27)
                    put("total_tokens", 348)
                    put("model", "qwen-test")
                })
            })
        }.toString()

        val ok = parseGatewayOk(json)
        assertEquals("NEEDS_CLARIFICATION", ok.status)
        assertEquals("Повторите", ok.sayText)
        assertEquals("кухня", ok.contextUpdatesLastAreaName)
        assertTrue(ok.clarification?.options?.contains("кухня") == true)
        assertEquals(listOf("light.kitchen_strip"), ok.contextSnapshot?.lastEntityIds)
        assertEquals(33, ok.contextSnapshot?.lastBrightness)
        assertEquals("orange", ok.contextSnapshot?.lastColorName)
        assertTrue(ok.contextSnapshot?.explicitColor == true)
        assertNotNull(ok.timing.llm)
        assertEquals(1180L, ok.timing.llm?.durationMs)
        assertEquals(321, ok.timing.llm?.promptTokens)
        assertEquals(27, ok.timing.llm?.completionTokens)
        assertEquals(348, ok.timing.llm?.totalTokens)
        assertEquals("qwen-test", ok.timing.llm?.model)
    }

    @Test
    fun parseDeviceCatalog_extractsAreasDevicesProfilesAndCapabilities() {
        val json = JSONObject().apply {
            put("schema_version", "1.0")
            put("areas", listOf(
                JSONObject().apply {
                    put("area_id", "area_bedroom")
                    put("name", "Спальня")
                    put("device_types", listOf("light", "switch"))
                    put("device_ids", listOf("device_light_1", "device_switch_1"))
                    put("target_profiles", listOf(
                        JSONObject().apply {
                            put("device_type", "light")
                            put("profile_id", "color_scene")
                            put("label", "Цвет и сцены")
                            put("supported_quick_actions", listOf("TURN_ON", "TURN_OFF", "COZY"))
                            put("device_ids", listOf("device_light_1"))
                        },
                        JSONObject().apply {
                            put("device_type", "switch")
                            put("profile_id", "power_only")
                            put("label", "Питание")
                            put("supported_quick_actions", listOf("TURN_ON", "TURN_OFF"))
                            put("device_ids", listOf("device_switch_1"))
                        }
                    ))
                }
            ))
            put("devices", listOf(
                JSONObject().apply {
                    put("device_id", "device_light_1")
                    put("name", "Лампа")
                    put("device_type", "light")
                    put("area_id", "area_bedroom")
                    put("area_name", "Спальня")
                    put("entity_id", "light.lampa1")
                    put("control_profile", "color_scene")
                    put("supported_quick_actions", listOf("TURN_ON", "TURN_OFF", "COZY", "MOVIE"))
                    put("capabilities", JSONObject().apply {
                        put("on_off", true)
                        put("brightness", true)
                        put("rgb", true)
                        put("color_temp", true)
                        put("transition", true)
                    })
                },
                JSONObject().apply {
                    put("device_id", "device_switch_1")
                    put("name", "Розетка")
                    put("device_type", "switch")
                    put("area_id", "area_bedroom")
                    put("area_name", "Спальня")
                    put("entity_id", "switch.bedside")
                    put("control_profile", "power_only")
                    put("supported_quick_actions", listOf("TURN_ON", "TURN_OFF"))
                    put("capabilities", JSONObject().apply {
                        put("on_off", true)
                    })
                }
            ))
        }.toString()

        val catalog = parseDeviceCatalog(json)

        assertEquals("1.0", catalog.schemaVersion)
        assertEquals(1, catalog.areas.size)
        assertEquals("Спальня", catalog.areas.first().name)
        assertEquals(listOf("light", "switch"), catalog.areas.first().deviceTypes)
        assertEquals(2, catalog.areas.first().targetProfiles.size)
        assertEquals("color_scene", catalog.areas.first().targetProfiles.first().profileId)
        assertEquals(2, catalog.devices.size)
        assertEquals("light", catalog.devices.first().deviceType)
        assertEquals("color_scene", catalog.devices.first().controlProfile)
        assertTrue(catalog.devices.first().supportedQuickActions.contains("COZY"))
        assertTrue(catalog.devices.first().capabilities.brightness)
        assertFalse(catalog.devices.last().capabilities.brightness)
        assertEquals("power_only", catalog.devices.last().controlProfile)
        assertEquals("switch.bedside", catalog.devices.last().entityId)
    }

    @Test
    fun parseGatewayReadiness_extractsLiveReadinessAndDetails() {
        val json = JSONObject().apply {
            put("ok", true)
            put("ready_for_live_commands", false)
            put("ready_for_llm_commands", true)
            put("gateway", JSONObject().apply {
                put("ok", true)
                put("configured", true)
                put("detail", "reachable")
            })
            put("home_assistant", JSONObject().apply {
                put("ok", false)
                put("configured", false)
                put("detail", "HA_TOKEN is not set")
            })
            put("llm", JSONObject().apply {
                put("ok", true)
                put("configured", true)
                put("detail", "configured (model=qwen-mini)")
            })
        }.toString()

        val result = parseGatewayReadiness(json, latencyMs = 42L, liveMode = true)

        assertFalse(result.ok)
        assertTrue(result.gatewayReachable)
        assertEquals("Gateway available, Home Assistant is not ready", result.message)
        assertEquals(42L, result.latencyMs)
        assertEquals(
            listOf(
                "Gateway: reachable",
                "Home Assistant: HA_TOKEN is not set",
                "LLM: configured (model=qwen-mini)"
            ),
            result.detailLines
        )
    }

    @Test
    fun parseScenarioPreviewOk_extractsAutomationPreviewAndTiming() {
        val json = JSONObject().apply {
            put("status", "PREVIEW_READY")
            put("say_text", "Сценарий подготовлен.")
            put("parsed_bundle", JSONObject().apply {
                put("title", "Вечерний свет")
                put("rules", listOf(
                    JSONObject().apply { put("rule_id", "evening_on") }
                ))
            })
            put("validated_bundle", JSONObject().apply {
                put("status", "VALIDATED")
            })
            put("automations", listOf(
                JSONObject().apply {
                    put("id", "evening_on")
                    put("alias", "Вечерний свет: Включить вечером")
                }
            ))
            put("timing_ms", JSONObject().apply {
                put("parse", 1400)
                put("validate", 0)
                put("compile", 0)
                put("llm", JSONObject().apply {
                    put("duration_ms", 1390)
                    put("prompt_tokens", 410)
                    put("completion_tokens", 55)
                    put("total_tokens", 465)
                    put("model", "qwen-scenario")
                })
            })
        }.toString()

        val result = parseScenarioPreviewOk(json)

        assertEquals("PREVIEW_READY", result.status)
        assertEquals("Сценарий подготовлен.", result.sayText)
        assertEquals("Вечерний свет", result.parsedSummary.title)
        assertEquals(1, result.parsedSummary.ruleCount)
        assertEquals(1, result.automationCount)
        assertEquals(1400L, result.timing.parseMs)
        assertEquals(1390L, result.timing.llm?.durationMs)
        assertEquals(410, result.timing.llm?.promptTokens)
        assertTrue(result.automationsJson.contains("evening_on"))
    }

    @Test
    fun parseScenarioPreviewOk_extractsClarification() {
        val json = JSONObject().apply {
            put("status", "NEEDS_CLARIFICATION")
            put("say_text", "Уточните освещённость.")
            put("clarification", JSONObject().apply {
                put("needed", true)
                put("question", "Какой порог освещённости использовать?")
                put("missing_fields", listOf("lux_threshold"))
            })
            put("parsed_bundle", JSONObject().apply {
                put("title", "Свет по датчику")
                put("rules", emptyList<JSONObject>())
            })
            put("automations", emptyList<JSONObject>())
            put("timing_ms", JSONObject().apply {
                put("parse", 980)
                put("validate", 0)
                put("compile", 0)
            })
        }.toString()

        val result = parseScenarioPreviewOk(json)

        assertEquals("NEEDS_CLARIFICATION", result.status)
        assertTrue(result.parsedSummary.clarificationNeeded)
        assertEquals("Какой порог освещённости использовать?", result.clarification?.question)
        assertEquals(listOf("lux_threshold"), result.clarification?.missingFields)
        assertEquals(0, result.automationCount)
    }

    @Test
    fun parseScenarioSaveOk_extractsSaveStatusAndCounts() {
        val json = JSONObject().apply {
            put("status", "SAVED_ACTIVE")
            put("say_text", "Сценарий сохранён и активирован.")
            put("saved_automation_count", 2)
            put("file_automation_count", 7)
            put("storage_file", "/config/smarthome_gateway_automations.yaml")
            put("include_detected", true)
            put("reloaded", true)
            put("include_hint", JSONObject.NULL)
        }.toString()

        val result = parseScenarioSaveOk(json)

        assertEquals("SAVED_ACTIVE", result.status)
        assertEquals("Сценарий сохранён и активирован.", result.sayText)
        assertEquals(2, result.savedAutomationCount)
        assertEquals(7, result.fileAutomationCount)
        assertEquals("/config/smarthome_gateway_automations.yaml", result.storageFile)
        assertTrue(result.includeDetected)
        assertTrue(result.reloaded)
        assertEquals(null, result.includeHint)
    }

    @Test
    fun parseScenarioSaveOk_extractsIncludeHintWhenReloadUnavailable() {
        val json = JSONObject().apply {
            put("status", "SAVED_NEEDS_INCLUDE")
            put("say_text", "Сценарий сохранён, но не активирован.")
            put("saved_automation_count", 1)
            put("file_automation_count", 1)
            put("include_detected", false)
            put("reloaded", false)
            put("include_hint", "Добавьте include в configuration.yaml")
        }.toString()

        val result = parseScenarioSaveOk(json)

        assertEquals("SAVED_NEEDS_INCLUDE", result.status)
        assertFalse(result.includeDetected)
        assertFalse(result.reloaded)
        assertEquals("Добавьте include в configuration.yaml", result.includeHint)
    }
    @Test
    fun parseScenarioListOk_extractsItemsAndJson() {
        val json = JSONObject().apply {
            put("ok", true)
            put("storage_file", "/config/smarthome_gateway_automations.yaml")
            put("file_automation_count", 2)
            put("items", listOf(
                JSONObject().apply {
                    put("automation_id", "rule_1")
                    put("alias", "Evening")
                    put("trigger_summary", "time 20:00:00")
                    put("action_summary", "light.turn_on")
                    put("automation", JSONObject().apply {
                        put("id", "rule_1")
                        put("alias", "Evening")
                    })
                }
            ))
        }.toString()

        val result = parseScenarioListOk(json)

        assertEquals("/config/smarthome_gateway_automations.yaml", result.storageFile)
        assertEquals(2, result.fileAutomationCount)
        assertEquals(1, result.items.size)
        assertEquals("rule_1", result.items.first().automationId)
        assertTrue(result.items.first().automationJson.contains("\"id\": \"rule_1\""))
    }

    @Test
    fun parseScenarioDeleteOk_extractsDeleteStatus() {
        val json = JSONObject().apply {
            put("status", "DELETED_ACTIVE")
            put("say_text", "Сценарий удалён")
            put("deleted_automation_id", "rule_1")
            put("file_automation_count", 1)
            put("storage_file", "/config/smarthome_gateway_automations.yaml")
        }.toString()

        val result = parseScenarioDeleteOk(json)

        assertEquals("DELETED_ACTIVE", result.status)
        assertEquals("Сценарий удалён", result.sayText)
        assertEquals("rule_1", result.deletedAutomationId)
        assertEquals(1, result.fileAutomationCount)
        assertEquals("/config/smarthome_gateway_automations.yaml", result.storageFile)
    }
}
