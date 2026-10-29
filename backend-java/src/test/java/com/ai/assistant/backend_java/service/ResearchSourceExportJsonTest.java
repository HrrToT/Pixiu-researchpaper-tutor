package com.ai.assistant.backend_java.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

class ResearchSourceExportJsonTest {
    @Test void sourceExportSupportsRealisticPdfAboveOrdinaryJsonStringLimitWithoutChangingOtherRoutes() throws Exception {
        byte[] pdf = new byte[17 * 1024 * 1024];
        System.arraycopy("%PDF-".getBytes(StandardCharsets.US_ASCII), 0, pdf, 0, 5);
        String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(pdf));
        String body = "{\"status\":\"success\",\"source\":{\"contentHash\":\"" + hash
                + "\",\"pdfBase64\":\"" + Base64.getEncoder().encodeToString(pdf) + "\"}}";
        RestTemplate client = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.createServer(client);
        server.expect(requestTo("http://python/source/export")).andRespond(withSuccess(body, MediaType.APPLICATION_JSON));
        server.expect(requestTo("http://python/ordinary")).andRespond(withSuccess(body, MediaType.APPLICATION_JSON));
        var response = GatewayHelper.forwardSourceExport(client, "http://python", "/source/export");
        assertEquals(200, response.getStatusCode().value());
        assertArrayEquals(pdf, ResearchSourcePdf.decode((Map<?, ?>) response.getBody().get("source")));
        RestClientException rejected = assertThrows(RestClientException.class,
                () -> GatewayHelper.forward(client, "http://python", HttpMethod.GET, "/ordinary", null));
        Throwable root = rejected;
        while (root.getCause() != null) root = root.getCause();
        assertTrue(root.getClass().getSimpleName().contains("StreamConstraints"), root.toString());
        server.verify();
    }

    @Test void declaredOversizeAndMalformedExportsFailWithoutRetry() {
        RestTemplate client = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.createServer(client);
        server.expect(requestTo("http://python/large")).andRespond(withSuccess("{}", MediaType.APPLICATION_JSON)
                .header("Content-Length", String.valueOf(ResearchSourceExportJson.MAX_RESPONSE_BYTES + 1)));
        server.expect(requestTo("http://python/broken")).andRespond(withSuccess("not-json", MediaType.APPLICATION_JSON));
        server.expect(requestTo("http://python/missing")).andRespond(withStatus(HttpStatus.NOT_FOUND)
                .contentType(MediaType.APPLICATION_JSON).body("{\"status\":\"error\",\"message\":\"missing source\"}"));
        assertEquals(502, GatewayHelper.forwardSourceExport(client, "http://python", "/large").getStatusCode().value());
        assertEquals(502, GatewayHelper.forwardSourceExport(client, "http://python", "/broken").getStatusCode().value());
        assertEquals(404, GatewayHelper.forwardSourceExport(client, "http://python", "/missing").getStatusCode().value());
        server.verify();
    }

    @Test void actualStreamLimitWorksWithUnknownLengthAndSingleOrBulkReads() throws Exception {
        try (InputStream input = ResearchSourceExportJson.limited(new ByteArrayInputStream(new byte[17]), 16)) {
            assertEquals(16, input.readNBytes(16).length);
            assertThrows(IOException.class, input::read);
        }
        try (InputStream input = ResearchSourceExportJson.limited(new ByteArrayInputStream(new byte[32]), 16)) {
            assertThrows(IOException.class, () -> input.read(new byte[32]));
        }
        try (InputStream input = ResearchSourceExportJson.limited(new ByteArrayInputStream(new byte[16]), 16)) {
            assertEquals(16, input.readAllBytes().length);
        }
        assertThrows(IOException.class, () -> ResearchSourceExportJson.read(
                new ByteArrayInputStream("{} {}".getBytes(StandardCharsets.UTF_8)), -1));
    }
}
