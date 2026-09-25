"""访客与门禁通行业务规则：登记兜底、区域受控、角色权限与通行证生命周期都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "visitor"
REQUIRED_FIELDS = ["访客姓名", "证件号码", "到访区域"]
STATUS_ORDER = ["已登记", "已授权", "通行中", "已离场"]

# 区域名录：开放区域门岗可直接放行；受控区域必须先由区域负责人授权。
OPEN_AREAS = ["办公区", "展厅"]
CONTROLLED_AREAS = ["生产区", "中控室", "危化品区"]
ALL_AREAS = OPEN_AREAS + CONTROLLED_AREAS

# 陪同人员授权名录：姓名 → 允许陪同进入的区域，名录之外一律视为越权陪同。
ESCORTS = {
    "王安全": ["办公区", "展厅", "生产区"],
    "李工艺": ["办公区", "生产区", "中控室"],
    "赵设备": ["办公区", "危化品区"],
}

# 角色与动作权限：门岗管登记发证核销，区域负责人管受控区域授权，互不越权。
ROLES = ["门岗", "区域负责人"]
ACTION_ROLES = {
    "区域授权": ["区域负责人"],
    "发放通行证": ["门岗"],
    "离场核销": ["门岗"],
}
NEGATIVE_STATUSES = ["已离场"]


class VisitorService:
    def meta(self) -> dict[str, Any]:
        """把区域名录、陪同名录与角色权限暴露给前端，保证两边口径一致。"""
        return {
            "open_areas": OPEN_AREAS,
            "controlled_areas": CONTROLLED_AREAS,
            "escorts": [{"name": name, "areas": areas} for name, areas in ESCORTS.items()],
            "roles": ROLES,
            "actions": sorted(ACTION_ROLES),
            "statuses": STATUS_ORDER,
        }

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        area: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("访客编号", ""))
                or keyword in str(row.get("访客姓名", ""))
                or keyword in str(row.get("证件号码", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if area:
            rows = [row for row in rows if row.get("到访区域") == area]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记访客：证件缺失、区域不存在、重复登记都拦下并逐条说明原因。"""
        problems: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            problems.append(f"缺少必填字段：{'、'.join(missing)}（证件缺失不得登记，请补齐后再提交）")

        area = str(values.get("到访区域") or "").strip()
        if area and area not in ALL_AREAS:
            problems.append(f"到访区域「{area}」不在厂区区域名录内，可选：{'、'.join(ALL_AREAS)}")

        id_number = str(values.get("证件号码") or "").strip()
        if id_number:
            for row in store.rows(MODULE):
                if row.get("证件号码") == id_number and row.get("status") not in NEGATIVE_STATUSES:
                    problems.append(
                        f"证件号码 {id_number} 已登记，访客「{row.get('访客姓名')}」"
                        f"（{row.get('访客编号')}）当前状态为「{row.get('status')}」，"
                        "请先离场核销再重新登记，避免重复发证"
                    )
                    break
        if problems:
            return None, problems

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["访客编号"] = f"VISI-{entry['id']:04d}"
        for field in ["访客姓名", "证件号码", "来访事由", "到访区域", "陪同人员"]:
            entry[field] = str(values.get(field) or "").strip()
        entry["通行证号"] = ""
        entry["status"] = STATUS_ORDER[0]
        entry["通行状态"] = "未发放"
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        role: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """通行证动作：先校角色权限，再校状态与区域授权，越权越界都拦下。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"访客记录 {entry_id} 不存在或已归档"
        if action not in ACTION_ROLES:
            return None, f"动作「{action}」不属于访客通行可执行范围"
        allowed = ACTION_ROLES[action]
        if role not in allowed:
            return None, (
                f"当前角色「{role or '未指定'}」无权执行「{action}」，"
                f"该动作仅限{'、'.join(allowed)}操作，门岗与区域负责人权限不同"
            )
        if action == "区域授权":
            return self._authorize_area(entry)
        if action == "发放通行证":
            return self._issue_pass(entry)
        return self._checkout(entry)

    def _authorize_area(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        area = str(entry.get("到访区域", ""))
        if area in OPEN_AREAS:
            return None, f"到访区域「{area}」属开放区域，无需区域授权，门岗可直接发放通行证"
        if entry.get("status") != "已登记":
            return None, f"当前状态「{entry.get('status')}」不允许区域授权，仅「已登记」的访客可申请授权"
        entry["status"] = "已授权"
        return entry, f"区域负责人已授权进入受控区域「{area}」，门岗可发放通行证"

    def _issue_pass(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        status = str(entry.get("status", ""))
        area = str(entry.get("到访区域", ""))
        if status == "通行中":
            return None, f"通行证 {entry.get('通行证号')} 已发放且在有效期内，请勿重复发放"
        if status == "已离场":
            return None, "访客已离场核销，原通行证已作废，如需再次来访请重新登记"
        if area in CONTROLLED_AREAS and status != "已授权":
            return None, (
                f"到访区域「{area}」属受控区域，尚未获得区域负责人授权，"
                "超出授权区域的申请不予发放通行证"
            )
        escort = str(entry.get("陪同人员") or "").strip()
        if escort:
            if escort not in ESCORTS:
                return None, f"陪同人员「{escort}」不在厂区陪同授权名录内，禁止陪同入厂"
            if area not in ESCORTS[escort]:
                return None, (
                    f"陪同人员「{escort}」未获「{area}」陪同授权，属于越权陪同，通行证不予发放"
                )
        entry["通行证号"] = f"PASS-{int(entry.get('id', 0)):04d}"
        entry["status"] = "通行中"
        entry["通行状态"] = "有效"
        return entry, f"通行证 {entry['通行证号']} 已发放，通行范围限「{area}」，超出授权区域将被门禁拦下"

    def _checkout(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        status = str(entry.get("status", ""))
        if status == "已离场":
            return None, "该访客已核销离场，通行证已作废，请勿重复核销"
        if status != "通行中":
            return None, f"当前状态「{status}」无有效通行证，无需离场核销"
        entry["status"] = "已离场"
        entry["通行状态"] = "已作废"
        entry["pending"] = False
        return entry, f"访客已离场，通行证 {entry.get('通行证号')} 已作废"
