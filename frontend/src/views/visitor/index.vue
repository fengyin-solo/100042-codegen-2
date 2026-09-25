<template>
  <section class="page" data-module="visitor">
    <header class="page-head">
      <div>
        <h2>访客与门禁通行</h2>
        <p class="page-desc">
          门岗登记访客、按到访区域发放通行证；受控区域须对应区域负责人陪同并审批，离场核销后通行证立即作废。
        </p>
      </div>
      <div class="page-actions">
        <label class="role-box">
          <span>当前身份</span>
          <select v-model="operator" @change="notice = ''">
            <option v-for="person in staff" :key="person.name" :value="person.name">
              {{ person.name }}（{{ person.role_label }}<template v-if="person.areas.length">·{{ person.areas.join('、') }}</template>）
            </option>
          </select>
        </label>
        <button class="btn primary" type="button" @click="openRegister">门岗登记发证</button>
        <button class="btn" type="button" @click="exportRows">导出访客清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.tone">{{ item.value }}</strong>
      </article>
    </div>

    <div class="panel">
      <h3 class="panel-title">门岗核验</h3>
      <form class="filter-bar" @submit.prevent="runCheck">
        <label class="filter-item">
          <span>通行证号</span>
          <input v-model="checkForm.passNo" placeholder="如 PASS-0001" />
        </label>
        <label class="filter-item">
          <span>当前进入区域</span>
          <select v-model="checkForm.area">
            <option value="" disabled>选择区域</option>
            <option v-for="area in areas" :key="area.name" :value="area.name">
              {{ area.name }}{{ area.restricted ? '（受控）' : '' }}
            </option>
          </select>
        </label>
        <button class="btn primary" type="submit">刷证核验</button>
      </form>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键词</span>
        <input v-model="filters.keyword" placeholder="访客姓名 / 证件号 / 通行证号" />
      </label>
      <label class="filter-item">
        <span>通行证状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in passStatuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>到访区域</span>
        <select v-model="filters.area">
          <option value="">全部</option>
          <option v-for="area in areas" :key="area.name" :value="area.name">{{ area.name }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['通行证号'] }}</td>
          <td>{{ row['访客姓名'] }}</td>
          <td>{{ row['证件类型'] }}</td>
          <td>{{ maskedId(row['证件号码']) }}</td>
          <td>{{ row['到访单位'] }}</td>
          <td>{{ row['到访事由'] }}</td>
          <td>
            <span v-for="name in row['到访区域']" :key="name" class="area-tag" :class="{ restricted: isRestricted(name) }">
              {{ name }}
            </span>
          </td>
          <td>{{ row['陪同人'] || '—' }}</td>
          <td>{{ row['登记人'] }}<br /><small>{{ row['登记时间'] }}</small></td>
          <td :class="statusTone(row['通行状态'])">
            <strong>{{ row['通行状态'] }}</strong><br /><small>（{{ row['在厂状态'] }}）</small>
          </td>
          <td>{{ row['审批人'] || '—' }}<small v-if="row['审批意见']"><br />{{ row['审批意见'] }}</small></td>
          <td>{{ row['离场时间'] || '—' }}<small v-if="row['核销人']"><br />{{ row['核销人'] }}</small></td>
          <td class="row-actions">
            <button
              v-if="canApprove(row) && managesRow(row)"
              class="link"
              type="button"
              @click="runAction('审批通过', row)"
            >审批通过</button>
            <button
              v-if="canApprove(row) && managesRow(row)"
              class="link reject"
              type="button"
              @click="openReject(row)"
            >审批驳回</button>
            <button
              v-if="canRevoke(row)"
              class="link"
              type="button"
              @click="runAction('离场核销', row)"
            >离场核销</button>
            <span v-if="!hasAction(row)" class="muted-text">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无访客登记记录，可先在门岗登记发证</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条访客与通行证记录（刷新页面后状态与名单保持一致）</span>
    </footer>

    <!-- 登记发证弹窗 -->
    <div v-if="registerOpen" class="modal-mask" @click.self="registerOpen = false">
      <div class="modal">
        <h3>门岗登记 · 发放通行证</h3>
        <p class="modal-tip">
          登记人：{{ operator }}（{{ currentStaff?.role_label }}）。普通区域当场发证；
          勾选受控区域时须由覆盖该区域的负责人陪同，并转其审批。
        </p>
        <div class="form-grid">
          <label v-for="field in textFields" :key="field" class="form-item">
            <span>{{ field }}<em>*</em></span>
            <input v-model="registerForm[field]" :placeholder="`请输入${field}`" />
          </label>
          <label class="form-item">
            <span>证件类型<em>*</em></span>
            <select v-model="registerForm['证件类型']">
              <option value="" disabled>请选择</option>
              <option v-for="type in idTypes" :key="type" :value="type">{{ type }}</option>
            </select>
          </label>
        </div>
        <fieldset class="area-pick">
          <legend>到访区域（可多选）<em>*</em></legend>
          <label v-for="area in areas" :key="area.name" class="area-check">
            <input
              type="checkbox"
              :value="area.name"
              :checked="registerAreas.includes(area.name)"
              @change="toggleArea(area.name)"
            />
            {{ area.name }}<small v-if="area.restricted">（受控）</small>
          </label>
        </fieldset>
        <label class="form-item">
          <span>陪同人<em v-if="hasRestrictedPick">*</em>（仅受控区域需要）</span>
          <select v-model="registerForm['陪同人']">
            <option value="">无 / 暂不指定</option>
            <option v-for="person in managers" :key="person.name" :value="person.name">
              {{ person.name }}（负责：{{ person.areas.join('、') }}）
            </option>
          </select>
        </label>
        <div class="modal-foot">
          <button class="btn" type="button" @click="registerOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitRegister">
            {{ submitting ? '提交中…' : '登记并发放通行证' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 驳回原因弹窗 -->
    <div v-if="rejectTarget" class="modal-mask" @click.self="rejectTarget = null">
      <div class="modal narrow">
        <h3>审批驳回 · 说明原因</h3>
        <p class="modal-tip">
          通行证 {{ rejectTarget['通行证号'] }}（访客 {{ rejectTarget['访客姓名'] }}，
          受控区域：{{ restrictedOf(rejectTarget['到访区域']).join('、') }}）
        </p>
        <label class="form-item">
          <span>驳回原因<em>*</em></span>
          <textarea v-model="rejectReason" rows="3" placeholder="如：未完成入厂安全教育 / 陪同人不覆盖该区域"></textarea>
        </label>
        <div class="modal-foot">
          <button class="btn" type="button" @click="rejectTarget = null">取消</button>
          <button class="btn primary reject-btn" type="button" @click="confirmReject">确认驳回</button>
        </div>
      </div>
    </div>

    <div v-if="notice" class="notice" :class="noticeOk ? 'ok' : 'err'" role="status">{{ notice }}</div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | string[] | null>
type Area = { name: string; restricted: boolean; desc: string }
type Staff = { name: string; role: 'gate' | 'manager'; role_label: string; areas: string[] }

const ENDPOINT = '/api/visitor'
const columns = [
  '通行证号', '访客', '证件类型', '证件号码', '到访单位', '到访事由', '到访区域',
  '陪同人', '登记信息', '通行证状态', '审批信息', '离场信息',
]
const textFields = ['访客姓名', '证件号码', '到访单位', '到访事由']

const rows = ref<Row[]>([])
const total = ref(0)
const areas = ref<Area[]>([])
const staff = ref<Staff[]>([])
const idTypes = ref<string[]>([])
const passStatuses = ref<string[]>([])
const operator = ref('周建国')
const notice = ref('')
const noticeOk = ref(false)
const submitting = ref(false)
const filters = reactive({ keyword: '', status: '', area: '' })
const checkForm = reactive({ passNo: '', area: '' })

const currentStaff = computed(() => staff.value.find((person) => person.name === operator.value))
const managers = computed(() => staff.value.filter((person) => person.role === 'manager'))
const restrictedAreaNames = computed(() => new Set(areas.value.filter((a) => a.restricted).map((a) => a.name)))

const stats = computed(() => {
  const all = rows.value
  return [
    { label: '在访访客', value: all.filter((r) => r['在厂状态'] === '在访').length, tone: '' },
    { label: '待审批', value: all.filter((r) => r['通行状态'] === '待审批').length, tone: 'tone-pending' },
    { label: '今日已发证', value: all.filter((r) => r['通行状态'] === '已发放' || r['通行状态'] === '已核销').length, tone: '' },
    { label: '已驳回/作废', value: all.filter((r) => ['已驳回', '已核销'].includes(String(r['通行状态']))).length, tone: 'tone-bad' },
  ]
})

function isRestricted(name: unknown) {
  return restrictedAreaNames.value.has(String(name))
}

function restrictedOf(names: unknown): string[] {
  return Array.isArray(names) ? (names as string[]).filter((n) => isRestricted(n)) : []
}

function statusTone(status: unknown) {
  if (status === '已发放') return 'tone-ok'
  if (status === '待审批') return 'tone-pending'
  return 'tone-bad'
}

function maskedId(value: unknown) {
  const text = String(value ?? '')
  return text.length > 6 ? `${text.slice(0, 3)}****${text.slice(-4)}` : text
}

function canApprove(row: Row) {
  return currentStaff.value?.role === 'manager' && row['通行状态'] === '待审批'
}

function managesRow(row: Row) {
  const restricted = restrictedOf(row['到访区域'])
  return restricted.every((name) => currentStaff.value?.areas.includes(name))
}

function canRevoke(row: Row) {
  return currentStaff.value?.role === 'gate' && row['通行状态'] === '已发放'
}

function hasAction(row: Row) {
  return (canApprove(row) && managesRow(row)) || canRevoke(row)
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.area = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ---- 登记发证 ----
const registerOpen = ref(false)
const registerForm = reactive<Record<string, string>>({
  访客姓名: '', 证件类型: '', 证件号码: '', 到访单位: '', 到访事由: '', 陪同人: '',
})
const registerAreas = ref<string[]>([])
const hasRestrictedPick = computed(() => registerAreas.value.some((name) => isRestricted(name)))

function openRegister() {
  if (currentStaff.value?.role !== 'gate') {
    showNotice(`当前身份 ${operator.value} 是区域负责人，没有门岗登记权限；请切换到门岗身份`, false)
    return
  }
  Object.keys(registerForm).forEach((key) => (registerForm[key] = ''))
  registerAreas.value = []
  registerOpen.value = true
}

function toggleArea(name: string) {
  const index = registerAreas.value.indexOf(name)
  if (index >= 0) registerAreas.value.splice(index, 1)
  else registerAreas.value.push(name)
}

async function submitRegister() {
  notice.value = ''
  submitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({
        values: { ...registerForm, 到访区域: registerAreas.value, operator: operator.value },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      showNotice(payload.detail || payload.message || '登记未通过', false)
      return
    }
    registerOpen.value = false
    showNotice(payload.message, true)
    await reload()
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '登记请求失败', false)
  } finally {
    submitting.value = false
  }
}

// ---- 审批 / 核销 ----
const rejectTarget = ref<Row | null>(null)
const rejectReason = ref('')

function openReject(row: Row) {
  rejectTarget.value = row
  rejectReason.value = ''
}

async function confirmReject() {
  if (!rejectTarget.value) return
  const target = rejectTarget.value
  rejectTarget.value = null
  await runAction('审批驳回', target, rejectReason.value)
}

async function runAction(action: string, row: Row, remark?: string) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, operator: operator.value }, remark }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      showNotice(payload.detail || payload.message || '操作未生效', false)
      return
    }
    showNotice(payload.message, true)
    await reload()
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '操作请求失败', false)
  }
}

