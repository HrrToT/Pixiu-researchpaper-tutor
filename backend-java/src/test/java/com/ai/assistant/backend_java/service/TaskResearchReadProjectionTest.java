package com.ai.assistant.backend_java.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.web.server.ResponseStatusException;

class TaskResearchReadProjectionTest {
    private Map<String, Object> workspace() {
        return Map.of("id", "work", "paperIds", List.of("A"), "researchRuns", List.of(
            Map.of("runId", "run", "researchId", "run", "engineVersion", "deep-research-v2",
                   "runRevision", 1L, "paperIds", List.of("A"))));
    }

    @Test
    void resultUsesLatestLockedProjectionWithoutRedundantFullHistoryReads() {
        TaskWorkspaceService tasks = mock(TaskWorkspaceService.class);
        ResearchService research = mock(ResearchService.class);
        TaskResearchService service = new TaskResearchService(tasks, research);
        when(tasks.get("work")).thenReturn(workspace());
        Map<String, Object> state = Map.of("taskId", "work", "runId", "run",
            "engineVersion", "deep-research-v2", "runRevision", 2L,
            "status", "completed", "outcome", "partial",
            "report", Map.of("versionId", "v1", "body", "Checked report"));
        when(research.getV2ResearchTask("run")).thenReturn(ResponseEntity.ok(Map.of("status", "success", "task", state)));
        Map<String, Object> published = Map.of("id", "work", "artifacts", List.of("report"));
        Map<String, Object> latest = Map.of("id", "work", "artifacts", List.of("report"),
            "notes", List.of("A concurrently preserved note"), "revision", 9L);
        when(tasks.publishV2ResearchResult("work", "run", state)).thenReturn(published);
        when(tasks.updateV2RunRevision("work", "run", 2L, "completed", "partial")).thenReturn(latest);
        Map<String, Object> result = service.getUnified("work", "run");
        assertSame(latest, result.get("workspace"));
        verify(tasks, times(3)).get("work");
        verify(tasks).publishV2ResearchResult("work", "run", state);
        verify(research).getV2ResearchTask("run");
    }

    @Test
    void scopeUsesOneMaterialAndRunSnapshotAndStillFailsClosedWithoutPaperStore() {
        TaskWorkspaceService tasks = mock(TaskWorkspaceService.class);
        ResearchService research = mock(ResearchService.class);
        when(tasks.get("work")).thenReturn(workspace());
        Map<String, Object> result = new TaskResearchService(tasks, research).scopeCheck("work", "run", Map.of());
        assertEquals(false, result.get("valid"));
        verify(tasks, times(1)).get("work");
        verifyNoInteractions(research);
    }

    @Test
    void foreignRunIsRejectedBeforeUpstreamReadOrMutation() {
        TaskWorkspaceService tasks = mock(TaskWorkspaceService.class);
        ResearchService research = mock(ResearchService.class);
        when(tasks.get("work")).thenReturn(workspace());
        assertThrows(ResponseStatusException.class,
            () -> new TaskResearchService(tasks, research).getUnified("work", "foreign"));
        verifyNoInteractions(research);
        verify(tasks, never()).updateV2RunRevision(anyString(), anyString(), anyLong(), any(), any());
    }
}
