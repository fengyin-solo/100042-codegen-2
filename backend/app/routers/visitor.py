"""访客与门禁通行接口：访客登记发证、受控区域审批、离场核销与门岗核验。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.visitor import VisitorService

router = APIRouter(prefix="/api/visitor", tags=["访客与门禁"])

service = VisitorService()

COLUMNS = [
    "通行证号", "访客姓名", "证件类型", "证件号码", "到访单位", "到访事由",
    "到访区域", "陪同人", "登记人", "登记时间", "审批人", "审批时间",
    "通行状态", "在厂状态", "离场时间",
]
STATUSES = ["待审批", "已发放", "已驳回", "已核销"]


@router.get("/meta")
def get_meta() -> dict[str, Any]:
    """区域、人员、证件与状态目录：前端表单选项以这里为准。"""
    return service.meta()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按访客姓名、证件号码或通行证号检索"),
    status: str | None = Query(default=None, description="待审批、已发放、已驳回、已核销"),
    area: str | None = Query(default=None, description="按到访区域筛选"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """访客名单（含通行证状态）；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, area=area, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出访客与通行证全量清单。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "visitor", "columns": COLUMNS, "total": total, "items": items}


@router.post("/check", response_model=ActionResult)
def check_access(payload: EntryPayload) -> ActionResult:
    """门岗刷证核验：通行证作废、审批中或进入超出授权区域都会被拦下并说明原因。"""
    entry, message, allowed = service.check_access(payload.values)
    result: dict[str, Any] = {"allowed": allowed}
    return ActionResult(ok=allowed, message=message, entry=entry or result)


@router.post("", response_model=ActionResult)
def register(payload: EntryPayload) -> ActionResult:
    """门岗登记访客并发放通行证；证件缺失、重复登记、越权陪同与受控区域越权都会被拦下。"""
    entry, message = service.register(payload.values)
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """区域负责人审批受控区域申请、门岗办理离场核销；越权动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    operator = str(payload.values.get("operator") or "").strip()
    entry, message = service.run_action(entry_id, action, operator, payload.remark)
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条访客与通行证明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"访客登记 {entry_id} 不存在或已归档")
    return entry
