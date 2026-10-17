package com.ai.assistant.backend_java.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** Validate cached bytes; downloading and the configured limit belong to Python. */
public final class ResearchSourcePdf {
    private static final int ABSOLUTE_MAX_BYTES = 64 * 1024 * 1024;
    private ResearchSourcePdf() { }

    public static byte[] decode(Map<?, ?> source) {
        if (!(source.get("pdfBase64") instanceof String encoded)) return null;
        if (encoded.length() > 4L * ((ABSOLUTE_MAX_BYTES + 2L) / 3L)) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "全文超过服务上限");
        }
        try {
            byte[] body = Base64.getDecoder().decode(encoded);
            if (body.length < 5 || body.length > ABSOLUTE_MAX_BYTES
                    || !"%PDF-".equals(new String(body, 0, 5, StandardCharsets.US_ASCII))
                    || !HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body))
                            .equals(source.get("contentHash"))) {
                throw new IllegalArgumentException();
            }
            return body;
        } catch (Exception error) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "全文内容校验失败");
        }
    }
}
