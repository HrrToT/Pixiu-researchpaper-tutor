package com.ai.assistant.backend_java.service;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import java.time.Instant;
import java.util.*;
import java.security.MessageDigest;
import com.ai.assistant.backend_java.model.*;
import com.ai.assistant.backend_java.repository.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.http.ResponseEntity;
class ResearchSourceProcessingTest {
 @Test void newSourceHasNoAiAnalysisAndDuplicateReceiptDoesNotWriteAgain() throws Exception {
  var tasks=mock(TaskWorkspaceRepository.class);var papers=mock(PaperRepository.class);
  var mapper=new ObjectMapper();var service=new TaskWorkspaceService(tasks,mapper);
  ReflectionTestUtils.setField(service,"researchPapers",papers);
  var task=new TaskWorkspace();task.setId("task");task.setUpdatedAt(Instant.now());ReflectionTestUtils.setField(task,"revision",7L);
  task.setPayloadJson(mapper.writeValueAsString(Map.of("paperIds",List.of(),"researchRuns",List.of(Map.of("runId","run","engineVersion","deep-research-v2")))));
  when(tasks.lockById("task")).thenReturn(Optional.of(task));when(tasks.saveAndFlush(any())).thenAnswer(c->c.getArgument(0));
  byte[] pdf="%PDF-test".getBytes(java.nio.charset.StandardCharsets.US_ASCII);
  String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(pdf));
  Map<String,Object> source=Map.of("arxivId","2403.17888v3","contentHash",hash,"pdfBase64",Base64.getEncoder().encodeToString(pdf));
  var input=Map.<String,Object>of("requestId","request","expectedTaskRevision",7);
  var first=service.addResearchSource("task","run","source",input,source);assertEquals(false,first.get("sourceAlreadyAdded"));
  var saved=org.mockito.ArgumentCaptor.forClass(Paper.class);verify(papers).saveAndFlush(saved.capture());
  assertEquals("not_requested",saved.getValue().getAiAnalysisStatus());assertEquals("pending",saved.getValue().getProcessingStatus());
  var duplicate=service.addResearchSource("task","run","source",input,source);
  assertEquals(true,duplicate.get("sourceAlreadyAdded"));assertEquals(first.get("paperId"),duplicate.get("paperId"));
  verify(papers,times(1)).saveAndFlush(any());verify(tasks,times(1)).saveAndFlush(any());
 }
 @ParameterizedTest @ValueSource(booleans={false,true}) void onlyFirstAdditionStartsParsing(boolean repeated) {
  var tasks=mock(TaskWorkspaceService.class);var research=mock(ResearchService.class);var processing=mock(MaterialProcessingService.class);
  var service=new TaskResearchService(tasks,research);ReflectionTestUtils.setField(service,"materialProcessing",processing);
  when(tasks.get("task")).thenReturn(Map.of("researchRuns",List.of(Map.of("runId","run","engineVersion","deep-research-v2","sourcePolicy",Map.of("mode","external_only")))));
  Map<String,Object> source=Map.of("sourceId","source","accessLevel","fulltext");
  when(research.exportV2Source("run","source")).thenReturn(ResponseEntity.ok(Map.of("status","success","source",source)));
  when(tasks.addResearchSource(eq("task"),eq("run"),eq("source"),anyMap(),eq(source))).thenReturn(Map.of("status","success","paperId","paper.pdf","sourceAlreadyAdded",repeated));
  service.addSource("task","run","source",Map.of("requestId","request"));
  verify(processing,times(repeated?0:1)).request("paper.pdf",false);verify(processing,never()).request(anyString(),eq(true));
 }
}
