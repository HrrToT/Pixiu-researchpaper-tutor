package com.ai.assistant.backend_java.controller;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.http.MediaType;
import com.ai.assistant.backend_java.repository.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.type.TypeReference;
@SpringBootTest @AutoConfigureMockMvc
class TaskAgentMigrationControllerTest {
    @Autowired MockMvc mvc; @Autowired ObjectMapper mapper;
    @Autowired TaskWorkspaceRepository tasks; @Autowired TaskMigrationSnapshotRepository backups;
    @BeforeEach void clear() { backups.deleteAll(); tasks.deleteAll(); }
    Map<String,Object> read(String json) throws Exception { return mapper.readValue(json,new TypeReference<>(){}); }
    Map<String,Object> input() {
        return new LinkedHashMap<>(Map.of("snapshot",Map.of("project",Map.of("projectId","old-project", "paperIds",List.of("A")),
            "serverSnapshot",Map.of("runs",List.of(Map.of("runId","old-run","status","queued"))),"browserSnapshot",Map.of("draftReport","原浏览器草稿")),
            "task",Map.of("title","旧项目","paperIds",List.of("A"),
                "messages",List.of(Map.of("role","ai","content","原会话","context",Map.of("taskId","old","allowedPaperIds",List.of("A")))),
                "artifacts",List.of(Map.of("id","report","text","完整报告","sources",List.of(Map.of("pdfId","A","sourceId","s")),"versions",List.of(Map.of("text","旧版")))),
                "activeActivity",Map.of("activityId","old-run"),"researchRuns",List.of(Map.of("researchId","old-run")))));
    }
    Map<String,Object> migrate(Map<String,Object> input) throws Exception {
        return read(mvc.perform(post("/api/task-workspaces/migrations/agent-projects").contentType(MediaType.APPLICATION_JSON)
            .content(mapper.writeValueAsString(input))).andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
    }
    @Test void copiesFullSnapshotAndKeepsNewEditsOnReplay() throws Exception {
        var original=input(); var imported=migrate(original); assertEquals("imported",imported.get("status"));
        var task=new LinkedHashMap<String,Object>((Map<String,Object>)imported.get("task"));
        assertNull(task.get("activeActivity")); assertEquals(List.of(),task.get("researchRuns"));
        assertEquals(original.get("snapshot"),task.get("legacyArchive"));
        assertEquals(task.get("id"),((Map<?,?>)((Map<?,?>)((List<?>)task.get("messages")).getFirst()).get("context")).get("taskId"));
        assertEquals(original.get("snapshot"),read(mvc.perform(get("/api/task-workspaces/"+task.get("id")+"/migration-backups/"+imported.get("backupId")))
            .andExpect(status().isOk()).andReturn().getResponse().getContentAsString()));
        task.put("title","用户新编辑"); task.remove("legacyArchive"); task.remove("legacyMigration");
        var edited=read(mvc.perform(put("/api/task-workspaces/"+task.get("id")).contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(task)))
            .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        assertEquals(original.get("snapshot"),edited.get("legacyArchive"));
        var replay=migrate(original); assertEquals("already_imported",replay.get("status")); assertEquals(edited,replay.get("task"));
        assertEquals(1,tasks.count()); assertEquals(1,backups.count());
    }
    @Test void changedOldVersionIsBackedUpWithoutOverwritingImportedReport() throws Exception {
        var original=input(); var first=migrate(original);
        var changed=new LinkedHashMap<String,Object>((Map<String,Object>)original.get("snapshot")); changed.put("extra","旧应用的新内容"); original.put("snapshot",changed);
        var second=migrate(original); assertEquals("conflicted",second.get("status"));
        assertEquals(first.get("task"),second.get("task")); assertEquals(1,tasks.count()); assertEquals(2,backups.count());
        var current=(Map<?,?>)first.get("task");
        assertEquals(changed,read(mvc.perform(get("/api/task-workspaces/"+current.get("id")+"/migration-backups/"+second.get("backupId")))
            .andReturn().getResponse().getContentAsString()));
    }
    @Test void rejectedTaskRollsBackPreparedBackup() throws Exception {
        var invalid=input(); invalid.put("task",Map.of("paperIds",List.of("A"),"focusedPaperId","B"));
        mvc.perform(post("/api/task-workspaces/migrations/agent-projects").contentType(MediaType.APPLICATION_JSON)
            .content(mapper.writeValueAsString(invalid))).andExpect(status().isBadRequest());
        assertEquals(0,tasks.count()); assertEquals(0,backups.count());
    }
}
