from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.dependencies import require_menu_permission
from app.models import User

from .catalog import PrepareRequest, VersionCatalogService
from .config import EnvironmentError, load_settings
from .service import EnvironmentPreparationService
from .state import EnvironmentLock
from .war_deployment import DeployWarRequest, WarDeploymentService
from .version_switch import SwitchVersionRequest, VersionSwitchService

router = APIRouter(prefix="/contrack-environments", tags=["contrack-environments"],
                   dependencies=[Depends(require_menu_permission("contrack_environments"))])


def get_service():
    try:
        return EnvironmentPreparationService(load_settings())
    except EnvironmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def call(operation):
    try:
        return operation()
    except EnvironmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Environment storage is unavailable; check server permissions") from exc


@router.get("/catalog")
def list_available_versions(service: EnvironmentPreparationService = Depends(get_service)):
    if not service.settings.enabled:
        return {"enabled": False, "operation_mode": service.settings.operation_mode,
                "busy": False, "versions": [], "wars": [], "databases": [], "repositories": [],
                "message": "An administrator must configure and enable the Linux environment manager."}
    if service.settings.operation_mode == "switch_version":
        return call(lambda: {"enabled": True, "operation_mode": "switch_version",
                             "busy": EnvironmentLock.busy(service.settings.path("lock")),
                             **VersionSwitchService(service.settings).catalog()})
    if service.settings.operation_mode == "deploy_war":
        return call(lambda: {"enabled": True, "operation_mode": "deploy_war",
                             "busy": EnvironmentLock.busy(service.settings.path("lock")),
                             "wars": WarDeploymentService(service.settings).list_wars(),
                             "versions": [], "databases": [], "repositories": []})
    return call(lambda: {"enabled": True, "busy": EnvironmentLock.busy(service.settings.path("lock")),
                         "operation_mode": "prepare_environment",
                         **VersionCatalogService(service.settings).list_available_contrack_versions()})


@router.get("/current")
def get_current_environment(service: EnvironmentPreparationService = Depends(get_service)):
    return call(lambda: {"environment": service.runtime.get_current_environment() if service.settings.enabled else None,
                         "busy": EnvironmentLock.busy(service.settings.path("lock")) if service.settings.enabled else False})


@router.get("/runs")
def list_runs(limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
              service: EnvironmentPreparationService = Depends(get_service)):
    return call(lambda: service.history.list(limit, offset) if service.settings.enabled else
                {"items": [], "total": 0, "limit": limit, "offset": offset})


@router.get("/runs/{run_id}")
def get_run(run_id: str, service: EnvironmentPreparationService = Depends(get_service)):
    def operation():
        service._enabled()
        return service.history.get(run_id)
    return call(operation)


@router.post("/validate")
def validate_selection(payload: PrepareRequest, service: EnvironmentPreparationService = Depends(get_service)):
    return call(lambda: service.validate(payload))


@router.post("/prepare", status_code=202)
def prepare_environment(payload: PrepareRequest, background_tasks: BackgroundTasks,
                        actor: User = Depends(require_menu_permission("contrack_environments")),
                        service: EnvironmentPreparationService = Depends(get_service)):
    state, recipe, lock = call(lambda: service.begin(payload, actor.username))
    background_tasks.add_task(service.execute, state.copy(), recipe, lock)
    return state


@router.post("/wars/validate")
def validate_war(payload: DeployWarRequest, service: EnvironmentPreparationService = Depends(get_service)):
    return call(lambda: WarDeploymentService(service.settings).validate(payload))


@router.post("/wars/deploy", status_code=202)
def deploy_war(payload: DeployWarRequest, background_tasks: BackgroundTasks,
               actor: User = Depends(require_menu_permission("contrack_environments")),
               service: EnvironmentPreparationService = Depends(get_service)):
    deployment = WarDeploymentService(service.settings)
    state, source, lock = call(lambda: deployment.begin(payload, actor.username))
    background_tasks.add_task(deployment.execute, state.copy(), source, lock)
    return state


@router.post("/switch/validate")
def validate_switch(payload: SwitchVersionRequest, service: EnvironmentPreparationService = Depends(get_service)):
    return call(lambda: VersionSwitchService(service.settings).validate(payload))


@router.post("/switch", status_code=202)
def switch_version(payload: SwitchVersionRequest, background_tasks: BackgroundTasks,
                   actor: User = Depends(require_menu_permission("contrack_environments")),
                   service: EnvironmentPreparationService = Depends(get_service)):
    switch = VersionSwitchService(service.settings)
    state, lock = call(lambda: switch.begin(payload, actor.username))
    background_tasks.add_task(switch.execute, state.copy(), lock)
    return state
