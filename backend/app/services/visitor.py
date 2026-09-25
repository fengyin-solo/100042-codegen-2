"""访客与门禁通行业务规则。

访客名单与通行证共用一份登记表（单一数据源）：登记即生成通行证、核销即作废，
因此刷新页面后通行证状态与访客名单永远一致。受控区域、陪同授权、门岗/区域负责人
的权限分界都收在本文件里，路由层只负责把规则结果翻译成接口响应。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "visitor"

REQUIRED_FIELDS = ["访客姓名", "证件类型", "证件号码", "到访单位", "到访事由"]
ID_TYPES = ["身份证", "驾驶证", "护照", "港澳台通行证"]

# 受控区域目录：restricted=True 的区域门岗无权直接放行，须区域负责人陪同并审批。
AREAS: list[dict[str, Any]] = [
    {"name": "办公区", "restricted": False, "desc": "行政办公与一般接待"},
    {"name": "参观通道", "restricted": False, "desc": "常规参观路线"},
    {"name": "装卸区", "restricted": False, "desc": "货物装卸与车辆等待"},
    {"name": "中控室", "restricted": True, "desc": "工艺运行集中控制室"},
    {"name": "鼓风机房", "restricted": True, "desc": "曝气鼓风核心设备间"},
    {"name": "加药间", "restricted": True, "desc": "危险化学品药剂存放间"},
    {"name": "污泥脱水车间", "restricted": True, "desc": "污泥脱水与外运作业区"},
]

# 厂区人员目录：决定每个登录身份的角色与可负责/可陪同的受控区域。
STAFF: list[dict[str, Any]] = [
    {"name": "周建国", "role": "gate", "role_label": "门岗", "areas": []},
    {"name": "赵敏", "role": "gate", "role_label": "门岗", "areas": []},
    {"name": "陈志强", "role": "manager", "role_label": "区域负责人", "areas": ["中控室"]},
    {"name": "李卫民", "role": "manager", "role_label": "区域负责人", "areas": ["鼓风机房"]},
    {"name": "孙丽华", "role": "manager", "role_label": "区域负责人", "areas": ["加药间"]},
    {"name": "王海涛", "role": "manager", "role_label": "区域负责人", "areas": ["污泥脱水车间"]},
]

STATUS_PENDING = "待审批"
STATUS_ISSUED = "已发放"
STATUS_REJECTED = "已驳回"
STATUS_REVOKED = "已核销"
PASS_STATUSES = [STATUS_PENDING, STATUS_ISSUED, STATUS_REJECTED, STATUS_REVOKED]

# 在厂状态与通行证状态分开维护：驳回/核销后人并未在厂，审批中则是已登记未放行。
ONSITE_WAITING = "待批"
ONSITE_IN = "在访"
ONSITE_OUT = "已离场"
ONSITE_NEVER = "未进厂"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _find_staff(name: str) -> dict[str, Any] | None:
    return next((person for person in STAFF if person["name"] == name), None)


def _area_names() -> set[str]:
    return {area["name"] for area in AREAS}


def _restricted_of(names: list[str]) -> list[str]:
    return [name for name in names if name in {a["name"] for a in AREAS if a["restricted"]}]


class VisitorService:
    def meta(self) -> dict[str, Any]:
        """返回区域、人员、状态目录：下拉选项以服务端目录为准，避免前端各写一份。"""
        return {"areas": AREAS, "staff": STAFF, "id_types": ID_TYPES, "pass_statuses": PASS_STATUSES}

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
            key = keyword.strip()
            rows = [
                row
                for row in rows
                if key in str(row.get("访客姓名", ""))
                or key in str(row.get("通行证号", ""))
                or key in str(row.get("证件号码", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("通行状态") == status]
        if area:
            rows = [row for row in rows if area in (row.get("到访区域") or [])]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def find_pass(self, pass_no: str) -> dict[str, Any] | None:
        return next((row for row in store.rows(MODULE) if row.get("通行证号") == pass_no), None)

    def register(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """门岗登记访客并发放通行证；任何一项兜底不通过都说明原因，不静默落库。"""
        operator = str(values.get("operator") or values.get("登记人") or "").strip()
        staff = _find_staff(operator)
        if staff is None:
            return None, "未识别门岗身份：只有在岗门岗可以登记访客并发放通行证"
        if staff["role"] != "gate":
            return None, f"{operator}是区域负责人，没有门岗登记权限；访客登记请到门岗办理"

        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        areas = self._parse_areas(values.get("到访区域"))
        if not areas:
            missing.append("到访区域")
        if missing:
            return None, f"缺少必填信息：{'、'.join(missing)}，请补齐后再登记（证件不齐不予发证）"

        unknown = [name for name in areas if name not in _area_names()]
        if unknown:
            return None, f"到访区域「{'、'.join(unknown)}」不在受控区域目录内，请重新选择"

        doc_no = str(values.get("证件号码")).strip()
        if str(values.get("证件类型")).strip() not in ID_TYPES:
            return None, f"证件类型只能是：{'、'.join(ID_TYPES)}"

        # 重复登记兜底：同一证件仍在待批或在访的，直接拦下并指到核销流程。
        duplicate = next(
            (
                row
                for row in store.rows(MODULE)
                if str(row.get("证件号码", "")).strip() == doc_no
                and row.get("在厂状态") in (ONSITE_WAITING, ONSITE_IN)
            ),
            None,
        )
        if duplicate is not None:
            return (
                None,
                f"该证件已登记（通行证 {duplicate.get('通行证号')}，"
                f"状态：{duplicate.get('通行状态')}/{duplicate.get('在厂状态')}），请勿重复登记；"
                "如需重新入场，请先办理离场核销",
            )

        restricted = _restricted_of(areas)
        escort_name = str(values.get("陪同人") or "").strip()
        entry: dict[str, Any] = {}
        if restricted:
            # 受控区域：门岗无权直接发证；先校验陪同授权，再转区域负责人审批。
            if not escort_name:
                return None, f"受控区域（{'、'.join(restricted)}）须由对应区域负责人陪同，请填写陪同人后提交申请"
            escort = _find_staff(escort_name)
            if escort is None or escort["role"] != "manager":
                return None, f"陪同人「{escort_name}」不是区域负责人，无受控区域陪同授权，越权陪同已拦下"
            uncovered = [name for name in restricted if name not in escort["areas"]]
            if uncovered:
                return (
                    None,
                    f"陪同人「{escort_name}」仅负责 {'、'.join(escort['areas']) or '无区域'}，"
                    f"不覆盖受控区域「{'、'.join(uncovered)}」，越权陪同已拦下",
                )
            entry["通行状态"] = STATUS_PENDING
            entry["在厂状态"] = ONSITE_WAITING
            entry["pending"] = True
            entry["abnormal"] = False
        else:
            entry["通行状态"] = STATUS_ISSUED
            entry["在厂状态"] = ONSITE_IN
            entry["pending"] = False
            entry["abnormal"] = False

        rows = store.rows(MODULE)
        entry_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry.update(
            {
                "id": entry_id,
                "status": entry["通行状态"],
                "通行证号": f"PASS-{entry_id:04d}",
                "访客姓名": str(values.get("访客姓名")).strip(),
                "证件类型": str(values.get("证件类型")).strip(),
                "证件号码": doc_no,
                "到访单位": str(values.get("到访单位")).strip(),
                "到访事由": str(values.get("到访事由")).strip(),
                "到访区域": areas,
                "陪同人": escort_name,
                "登记人": operator,
                "登记时间": _now(),
                "审批人": "",
                "审批时间": "",
                "审批意见": "",
                "离场时间": "",
                "核销人": "",
            }
        )
        rows.append(entry)
        if restricted:
            return entry, (
                f"访客已登记，受控区域（{'、'.join(restricted)}）通行证门岗无权直接发放，"
                f"已提交区域负责人 {escort_name} 审批"
            )
        return entry, f"通行证 {entry['通行证号']} 已发放，授权区域：{'、'.join(areas)}"

    def run_action(
        self, entry_id: int, action: str, operator: str, remark: str | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        """审批通过/驳回归区域负责人，离场核销归门岗；越权动作一律拦下并说明原因。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"访客登记 {entry_id} 不存在或已归档"
        staff = _find_staff(operator)
        if staff is None:
            return None, f"未识别操作人员「{operator}」，请从厂区人员目录中选择身份"

        if action in ("审批通过", "审批驳回"):
            if staff["role"] != "manager":
                return None, f"{operator}是门岗，没有受控区域审批权限；审批须由对应区域负责人办理"
            if entry.get("通行状态") != STATUS_PENDING:
                return None, f"通行证当前为「{entry.get('通行状态')}」，只有待审批的申请可以{action}"
            restricted = _restricted_of(entry.get("到访区域") or [])
            uncovered = [name for name in restricted if name not in staff["areas"]]
            if uncovered:
                return (
                    None,
                    f"该申请的受控区域「{'、'.join(uncovered)}」不在您的负责范围"
                    f"（您负责：{'、'.join(staff['areas'])}），越权审批已拦下",
                )
            if action == "审批驳回":
                reason = (remark or "").strip()
                if not reason:
                    return None, "驳回必须填写审批意见并说明原因，申请已保留为待审批"
                entry["通行状态"] = STATUS_REJECTED
                entry["在厂状态"] = ONSITE_NEVER
                entry["审批意见"] = reason
                entry["pending"] = False
                entry["abnormal"] = True
            else:
                entry["通行状态"] = STATUS_ISSUED
                entry["在厂状态"] = ONSITE_IN
                entry["审批意见"] = (remark or "").strip() or "同意发放，按授权区域通行"
                entry["pending"] = False
                entry["abnormal"] = False
            entry["status"] = entry["通行状态"]
            entry["审批人"] = operator
            entry["审批时间"] = _now()
            return entry, f"通行证 {entry['通行证号']} 已{action}，授权区域：{'、'.join(entry['到访区域'])}"

        if action == "离场核销":
            if staff["role"] != "gate":
                return None, f"{operator}是区域负责人，离场核销只能由门岗办理"
            if entry.get("通行状态") != STATUS_ISSUED:
                return (
                    None,
                    f"通行证当前为「{entry.get('通行状态')}」，仅已发放且在访的通行证可以核销",
                )
            entry["通行状态"] = STATUS_REVOKED
            entry["在厂状态"] = ONSITE_OUT
            entry["status"] = STATUS_REVOKED
            entry["pending"] = False
            entry["abnormal"] = False
            entry["离场时间"] = _now()
            entry["核销人"] = operator
            return entry, f"通行证 {entry['通行证号']} 已核销并立即作废"

        return None, f"动作「{action}」不属于访客门禁模块可执行范围"

    def check_access(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        """门岗刷证核验：先看通行证是否有效，再看当前区域是否在授权范围内。"""
        pass_no = str(values.get("通行证号") or "").strip()
        area = str(values.get("区域") or values.get("到访区域") or "").strip()
        if not pass_no:
            return None, "通行证号不能为空，无法核验", False
        if not area:
            return None, "未选择当前到访区域，无法核验授权范围", False
        if area not in _area_names():
            return None, f"区域「{area}」不在受控区域目录内", False

        entry = self.find_pass(pass_no)
        if entry is None:
            return None, f"查无通行证 {pass_no}，请确认号码或先到门岗登记", False

        status = entry.get("通行状态")
        if status == STATUS_REVOKED:
            return entry, f"通行证 {pass_no} 已离场核销并作废，禁止进入「{area}」", False
        if status == STATUS_REJECTED:
            return entry, f"通行证 {pass_no} 的申请已被驳回（{entry.get('审批意见')}），禁止进入「{area}」", False
        if status == STATUS_PENDING:
            return entry, f"通行证 {pass_no} 尚在区域负责人审批中，暂不能进入「{area}」", False

        authorized = entry.get("到访区域") or []
        if area not in authorized:
            return (
                entry,
                f"超出授权区域：通行证 {pass_no} 仅授权 {'、'.join(authorized)}，"
                f"不含「{area}」，本次进入已拦下",
                False,
            )
        return entry, f"通行证 {pass_no} 有效，访客 {entry.get('访客姓名')} 准予进入「{area}」", True

    @staticmethod
    def _parse_areas(raw: Any) -> list[str]:
        """到访区域可能是多选数组，也兼容逗号分隔字符串。"""
        if isinstance(raw, list):
            names = [str(item).strip() for item in raw]
        else:
            names = [item.strip() for item in str(raw or "").replace("，", ",").split(",")]
        return [name for name in names if name]
