package com.ai.assistant.backend_java.controller;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import com.ai.assistant.backend_java.repository.TaskWorkspaceRepository;
import com.ai.assistant.backend_java.service.TaskWorkspaceService;
import com.fasterxml.jackson.databind.ObjectMapper;

@SpringBootTest
@AutoConfigureMockMvc
class TaskResearchArtifactOwnershipTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired TaskWorkspaceService tasks;
    @Autowired TaskWorkspaceRepository repository;

    @BeforeEach void clear() { repository.deleteAll(); }

    private Map<String,Object> seed(Map<String,Object> artifact) {
        // Trusted service write represents existing server-authored provenance.
        return tasks.create(Map.of("id", "ownership", "paperIds", List.of(), "artifacts", List.of(artifact)));
    }

    private Map<String,Object> artifact(Map<String,Object> task) {
        return new LinkedHashMap<>((Map<String,Object>) ((List<?>)task.get("artifacts")).getFirst());
    }

    private Map<String,Object> save(Map<String,Object> task, Map<String,Object> artifact) throws Exception {
        task.put("artifacts", List.of(artifact));
        mvc.perform(put("/api/task-workspaces/ownership").contentType(MediaType.APPLICATION_JSON)
            .content(mapper.writeValueAsString(task))).andExpect(status().isOk());
        return artifact(tasks.get("ownership"));
    }

    @Test void browserCannotCreateResearchAssociationUsingOnlyAnAlias() throws Exception {
        mvc.perform(post("/api/task-workspaces").contentType(MediaType.APPLICATION_JSON)
            .content(mapper.writeValueAsString(Map.of("id", "ownership", "artifacts", List.of(Map.of(
                "id", "forged", "text", "用户正文", "sourceResearchId", "foreign-run", "reportVersionId", "foreign-version"))))))
            .andExpect(status().isCreated());
        Map<String,Object> saved = artifact(tasks.get("ownership"));
        assertFalse(saved.containsKey("sourceResearchId"));
        assertFalse(saved.containsKey("reportVersionId"));
        assertEquals("用户正文", saved.get("text"));
    }

    @Test void browserCannotResetAnEditedResearchCopyToAnUntouchedReport() throws Exception {
        Map<String,Object> task=seed(Map.of("id", "latest", "text", "我的修改", "title", "报告", "sourceRunId", "run",
            "sourceResearchId", "run", "origin", "latest", "edited", true, "versions", List.of(Map.of("text", "原稿"))));
        Map<String,Object> copy=artifact(task);copy.put("edited", false);copy.put("versions", List.of());
        Map<String,Object> saved=save(task, copy);
        assertEquals(true, saved.get("edited"));
        assertEquals("我的修改", saved.get("text"));
        assertEquals("run", saved.get("sourceRunId"));
    }

    @Test void titleEditIsProtectedAndMissingServerMetadataCannotBeInjected() throws Exception {
        Map<String,Object> task=seed(Map.of("id", "latest", "text", "原稿", "title", "原始标题", "sourceRunId", "run",
            "sourceResearchId", "run", "origin", "latest", "edited", false));
        Map<String,Object> copy=artifact(task);copy.put("title", "我的标题");copy.put("outcome", "complete");
        Map<String,Object> saved=save(task,copy);
        assertEquals("我的标题",saved.get("title"));
        assertEquals(true,saved.get("edited"));
        assertFalse(saved.containsKey("outcome"));
    }

    @Test void genuineLegacyResearchAliasCannotBeReboundByBrowser() throws Exception {
        Map<String,Object> task=seed(Map.of("id", "legacy", "text", "原稿", "title", "旧报告", "sourceResearchId", "owned-run"));
        Map<String,Object> copy=artifact(task);copy.put("sourceResearchId","foreign-run");copy.put("text","我的修改");
        assertEquals("owned-run", save(task,copy).get("sourceResearchId"));
    }
}
