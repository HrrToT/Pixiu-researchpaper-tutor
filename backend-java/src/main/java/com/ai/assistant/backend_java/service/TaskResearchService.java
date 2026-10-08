package com.ai.assistant.backend_java.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class TaskResearchService {
    private final TaskWorkspaceService tasks;
    private final ResearchService research;

    public TaskResearchService(TaskWorkspaceService tasks, ResearchService research) {
        this.tasks = tasks;
        this.research = research;
    }

    public Map<String, Object> start(String id, Map<String, Object> input) {
        Map<String, Object> workspace = tasks.get(id);
        Object expected = input.get("expectedTaskRevision");
        if (!(expected instanceof Number n) || n.longValue() < 0 || n.doubleValue() != n.longValue()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "必须提供整数 expectedTaskRevision");
        }
        if (n.longValue() != ((Number) workspace.get("revision")).longValue()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "任务已更新，请刷新后重试");
        }
        List<?> taskPapers = (List<?>) workspace.get("paperIds");
        Object rawScope = input.containsKey("allowedPaperIds") ? input.get("allowedPaperIds") : taskPapers;
        if (!(rawScope instanceof List<?> ids) || ids.isEmpty()
                || ids.stream().anyMatch(paper -> !(paper instanceof String) || !taskPapers.contains(paper))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "研究材料必须是当前任务内的非空论文集合");
        }
        List<?> scope = new ArrayList<>(new LinkedHashSet<>(ids));
        Object primary = input.get("pdfId");
        if (primary == null) primary = scope.contains(workspace.get("focusedPaperId")) ? workspace.get("focusedPaperId") : scope.getFirst();
        if (!(primary instanceof String) || !scope.contains(primary)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "主论文必须属于研究材料范围");
        }
        if (!(input.get("question") instanceof String question) || question.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "研究问题不能为空");
        }
        // Unified research preserves the existing default-closed external-search boundary.
        if (Boolean.TRUE.equals(input.get("allowExternalSearch")) || Boolean.TRUE.equals(input.get("allowWebSearch"))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "统一任务研究尚未授权外部检索");
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("question", question);
        body.put("pdfId", primary);
        body.put("allowedPaperIds", scope);
        body.put("allowExternalSearch", false);
        body.put("allowWebSearch", false);
        for (String field : List.of("userConstraints", "paperSkeleton", "briefPreview")) {
            if (input.containsKey(field)) body.put(field, input.get(field));
        }
        Map<String, Object> result = requireSuccess(research.createResearchTask(body));
        if (!(result.get("task") instanceof Map<?, ?> created)
                || !(created.get("taskId") instanceof String researchId) || researchId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "研究服务未返回任务标识");
        }
        Map<String, Object> run = Map.of("researchId", researchId, "paperIds", scope, "primaryPaperId", primary,
                "question", question, "createdAt", Instant.now().toString());
        try {
            Map<String, Object> saved = tasks.attachResearchRun(id, expected, run);
            return Map.of("task", saved, "result", result);
        } catch (RuntimeException conflict) {
            // Provider call ran outside a transaction. Cancel a job whose binding could not commit.
            try {
                requireSuccess(research.cancelResearchTask(researchId));
            } catch (RuntimeException cancelFailure) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                        "任务保存发生冲突，研究任务绑定未完成且取消未确认；请核对研究任务 " + researchId);
            }
            throw new ResponseStatusException(HttpStatus.CONFLICT, "任务已更新，新建研究任务已取消，请刷新后重试");
        }
    }

    public Map<String, Object> get(String id, String researchId) {
        requireOwner(id, researchId);
        return publish(id, researchId, requireSuccess(research.getResearchTask(researchId)));
    }

    public Map<String, Object> cancel(String id, String researchId) {
        requireOwner(id, researchId);
        return publish(id, researchId, requireSuccess(research.cancelResearchTask(researchId)));
    }

    public Map<String, Object> resume(String id, String researchId) {
        requireOwner(id, researchId);
        requireMaterials(id, researchId);
        return publish(id, researchId, requireSuccess(research.resumeResearchTask(researchId)));
    }

    public Map<String, Object> reviewPlan(String id, String researchId, Map<String, Object> input) {
        requireOwner(id, researchId);
        requireMaterials(id, researchId);
        Map<String, Object> body = reviewFields(input, List.of("subQuestions", "reviewNotes"));
        return publish(id, researchId, requireSuccess(research.reviewResearchPlan(researchId, body)));
    }

    public Map<String, Object> reviewFinal(String id, String researchId, Map<String, Object> input) {
        requireOwner(id, researchId);
        return publish(id, researchId, requireSuccess(research.reviewResearchFinal(researchId, reviewFields(input, List.of("reviewNotes", "riskReviews")))));
    }

    private Map<String, Object> publish(String id, String researchId, Map<String, Object> result) {
        if (!(result.get("task") instanceof Map<?, ?> state))
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "研究服务未返回任务");
        Map<String, Object> response = new LinkedHashMap<>(result);
        Map<String, Object> workspace = tasks.publishResearchResult(id, researchId, state);
        response.put("workspace", workspace);
        Map<?, ?> run = ((List<?>) workspace.get("researchRuns")).stream()
                .filter(value -> value instanceof Map<?, ?> item && researchId.equals(item.get("researchId")))
                .map(value -> (Map<?, ?>) value).findFirst().orElseThrow();
        Map<String, Object> scope = new LinkedHashMap<>();
        scope.put("taskId", id); scope.put("allowedPaperIds", run.get("paperIds"));
        scope.put("primaryPaperId", run.get("primaryPaperId")); scope.put("strictScope", true);
        Map<?, ?> artifact = ((List<?>) workspace.get("artifacts")).stream()
                .filter(value -> value instanceof Map<?, ?> item && researchId.equals(item.get("sourceResearchId")))
                .map(value -> (Map<?, ?>) value).findFirst().orElse(null);
        Map<?, ?> answer = ((List<?>) workspace.get("messages")).stream()
                .filter(value -> value instanceof Map<?, ?> item && researchId.equals(item.get("sourceResearchId")))
                .map(value -> (Map<?, ?>) value).findFirst().orElse(null);
        response.put("resultVersion", 1); response.put("capability", "research");
        response.put("materialScope", scope); response.put("artifact", artifact);
        response.put("sources", artifact == null ? List.of() : artifact.get("sources"));
        response.put("sentenceSourceMap", List.of()); response.put("steps", List.of());
        response.put("message", answer == null ? "研究状态已更新。" : answer.get("content"));
        return response;
    }

    private Map<String, Object> reviewFields(Map<String, Object> input, List<String> fields) {
        Map<String, Object> body = new LinkedHashMap<>();
        for (String field : fields) if (input.containsKey(field)) body.put(field, input.get(field));
        return body;
    }

    private void requireOwner(String id, String researchId) {
        Map<String, Object> workspace = tasks.get(id);
        if (!(workspace.get("researchRuns") instanceof List<?> runs)
                || runs.stream().noneMatch(run -> run instanceof Map<?, ?> value && researchId.equals(value.get("researchId")))) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "研究任务不属于当前工作区");
        }
    }

    private void requireMaterials(String id, String researchId) {
        Map<String, Object> workspace = tasks.get(id);
        List<?> papers = (List<?>) workspace.get("paperIds");
        for (Object item : (List<?>) workspace.get("researchRuns")) {
            if (item instanceof Map<?, ?> run && researchId.equals(run.get("researchId"))) {
                if (!(run.get("paperIds") instanceof List<?> scope) || scope.isEmpty() || !papers.containsAll(scope)) {
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "研究材料已变化，请恢复原材料后继续");
                }
                return;
            }
        }
        throw new ResponseStatusException(HttpStatus.NOT_FOUND, "研究任务不属于当前工作区");
    }

    private Map<String, Object> requireSuccess(ResponseEntity<Map<String, Object>> response) {
        if (!response.getStatusCode().is2xxSuccessful()) {
            throw new ResponseStatusException(response.getStatusCode(), "研究服务请求未完成，请重试");
        }
        Map<String, Object> body = response.getBody();
        if (body == null || !"success".equals(body.get("status"))) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "研究服务返回无效结果");
        }
        return body;
    }
}
