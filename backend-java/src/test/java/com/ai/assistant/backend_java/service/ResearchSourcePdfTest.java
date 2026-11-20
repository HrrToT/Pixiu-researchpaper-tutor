package com.ai.assistant.backend_java.service;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

class ResearchSourcePdfTest {
    @Test void acceptsCachedPublicPdfAboveTheOldEightMiBLimitAndChecksHash() throws Exception {
        byte[] body = new byte[9 * 1024 * 1024];
        System.arraycopy("%PDF-".getBytes(StandardCharsets.US_ASCII), 0, body, 0, 5);
        String encoded = Base64.getEncoder().encodeToString(body);
        String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body));
        assertArrayEquals(body, ResearchSourcePdf.decode(Map.of("pdfBase64", encoded, "contentHash", hash)));
        assertThrows(ResponseStatusException.class, () -> ResearchSourcePdf.decode(Map.of("pdfBase64", encoded, "contentHash", "changed")));
    }
    @Test void metadataCannotBecomePdfAndInvalidEncodingIsRejected() {
        assertNull(ResearchSourcePdf.decode(Map.of("accessLevel", "abstract")));
        assertThrows(ResponseStatusException.class, () -> ResearchSourcePdf.decode(Map.of("pdfBase64", "not base64")));
    }
}
