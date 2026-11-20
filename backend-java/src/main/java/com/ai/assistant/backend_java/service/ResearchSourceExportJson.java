package com.ai.assistant.backend_java.service;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadConstraints;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Map;

/** A route-specific JSON limit matching the separately verified PDF byte limit. */
final class ResearchSourceExportJson {
    static final int MAX_BASE64_CHARACTERS = 4 * ((ResearchSourcePdf.ABSOLUTE_MAX_BYTES + 2) / 3);
    static final long MAX_RESPONSE_BYTES = MAX_BASE64_CHARACTERS + 128L * 1024;
    private static final ObjectMapper MAPPER = new ObjectMapper(JsonFactory.builder()
            .streamReadConstraints(StreamReadConstraints.builder()
                    .maxStringLength(MAX_BASE64_CHARACTERS).build()).build())
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    private ResearchSourceExportJson() { }

    static Map<String, Object> read(InputStream input, long declaredLength) throws IOException {
        if (declaredLength > MAX_RESPONSE_BYTES) throw new IOException("Source export exceeds byte limit");
        return MAPPER.readValue(limited(input, MAX_RESPONSE_BYTES), new TypeReference<>() { });
    }

    static InputStream limited(InputStream input, long maximum) {
        if (maximum < 0) throw new IllegalArgumentException("Invalid source byte limit");
        return new FilterInputStream(input) {
            private long count;
            private void consumed(int size) throws IOException {
                if (size > 0 && (count += size) > maximum) throw new IOException("Source export exceeds byte limit");
            }
            @Override public int read() throws IOException {
                if (count > maximum) throw new IOException("Source export exceeds byte limit");
                int value = in.read();
                if (value >= 0) consumed(1);
                return value;
            }
            @Override public int read(byte[] bytes, int offset, int length) throws IOException {
                if (count > maximum) throw new IOException("Source export exceeds byte limit");
                int read = in.read(bytes, offset, (int) Math.min(length, maximum - count + 1));
                consumed(read);
                return read;
            }
        };
    }
}
