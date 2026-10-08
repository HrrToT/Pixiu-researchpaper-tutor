package com.ai.assistant.backend_java.service;

import java.io.IOException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import com.ai.assistant.backend_java.model.TaskWorkspace;
import com.ai.assistant.backend_java.repository.TaskWorkspaceRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class TaskWorkspaceService {
    private final TaskWorkspaceRepository repository;
    private final ObjectMapper mapper;

    public TaskWorkspaceService(TaskWorkspaceRepository repository, ObjectMapper mapper) {
        this.repository = repository;
        this.mapper = mapper;
    }

    @Transactional(readOnly = true)
    public List<Map<String, Object>> list() {
        return repository.findAllByOrderByUpdatedAtDesc().stream().map(this::toResponse).toList();
    }

    @Transactional(readOnly = true)
    public Map<String, Object> get(String id) {
        return toResponse(find(id));
    }

    @Transactional
    public Map<String, Object> create(Map<String, Object> input) {
        String id = input.get("id") == null ? "task:" + UUID.randomUUID() : validId(input.get("id"));
        if (repository.existsById(id)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "任务已存在");
        }
        TaskWorkspace entity = new TaskWorkspace();
        entity.setId(id);
        Map<String, Object> initial = new LinkedHashMap<>(input);
        initial.put("researchRuns", List.of());
        setContent(entity, initial, id);
        return toResponse(repository.saveAndFlush(entity));
    }

    @Transactional
    public Map<String, Object> update(String id, Map<String, Object> input) {
        TaskWorkspace entity = find(id);
        if (input.containsKey("id") && !id.equals(validId(input.get("id")))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "任务 ID 与路径不一致");
        }
        requireRevision(input.get("revision"), entity.getRevision());
        Map<String, Object> protectedInput = new LinkedHashMap<>(input);
        protectedInput.put("researchRuns", toResponse(entity).getOrDefault("researchRuns", List.of()));
        setContent(entity, protectedInput, id);
        return toResponse(repository.saveAndFlush(entity));
    }

    @Transactional
    public Map<String, Object> createFromClient(Map<String, Object> input) {
        Map<String, Object> safe = new LinkedHashMap<>(input);
        List<Object> history = new ArrayList<>(array(input.get("activityHistory"), "activityHistory"));
        if (input.get("activeActivity") instanceof Map<?, ?> activity) {
            Map<String, Object> imported = new LinkedHashMap<>();
            activity.forEach((key, value) -> imported.put(String.valueOf(key), value));
            imported.put("imported", true);
            history.add(imported);
        }
        safe.put("activeActivity", null);
        safe.put("activityHistory", history);
        safe.put("appliedRequestIds", List.of());
        return create(safe);
    }

    /** Browser writes may not replace the server's activity, request receipts or run ownership. */
    @Transactional
    public Map<String, Object> updateFromClient(String id, Map<String, Object> input) {
        TaskWorkspace entity = find(id);
        requireRevision(input.get("revision"), entity.getRevision());
        Map<String, Object> authority = toResponse(entity);
        Map<String, Object> protectedInput = new LinkedHashMap<>(input);
        for (String field : List.of("activeActivity", "activityHistory", "appliedRequestIds", "researchRuns", "legacyMigration", "legacyArchive")) {
            protectedInput.put(field, authority.get(field));
        }
        // Removing materials cannot invalidate a saved activity or research snapshot.
        List<String> ids = paperIds(protectedInput.get("paperIds"));
        if (authority.get("activeActivity") instanceof Map<?, ?> activity
                && activity.get("pdfId") != null && !"finished".equals(activity.get("status")) && !ids.contains(activity.get("pdfId"))) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "请先结束该论文的学习活动再移出材料");
        }
        return update(id, protectedInput);
    }

    /** Atomically merge a durable Python result; polling/replaying never publishes it twice. */
    @Transactional
    @SuppressWarnings("unchecked")
    public Map<String, Object> applyOperation(String id, Map<String, Object> operation) {
        TaskWorkspace entity = repository.lockById(validId(id))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在"));
        Map<String, Object> task = toResponse(entity);
        String requestId = (String) operation.get("requestId");
        List<Object> applied = new ArrayList<>(array(task.get("appliedRequestIds"), "appliedRequestIds"));
        if (applied.contains(requestId)) return task;
        Map<String, Object> payload = (Map<String, Object>) operation.get("input");
        Map<String, Object> upstream = (Map<String, Object>) payload.get("upstream");
        Map<String, Object> result = (Map<String, Object>) operation.get("result");
        String kind = (String) operation.get("kind");
        List<String> scope = paperIds(payload.get("paperIds"));
        if (!((List<?>) task.get("paperIds")).containsAll(scope)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "请求材料已移出任务，结果保留在请求记录中");
        }
        if (Integer.valueOf(1).equals(result.get("resultVersion"))) {
            if (!(result.get("materialScope") instanceof Map<?, ?> materialScope)
                    || !id.equals(materialScope.get("taskId")) || !scope.equals(materialScope.get("allowedPaperIds"))
                    || (materialScope.get("primaryPaperId") != null && !scope.contains(materialScope.get("primaryPaperId")))
                    || !(result.get("sources") instanceof List<?> sources)
                    || sources.stream().anyMatch(source -> !(source instanceof Map<?, ?> item) || !scope.contains(item.get("pdfId")))
                    || !(result.get("message") instanceof String message) || message.isBlank())
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "能力结果不符合任务材料快照");
        }
        if (kind.startsWith("learning.")) {
            Map<String, Object> old = task.get("activeActivity") instanceof Map<?, ?> value ? (Map<String, Object>) value : null;
            if (kind.equals("learning.action")) {
                if (old == null || !upstream.get("activityId").equals(old.get("activityId"))) {
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "学习活动已改变，原请求结果保留");
                }
                requireRevision(upstream.get("expectedRevision"), ((Number) old.get("revision")).longValue());
            } else if (old != null && !"finished".equals(old.get("status"))) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "已有未结束学习活动，请核对请求结果");
            }
            if (!(result.get("state") instanceof Map<?, ?> rawState)) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "学习结果缺少活动状态");
            }
            Map<String, Object> state = new LinkedHashMap<>((Map<String, Object>) rawState);
            long expectedRevision = kind.equals("learning.start") ? 0 : ((Number) upstream.get("expectedRevision")).longValue() + 1;
            if (!id.equals(state.get("taskId")) || !scope.getFirst().equals(state.get("pdfId"))
                    || !(state.get("activityId") instanceof String activityId) || activityId.isBlank()
                    || !(state.get("revision") instanceof Number revision) || revision.doubleValue() != expectedRevision
                    || (old != null && kind.equals("learning.action") && !old.get("activityId").equals(activityId))
                    || !List.of("active", "paused", "finished").contains(state.get("status"))) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "学习结果不符合任务快照");
            }
            state.put("id", activityId);
            state.put("paperIds", scope);
            state.put("primaryPaperId", scope.getFirst());
            state.put("strictScope", true);
            state.put("snapshot", Map.of("paperIds", scope, "primaryPaperId", scope.getFirst(), "strictScope", true));
            state.put("lastRequestId", requestId);
            List<Object> history = new ArrayList<>(array(task.get("activityHistory"), "activityHistory"));
            if (old != null) history.add(old);
            task.put("activityHistory", history);
            task.put("activeActivity", state);
            Map<String, Object> context = Map.of("taskId", id, "allowedPaperIds", scope,
                    "primaryPaperId", scope.getFirst(), "strictScope", true, "activityId", activityId);
            String content = String.valueOf(result.getOrDefault("message", ""));
            if (!Integer.valueOf(1).equals(result.get("resultVersion")) && "active".equals(state.get("status")) && result.get("question") instanceof String question) content += "\n\n" + question;
            List<Object> messages = new ArrayList<>(array(task.get("messages"), "messages"));
            String userText = String.valueOf(upstream.getOrDefault("text", upstream.getOrDefault("goal", "开始学习")));
            if (userText.isBlank()) userText = Map.of("hint", "给我一个提示", "skip", "跳过这个问题", "retry", "重新回答",
                    "pause", "暂停学习", "resume", "继续学习", "finish", "结束学习", "ask", "临时追问",
                    "remediate", "补充前置知识", "answer", "回答当前问题")
                    .getOrDefault(String.valueOf(upstream.get("action")), "继续学习");
            messages.add(Map.of("id", requestId + ":user", "role", "user", "content", userText, "context", context, "sourceRequestId", requestId));
            Map<String, Object> answer = new LinkedHashMap<>(Map.of("id", requestId + ":ai", "role", "ai", "content", content,
                    "context", context, "sourceRequestId", requestId));
            answer.put("rag_sources", result.getOrDefault("sources", List.of()));
            if (Integer.valueOf(1).equals(result.get("resultVersion"))) {
                answer.put("capability", result.get("capability"));
                answer.put("sentenceSourceMap", result.get("sentenceSourceMap"));
                if (result.get("artifact") instanceof Map<?, ?> artifact) {
                    if (!(artifact.get("text") instanceof String body) || body.isBlank() || !scope.equals(artifact.get("paperIds"))
                            || !result.get("sources").equals(artifact.get("sources")))
                        throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "学习成果不符合材料快照");
                    String artifactId = requestId + ":artifact";
                    Map<String, Object> saved = new LinkedHashMap<>(Map.of("id", artifactId, "title", "学习成果", "text", body,
                            "paperIds", scope, "sources", artifact.get("sources"), "versions", List.of(), "sourceRequestId", requestId,
                            "createdAt", Instant.now().toString()));
                    saved.put("sentenceSourceMap", artifact.get("sentenceSourceMap"));
                    List<Object> artifacts = new ArrayList<>(array(task.get("artifacts"), "artifacts")); artifacts.add(saved);
                    task.put("artifacts", artifacts); answer.put("artifactId", artifactId);
                }
            }
            if (!Integer.valueOf(1).equals(result.get("resultVersion")) && result.get("evaluation") instanceof Map<?, ?> evaluation && evaluation.get("references") instanceof List<?> refs) {
                answer.put("sentenceSourceMap", refs.stream().filter(Map.class::isInstance).map(ref -> {
                    Map<?, ?> reference = (Map<?, ?>) ref;
                    return Map.of("target", "message", "sentence", result.getOrDefault("message", ""),
                            "sourceIds", List.of(String.valueOf(reference.get("sourceId"))), "quote", String.valueOf(reference.get("quote")));
                }).toList());
            }
            messages.add(answer);
            task.put("messages", messages);
        } else if (kind.equals("conversation.execute")) {
            if (!(result.get("materialScope") instanceof Map<?, ?> context) || !id.equals(context.get("taskId"))
                    || !scope.equals(context.get("allowedPaperIds"))
                    || !java.util.Objects.equals(upstream.get("primaryPaperId"), context.get("primaryPaperId"))
                    || !java.util.Objects.equals(upstream.get("strictScope"), context.get("strictScope"))
                    || !java.util.Objects.equals(upstream.get("capability"), result.get("capability"))
                    || !(result.get("message") instanceof String content) || content.isBlank()
                    || !(result.get("sources") instanceof List<?> sources)
                    || sources.stream().anyMatch(source -> !(source instanceof Map<?, ?> item) || !scope.contains(item.get("pdfId")))) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "对话结果不符合材料快照");
            }
            List<Object> messages = new ArrayList<>(array(task.get("messages"), "messages"));
            Map<?, ?> original = (Map<?, ?>) payload.get("original");
            Object displayText = original.get("displayText");
            messages.add(Map.of("id", requestId + ":user", "role", "user", "content",
                    displayText instanceof String text && !text.isBlank() ? text : upstream.get("message"),
                    "context", context, "sourceRequestId", requestId));
            Map<String, Object> answer = new LinkedHashMap<>(Map.of("id", requestId + ":ai", "role", "ai", "content", content,
                    "context", context, "sourceRequestId", requestId, "capability", result.get("capability")));
            answer.put("rag_sources", sources);
            answer.put("sentenceSourceMap", result.getOrDefault("sentenceSourceMap", List.of()));
            if (result.get("artifact") instanceof Map<?, ?> artifact) {
                if (!(artifact.get("text") instanceof String body) || body.isBlank() || !scope.equals(artifact.get("paperIds"))
                        || !sources.equals(artifact.get("sources"))) throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "成果不符合对话材料快照");
                String artifactId = requestId + ":artifact";
                Map<String, Object> saved = new LinkedHashMap<>(Map.of("id", artifactId, "title", "对话成果", "text", body,
                        "paperIds", scope, "sources", sources, "versions", List.of(), "sourceRequestId", requestId,
                        "createdAt", Instant.now().toString()));
                saved.put("sentenceSourceMap", artifact.getOrDefault("sentenceSourceMap", null));
                List<Object> artifacts = new ArrayList<>(array(task.get("artifacts"), "artifacts"));
                artifacts.add(saved);
                task.put("artifacts", artifacts);
                answer.put("artifactId", artifactId);
            }
            messages.add(answer);
            task.put("messages", messages);
        } else if (kind.equals("research.start")) {
            if (!(result.get("task") instanceof Map<?, ?> research) || !(research.get("taskId") instanceof String researchId)) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "研究结果缺少任务标识");
            }
            List<Object> runs = new ArrayList<>(array(task.get("researchRuns"), "researchRuns"));
            runs.add(Map.of("researchId", researchId, "requestId", requestId, "paperIds", scope,
                    "primaryPaperId", upstream.get("pdfId"), "question", upstream.get("question"), "createdAt", operation.get("createdAt")));
            task.put("researchRuns", runs);
        } else {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "请求能力无效");
        }
        applied.add(requestId);
        task.put("appliedRequestIds", applied);
        setContent(entity, task, id);
        return toResponse(repository.saveAndFlush(entity));
    }

    /** Explicit recovery saves the generated text, without applying an obsolete learning state. */
    @Transactional
    public Map<String, Object> recoverOperationResult(String id, Map<String, Object> operation) {
        TaskWorkspace entity = repository.lockById(validId(id))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在"));
        Map<String, Object> task = toResponse(entity);
        String requestId = (String) operation.get("requestId");
        List<Object> applied = new ArrayList<>(array(task.get("appliedRequestIds"), "appliedRequestIds"));
        if (applied.contains(requestId)) return task;
        if (!id.equals(operation.get("taskId")) || !"succeeded".equals(operation.get("status"))
                || !List.of("conversation.execute", "learning.start", "learning.action").contains(operation.get("kind"))
                || !(operation.get("input") instanceof Map<?, ?> input)
                || !(operation.get("result") instanceof Map<?, ?> result))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "该请求没有可恢复的文字成果");
        List<String> scope = paperIds(input.get("paperIds"));
        if (!((List<?>) task.get("paperIds")).containsAll(scope))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "请先恢复原请求材料，再保存成果；已生成结果仍可查看");
        if (!(result.get("message") instanceof String message) || message.isBlank()
                || !(result.get("sources") instanceof List<?> sources)
                || sources.stream().anyMatch(source -> !(source instanceof Map<?, ?> item) || !scope.contains(item.get("pdfId")))
                || !(result.get("materialScope") instanceof Map<?, ?> context)
                || !id.equals(context.get("taskId")) || !scope.equals(context.get("allowedPaperIds"))
                || (context.get("primaryPaperId") != null && !scope.contains(context.get("primaryPaperId"))))
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "已生成结果不符合原材料快照");
        String body = message;
        if (result.get("artifact") instanceof Map<?, ?> artifact) {
            if (!(artifact.get("text") instanceof String text) || text.isBlank()
                    || !scope.equals(artifact.get("paperIds")) || !sources.equals(artifact.get("sources")))
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "成果不符合原材料快照");
            body = text;
        }
        String artifactId = requestId + ":artifact";
        Map<String, Object> artifact = new LinkedHashMap<>(Map.of("id", artifactId, "title", "恢复的成果",
                "text", body, "paperIds", scope, "sources", sources, "versions", List.of(),
                "sourceRequestId", requestId, "createdAt", Instant.now().toString()));
        artifact.put("sentenceSourceMap", result.containsKey("sentenceSourceMap") ? result.get("sentenceSourceMap") : List.of());
        List<Object> artifacts = new ArrayList<>(array(task.get("artifacts"), "artifacts"));
        artifacts.add(artifact); task.put("artifacts", artifacts);
        List<Object> messages = new ArrayList<>(array(task.get("messages"), "messages"));
        messages.add(Map.of("id", requestId + ":recovered", "role", "ai", "content", "已生成结果已保存为成果，当前学习位置保留。",
                "artifactId", artifactId, "sourceRequestId", requestId, "context", context,
                "rag_sources", sources, "timestamp", System.currentTimeMillis()));
        task.put("messages", messages); applied.add(requestId); task.put("appliedRequestIds", applied);
        setContent(entity, task, id);
        return toResponse(repository.saveAndFlush(entity));
    }

    /** Publish a completed research report under the task lock, without replacing client edits. */
    @Transactional
    public Map<String, Object> publishResearchResult(String id, String researchId, Map<?, ?> research) {
        TaskWorkspace entity = repository.lockById(validId(id))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在"));
        Map<String, Object> task = toResponse(entity);
        Map<?, ?> run = array(task.get("researchRuns"), "researchRuns").stream()
                .filter(value -> value instanceof Map<?, ?> item && researchId.equals(item.get("researchId")))
                .map(value -> (Map<?, ?>) value).findFirst()
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "研究任务不属于当前任务"));
        if (!researchId.equals(research.get("taskId")))
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "研究服务返回的任务不匹配");
        if (!"succeeded".equals(research.get("status"))) return task;
        String receipt = "research:" + researchId;
        List<Object> applied = new ArrayList<>(array(task.get("appliedRequestIds"), "appliedRequestIds"));
        if (applied.contains(receipt)) return task;
        List<String> scope = paperIds(run.get("paperIds"));
        if (!((List<?>) task.get("paperIds")).containsAll(scope))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "研究材料已移出任务，请恢复原材料后保存成果");
        if (!(research.get("report") instanceof String report) || report.isBlank())
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "研究报告为空，尚未保存成果");
        List<Object> sources = new ArrayList<>();
        List<String> conclusions = new ArrayList<>();
        for (Object raw : array(research.get("findings"), "findings")) {
            if (!(raw instanceof Map<?, ?> finding))
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "研究发现格式无效");
            if (finding.get("claims") instanceof List<?> claims && !claims.isEmpty()) {
                for (Object item : claims) {
                    if (conclusions.size() >= 3) break;
                    if (item instanceof Map<?, ?> claim && claim.get("summary") instanceof String summary && !summary.isBlank())
                        conclusions.add(summary.length() > 180 ? summary.substring(0, 180) + "…" : summary);
                }
            } else if (finding.get("summary") instanceof String summary && !summary.isBlank() && conclusions.size() < 3) {
                // Legacy findings can contain long internal source ids; sources remain available separately.
                String plain = summary.replaceAll("\\[[^\\]\\r\\n]*\\.pdf-chunk-[^\\]\\r\\n]*\\]", "").strip();
                conclusions.add(plain.length() > 180 ? plain.substring(0, 180) + "…" : plain);
            }
            for (Object evidence : array(finding.get("sources"), "sources")) {
                if (!(evidence instanceof Map<?, ?> source) || !(source.get("pdfId") instanceof String pdfId))
                    throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "研究来源缺少论文标识");
                List<String> matches = scope.stream().filter(paper -> paper.equals(pdfId)
                        || paper.replaceFirst("(?i)\\.pdf$", "").equals(pdfId.replaceFirst("(?i)\\.pdf$", ""))).toList();
                if (matches.size() != 1)
                    throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "研究来源超出材料快照或标识不明确");
                Map<String, Object> normalized = new LinkedHashMap<>();
                source.forEach((key, value) -> normalized.put(String.valueOf(key), value));
                normalized.put("pdfId", matches.getFirst());
                if (!sources.contains(normalized)) sources.add(normalized);
            }
        }
        String artifactId = receipt + ":artifact";
        String now = Instant.now().toString();
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("taskId", id); context.put("allowedPaperIds", scope);
        context.put("primaryPaperId", run.get("primaryPaperId")); context.put("strictScope", true);
        String preview = conclusions.isEmpty() ? "研究已完成。" : String.join("\n\n", conclusions);
        Map<String, Object> answer = new LinkedHashMap<>(Map.of("id", receipt + ":answer", "role", "ai",
                "content", preview + "\n\n完整报告已保存在成果中。", "capability", "research",
                "artifactId", artifactId, "sourceResearchId", researchId, "context", context,
                "rag_sources", sources, "sentenceSourceMap", List.of(), "timestamp", System.currentTimeMillis()));
        Map<String, Object> artifact = new LinkedHashMap<>(Map.of("id", artifactId, "title",
                run.get("question") instanceof String question && !question.isBlank() ? question : "研究成果",
                "text", report, "paperIds", scope, "sources", sources, "sourceResearchId", researchId,
                "versions", List.of(), "createdAt", now));
        List<Object> messages = new ArrayList<>(array(task.get("messages"), "messages"));
        List<Object> artifacts = new ArrayList<>(array(task.get("artifacts"), "artifacts"));
        // Existing client-published legacy results remain intact; mark them as already adopted.
        boolean saved = artifacts.stream().anyMatch(value -> value instanceof Map<?, ?> item
                && researchId.equals(item.get("sourceResearchId")));
        if (!saved) {
            artifacts.add(artifact);
            messages.add(answer);
        }
        task.put("messages", messages); task.put("artifacts", artifacts);
        applied.add(receipt); task.put("appliedRequestIds", applied);
        setContent(entity, task, id);
        return toResponse(repository.saveAndFlush(entity));
    }

    /** Research ownership can only be established after a successful upstream creation. */
    @Transactional
    public Map<String, Object> attachResearchRun(String id, Object revision, Map<String, Object> run) {
        TaskWorkspace entity = find(id);
        requireRevision(revision, entity.getRevision());
        Map<String, Object> input = toResponse(entity);
        List<Object> runs = new ArrayList<>(array(input.get("researchRuns"), "researchRuns"));
        runs.add(run);
        input.put("researchRuns", runs);
        setContent(entity, input, id);
        return toResponse(repository.saveAndFlush(entity));
    }

    @Transactional
    public void delete(String id, long revision) {
        TaskWorkspace entity = find(id);
        requireRevision(revision, entity.getRevision());
        repository.delete(entity);
        repository.flush();
    }

    private TaskWorkspace find(String id) {
        return repository.findById(validId(id))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在"));
    }

    private void setContent(TaskWorkspace entity, Map<String, Object> input, String id) {
        Map<String, Object> payload = normalize(input, id);
        Instant updatedAt = Instant.now().truncatedTo(java.time.temporal.ChronoUnit.MICROS);
        payload.put("updatedAt", updatedAt.toString());
        try {
            entity.setPayloadJson(mapper.writeValueAsString(payload));
        } catch (JsonProcessingException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "任务内容无法保存", exception);
        }
        entity.setUpdatedAt(updatedAt);
    }

    private Map<String, Object> normalize(Map<String, Object> input, String id) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("id", id);
        Object rawTitle = input.get("title");
        if (rawTitle != null && !(rawTitle instanceof String)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "任务标题必须是文字");
        }
        String title = rawTitle == null || ((String) rawTitle).isBlank()
                ? "未命名任务" : ((String) rawTitle).trim();
        if (title.length() > 500) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "任务标题过长");
        }
        payload.put("title", title);
        List<String> paperIds = paperIds(input.get("paperIds"));
        payload.put("paperIds", paperIds);
        payload.put("messages", array(input.get("messages"), "messages"));
        payload.put("notes", array(input.get("notes"), "notes"));
        payload.put("artifacts", array(input.get("artifacts"), "artifacts"));
        payload.put("researchRuns", array(input.get("researchRuns"), "researchRuns"));
        payload.put("activityHistory", array(input.get("activityHistory"), "activityHistory"));
        payload.put("appliedRequestIds", array(input.get("appliedRequestIds"), "appliedRequestIds"));
        for (String field : List.of("legacyMigration", "legacyArchive")) {
            if (input.get(field) != null && !(input.get(field) instanceof Map<?,?>))
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, field + " 必须是对象");
            if (input.get(field) != null) payload.put(field,input.get(field));
        }

        Object focusedPaper = input.get("focusedPaperId");
        if (focusedPaper != null && (!(focusedPaper instanceof String) || !paperIds.contains(focusedPaper))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "阅读焦点必须属于当前任务");
        }
        payload.put("focusedPaperId", focusedPaper);

        Object activeActivity = input.get("activeActivity");
        if (activeActivity != null && !(activeActivity instanceof Map<?, ?>)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "活动必须是对象");
        }
        payload.put("activeActivity", activeActivity);
        return payload;
    }

    private List<String> paperIds(Object value) {
        if (value == null) return List.of();
        if (!(value instanceof List<?> raw)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "论文 ID 必须是数组");
        }
        LinkedHashSet<String> unique = new LinkedHashSet<>();
        for (Object item : raw) {
            if (!(item instanceof String id) || id.isBlank()) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "论文 ID 必须是非空文字");
            }
            unique.add(id);
        }
        return new ArrayList<>(unique);
    }

    private List<?> array(Object value, String field) {
        if (value == null) return List.of();
        if (!(value instanceof List<?> items)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, field + " 必须是数组");
        }
        if (!field.equals("appliedRequestIds") && items.stream().anyMatch(item -> !(item instanceof Map<?, ?>))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, field + " 的条目必须是对象");
        }
        return items;
    }

    private String validId(Object value) {
        if (!(value instanceof String id) || id.isBlank() || id.length() > 255) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "任务 ID 无效");
        }
        return id;
    }

    private void requireRevision(Object supplied, Long current) {
        if (!(supplied instanceof Number number) || number.doubleValue() != Math.rint(number.doubleValue())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "必须提供整数 revision");
        }
        if (current == null || number.longValue() != current) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "任务已在其他位置更新");
        }
    }

    private Map<String, Object> toResponse(TaskWorkspace entity) {
        try {
            Map<String, Object> payload = mapper.readValue(entity.getPayloadJson(), new TypeReference<>() {});
            payload.put("id", entity.getId());
            payload.put("updatedAt", entity.getUpdatedAt().toString());
            payload.put("revision", entity.getRevision());
            return payload;
        } catch (IOException exception) {
            throw new IllegalStateException("无法读取已保存的任务", exception);
        }
    }
}
