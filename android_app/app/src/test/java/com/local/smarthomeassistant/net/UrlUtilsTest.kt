package com.local.smarthomeassistant.net

import org.junit.Assert.assertEquals
import org.junit.Test

class UrlUtilsTest {

    @Test
    fun normalizeBaseUrl_addsSchemeAndTrims() {
        assertEquals("http://10.0.2.2:8099", normalizeBaseUrlForTest(" 10.0.2.2:8099 "))
        assertEquals("http://10.0.2.2:8099", normalizeBaseUrlForTest("http://10.0.2.2:8099/"))
        assertEquals("https://x.y", normalizeBaseUrlForTest("https://x.y/"))
    }
}