// ---- 门岗核验 ----
async function runCheck() {
  try {
    const response = await request(`${ENDPOINT}/check`, {
      method: 'POST',
      body: JSON.stringify({ values: { 通行证号: checkForm.passNo, 区域: checkForm.area } }),
    })
    const payload = await response.json()
    showNotice(payload.message, Boolean(payload.ok))
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '核验请求失败', false)
  }
}

async function loadMeta() {
  const response = await request(`${ENDPOINT}/meta`)
  if (!response.ok) throw new Error('区域与人员目录读取失败')
  const payload = await response.json()
  areas.value = payload.areas ?? []
  staff.value = payload.staff ?? []
  idTypes.value = payload.id_types ?? []
  passStatuses.value = payload.pass_statuses ?? []
}

async function reload() {
  notice.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.area) query.set('area', filters.area)
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('访客名单读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '访客名单读取失败', false)
  }
}

function showNotice(message: string, ok: boolean) {
  notice.value = message
  noticeOk.value = ok
}

onMounted(async () => {
  await loadMeta()
  await reload()
})
</script>

<style scoped>
.page-actions { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.role-box span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 2px; }
.role-box select { min-width: 240px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; }
.panel-title { margin: 0 0 8px; font-size: 14px; }
.tone-ok { color: #067647; }
.tone-pending { color: #b54708; }
.tone-bad { color: #b42318; }
.area-tag { display: inline-block; background: #eef4ff; color: #1f6feb; border-radius: 4px; padding: 1px 6px; margin: 1px 3px 1px 0; font-size: 12px; }
.area-tag.restricted { background: #fef3f2; color: #b42318; }
.muted-text { color: var(--muted); }
.link.reject, .reject-btn { color: #b42318; }
.modal-mask { position: fixed; inset: 0; background: rgba(16, 24, 40, 0.45); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; width: 640px; max-height: 88vh; overflow: auto; }
.modal.narrow { width: 460px; }
.modal h3 { margin: 0 0 8px; font-size: 16px; }
.modal-tip { color: var(--muted); font-size: 12px; margin: 0 0 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.form-item { display: flex; flex-direction: column; gap: 4px; font-size: 13px; margin-bottom: 10px; }
.form-item em, .area-pick em { color: #b42318; font-style: normal; }
.form-item input, .form-item select, .form-item textarea { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; font: inherit; }
.area-pick { border: 1px dashed var(--border); border-radius: 8px; padding: 8px 10px; margin: 0 0 10px; }
.area-pick legend { font-size: 13px; padding: 0 4px; }
.area-check { display: inline-block; margin: 4px 12px 2px 0; font-size: 13px; }
.area-check small { color: #b42318; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 6px; }
.notice { position: fixed; right: 20px; bottom: 20px; max-width: 460px; padding: 10px 14px; border-radius: 8px; font-size: 13px; z-index: 60; box-shadow: 0 4px 14px rgba(16, 24, 40, 0.18); }
.notice.err { background: #fef3f2; color: #b42318; border: 1px solid #fda29b; }
.notice.ok { background: #ecfdf3; color: #067647; border: 1px solid #6ce9a6; }
small { color: var(--muted); }
</style>
