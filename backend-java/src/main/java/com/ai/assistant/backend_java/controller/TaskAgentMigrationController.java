package com.ai.assistant.backend_java.controller;
import java.util.Map;
import java.util.List;
import java.util.LinkedHashMap;
import com.ai.assistant.backend_java.repository.PaperRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.dao.DataIntegrityViolationException;
import com.ai.assistant.backend_java.service.ResearchService;
import org.springframework.web.bind.annotation.*;
import com.ai.assistant.backend_java.service.TaskAgentMigrationService;
@CrossOrigin(origins={"http://localhost:5173","http://127.0.0.1:5173"},allowCredentials="true")
@RestController
@RequestMapping("/api/task-workspaces/migrations")
public class TaskAgentMigrationController {
    private final TaskAgentMigrationService service;
    private final ResearchService research;
    private final PaperRepository papers;
    public TaskAgentMigrationController(TaskAgentMigrationService service, ResearchService research, PaperRepository papers) { this.service=service; this.research=research; this.papers=papers; }
    @GetMapping("/agent-projects")
    public ResponseEntity<Map<String,Object>> list() { return research.listLegacyAgentProjects(); }
    @GetMapping("/agent-projects/{projectId}/snapshot")
    public ResponseEntity<Map<String,Object>> snapshot(@PathVariable String projectId) {
        var exported=research.exportLegacyAgentProject(projectId);
        if (!exported.getStatusCode().is2xxSuccessful() || exported.getBody()==null) return exported;
        var body=new LinkedHashMap<String,Object>(exported.getBody());
        if (body.get("snapshot") instanceof Map<?,?> snapshot && snapshot.get("project") instanceof Map<?,?> project
                && project.get("paperIds") instanceof List<?> ids) {
            body.put("materials", ids.stream().map(id -> {
                var paper=papers.findById(String.valueOf(id)).orElse(null);
                return Map.of("id",id,"fileAvailable",paper!=null && paper.getPdfBytes()!=null);
            }).toList());
        }
        return ResponseEntity.status(exported.getStatusCode()).body(body);
    }
    @PostMapping("/agent-projects")
    public Map<String,Object> importProject(@RequestBody Map<String,Object> body) {
        try { return service.importProject(body); }
        catch (DataIntegrityViolationException concurrentImport) { return service.importProject(body); }
    }
}
