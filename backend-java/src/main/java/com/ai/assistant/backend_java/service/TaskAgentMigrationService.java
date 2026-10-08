package com.ai.assistant.backend_java.service;
import java.util.*;
import java.nio.charset.StandardCharsets;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import com.ai.assistant.backend_java.model.TaskMigrationSnapshot;
import com.ai.assistant.backend_java.repository.*;
import com.fasterxml.jackson.databind.*;
@Service
public class TaskAgentMigrationService {
    private final TaskWorkspaceRepository repository;
    private final TaskMigrationSnapshotRepository backups;
    private final TaskWorkspaceService tasks;
    private final ObjectMapper mapper;
    public TaskAgentMigrationService(TaskWorkspaceRepository repository, TaskMigrationSnapshotRepository backups,
            TaskWorkspaceService tasks, ObjectMapper mapper) {
        this.repository=repository; this.backups=backups; this.tasks=tasks; this.mapper=mapper;
    }
    @Transactional
    public Map<String,Object> importProject(Map<String,Object> input) {
        if (!(input.get("snapshot") instanceof Map<?,?> snapshot)
            || !(snapshot.get("project") instanceof Map<?,?> project)
            || !(project.get("projectId") instanceof String projectId) || projectId.isBlank()
            || !(input.get("task") instanceof Map<?,?> prepared))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "迁移需要完整项目快照和整理后的任务");
        String id="legacy-agent:" + UUID.nameUUIDFromBytes(projectId.getBytes(StandardCharsets.UTF_8));
        String json;
        try { json=mapper.copy().configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS,true).writeValueAsString(snapshot); }
        catch (Exception error) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"旧项目无法备份",error); }
        String fingerprint=UUID.nameUUIDFromBytes(json.getBytes(StandardCharsets.UTF_8)).toString();
        String backupId="agent-import:" + UUID.nameUUIDFromBytes((id+":"+fingerprint).getBytes(StandardCharsets.UTF_8));
        if (!backups.existsById(backupId)) {
            var backup=new TaskMigrationSnapshot(); backup.setId(backupId); backup.setTaskId(id); backup.setPayloadJson(json);
            backups.saveAndFlush(backup);
        }
        var existing=repository.lockById(id);
        if (existing.isPresent()) {
            var current=tasks.get(id);
            boolean same=current.get("legacyMigration") instanceof Map<?,?> marker && fingerprint.equals(marker.get("fingerprint"));
            return Map.of("status",same?"already_imported":"conflicted","task",current,"backupId",backupId,
                "message",same?"已迁移，保留当前编辑":"旧项目有新版本，已备份；现有任务未覆盖");
        }
        var task=new LinkedHashMap<String,Object>(); prepared.forEach((key,value)->task.put(String.valueOf(key),value));
        task.put("id",id); task.put("activeActivity",null); task.put("researchRuns",List.of()); task.put("appliedRequestIds",List.of());
        if (task.get("messages") instanceof List<?> messages) {
            var rebound=new ArrayList<Object>();
            for (Object raw : messages) {
                if (!(raw instanceof Map<?,?> message)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"旧对话必须是对象");
                var copied=new LinkedHashMap<String,Object>(); message.forEach((key,value)->copied.put(String.valueOf(key),value));
                if (copied.get("context") instanceof Map<?,?> context) {
                    var scope=new LinkedHashMap<String,Object>(); context.forEach((key,value)->scope.put(String.valueOf(key),value));
                    scope.put("taskId",id); copied.put("context",scope);
                }
                rebound.add(copied);
            }
            task.put("messages",rebound);
        }
        task.put("legacyMigration",Map.of("projectId",projectId,"fingerprint",fingerprint,"backupId",backupId));
        task.put("legacyArchive",snapshot);
        return Map.of("status","imported","task",tasks.create(task),"backupId",backupId);
    }
}
