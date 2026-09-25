"""访客与门禁通行接口：门岗登记访客、按区域发放通行证、离场核销，越权越界一律拦下。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.visitor import VisitorService

router = APIRouter(prefix="/api/visitor", tags=["访客与门禁通行"])

service = VisitorService()

LIST_FIELDS = ["访客编号", "访客姓名", "证件号码", "来访事由", "到访区域", "陪同人员", "通行证号", "通行状态"]
STATUSES = ["已登记", "已授权", "通行中", "已离场"]


@router.get("/meta")
def get_meta() -> dict[str, Any]:
    """区域名录、陪同授权名录与角色权限：前端登记表单与动作按钮以此为准。"""
    return service.meta()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出访客通行清单：返回当前全量数据，含通行证状态。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "visitor", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按访客编号、姓名或证件号码检索"),
    status: str | None = Query(default=None, description="已登记、已授权、通行中、已离场"),
    area: str | None = Query(default=None, description="按到访区域过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按关键字、状态与到访区域过滤访客列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, area=area, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条访客记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"访客记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记访客：证件缺失、重复登记、区域不存在都会被拦下并逐条说明原因。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="访客已登记，待发放通行证", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条访客记录执行区域授权、发放通行证、离场核销；越权越界会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    role = str(payload.values.get("role") or "").strip()
    entry, message = service.run_action(entry_id, action, role)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
