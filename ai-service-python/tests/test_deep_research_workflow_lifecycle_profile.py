"""New-run activation is server-owned; persisted legacy runs are not migrated."""
from copy import deepcopy
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.facade import ResearchFacade
from services.deep_research.execution_workflow_blueprint import enabled
from services.deep_research.experiment_template import enabled as draft_enabled
from services.deep_research.experiment_repair import enabled as repair_enabled


def test_new_profile_is_consistent_and_does_not_rewrite_legacy_run(tmp_path):
    repo=DeepResearchRepository(tmp_path/'profile.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        first,_=facade.create({'workspaceTaskId':'t','operationKey':'first','question':'Design an experiment',
            'deferStart':True},start_async=False)
        assert first['promptVersion']=='dr-v2.20261029.332'
        assert first['scientificOutlineContractVersion']==1
        assert first['workflowMetadataRowsContractVersion']==2
        assert first['workflowMetadataRepairContractVersion']==34
        assert first['workflowInitializationOutputContractVersion']==1
        assert first['workflowInitializationRepairContractVersion']==2
        assert (first['workflowContractVersion'],first['executionWorkflowContractVersion'])==(5,7)
        probe=deepcopy(first);probe['state']['outputKind']='experiment_design'
        assert enabled(probe) and draft_enabled(probe) and repair_enabled(probe)
        old=deepcopy(first);old.update(runId='legacy',idempotencyKey='legacy',
            promptVersion='dr-v2.20261023.257',workflowContractVersion=4,executionWorkflowContractVersion=6)
        old.pop('experimentPlanningReasoningContractVersion')
        old.pop('scientificOutlineContractVersion')
        old.pop('workflowMetadataRowsContractVersion')
        old.pop('workflowMetadataRepairContractVersion')
        old.pop('workflowInitializationOutputContractVersion')
        old.pop('workflowInitializationRepairContractVersion')
        old.pop('answerPointIntentContractVersion')
        old.pop('scopeExpressionContractVersion')
        old.pop('scopeCompactionContractVersion')
        old.pop('repairCompactionContractVersion')
        old.pop('tableIdentityContextContractVersion')
        old.pop('coverageDiagnosticsContractVersion')
        old.pop('requestCoverageContractVersion')
        old.pop('claimCheckContractVersion')
        old.pop('scopeObservationContractVersion')
        old.pop('scopeExpressionReviewContractVersion')
        old.pop('scopeEvidenceContractVersion')
        old.pop('factualDecisionContractVersion')
        repo.create_run(old);before=repo.require_run('legacy')
        facade.create({'workspaceTaskId':'t','operationKey':'second','question':'Design an experiment',
            'deferStart':True},start_async=False)
        assert repo.require_run('legacy')==before
        legacy=deepcopy(before);legacy['state']['outputKind']='experiment_design'
        assert enabled(legacy)
    finally:facade.shutdown()
