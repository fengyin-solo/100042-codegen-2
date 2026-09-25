<template>
  <section class="page" data-module="visitor">
    <header class="page-head">
      <div>
        <h2>访客与门禁通行</h2>
        <p class="page-desc">门岗登记访客并按到访区域发放通行证，受控区域需区域负责人授权，离场核销后通行证作废。</p>
      </div>
      <div class="page-actions">
        <label class="role-switch">
          <span>当前角色</span>
          <select v-model="role">
            <option v-for="item in meta.roles" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <button class="btn primary" type="button" @click="showCreate = !showCreate">
          {{ showCreate ? '收起登记表单' : '登记访客' }}
        </button>
        <button class="btn" type="button" @click="exportRows">导出访客通行清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="create-panel" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}<em v-if="field.required" class="required-mark">*</em></span>
        <select v-if="field.key === '到访区域'" v-model="createForm[field.key]">
          <option value="">请选择到访区域</option>
          <optgroup label="开放区域（门岗可直接放行）">
            <option v-for="area in meta.open_areas" :key="area" :value="area">{{ area }}</option>
          </optgroup>
          <optgroup label="受控区域（需区域负责人授权）">
            <option v-for="area in meta.controlled_areas" :key="area" :value="area">{{ area }}</option>
          </optgroup>
        </select>
        <select v-else-if="field.key === '陪同人员'" v-model="createForm[field.key]">
          <option value="">无需陪同</option>
          <option v-for="escort in meta.escorts" :key="escort.name" :value="escort.name">
            {{ escort.name }}（可陪同：{{ escort.areas.join('、') }}）
          </option>
        </select>
        <input v-else v-model="createForm[field.key]" :placeholder="`请输入${field.label}`" />
      </label>
      <button class="btn primary" type="submit">提交登记</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="filters.keyword" placeholder="按编号、姓名或证件号检索" />
      </label>
      <label class="filter-item">
        <span>通行状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in meta.statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>到访区域</span>
        <select v-model="filters.area">
          <option value="">全部区域</option>
          <option v-for="area in allAreas" :key="area" :value="area">{{ area }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in rowActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!rowActions(row).length" class="muted-text">已办结</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无访客记录，可先登记访客</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条访客通行记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { fetchJson, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>
type Meta = {
  open_areas: string[]
  controlled_areas: string[]
  escorts: { name: string; areas: string[] }[]
  roles: string[]
  actions: string[]
  statuses: string[]
}

const ENDPOINT = '/api/visitor'
const columns = ['访客编号', '访客姓名', '证件号码', '来访事由', '到访区域', '陪同人员', '通行证号', '通行状态']
const createFields = [
  { key: '访客姓名', label: '访客姓名', required: true },
  { key: '证件号码', label: '证件号码', required: true },
  { key: '来访事由', label: '来访事由', required: false },
  { key: '到访区域', label: '到访区域', required: true },
  { key: '陪同人员', label: '陪同人员', required: false },
]

const session = useSessionStore()
const meta = ref<Meta>({ open_areas: [], controlled_areas: [], escorts: [], roles: [], actions: [], statuses: [] })
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const showCreate = ref(false)
const filters = ref<Record<string, string>>({ keyword: '', status: '', area: '' })
const createForm = reactive<Record<string, string>>({ 访客姓名: '', 证件号码: '', 来访事由: '', 到访区域: '', 陪同人员: '' })

// 角色选择放进会话 Store，页面间切换不丢；动作是否放行以后端校验为准。
const role = computed({
  get: () => session.role,
  set: (value: string) => session.setRole(value),
})

const allAreas = computed(() => [...meta.value.open_areas, ...meta.value.controlled_areas])
const stats = computed(() => [
  { label: '在厂访客', value: rows.value.filter((row) => row.status === '通行中').length },
  { label: '待授权申请', value: rows.value.filter((row) => row.status === '已登记').length },
  { label: '有效通行证', value: rows.value.filter((row) => row['通行状态'] === '有效').length },
])

function isControlled(area: unknown) {
  return meta.value.controlled_areas.includes(String(area ?? ''))
}

function rowActions(row: Row) {
  const status = String(row.status ?? '')
  if (status === '已登记') {
    return isControlled(row['到访区域']) ? ['区域授权', '发放通行证'] : ['发放通行证']
  }
  if (status === '已授权') return ['发放通行证']
  if (status === '通行中') return ['离场核销']
  return []
}

function resetFilters() {
  filters.value = { keyword: '', status: '', area: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message ?? '访客登记被拦下'
      return
    }
    noticeMessage.value = payload.message ?? '访客已登记'
    showCreate.value = false
    for (const field of createFields) createForm[field.key] = ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '访客登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, role: session.role } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message ?? '动作被拦下'
      return
    }
    noticeMessage.value = payload.message ?? '动作已生效'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '访客通行操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters.value)) {
    if (value) query.set(key, value)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('访客列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '访客列表读取失败'
  }
}

onMounted(async () => {
  try {
    meta.value = await fetchJson<Meta>(`${ENDPOINT}/meta`)
  } catch {
    errorMessage.value = '区域与角色配置读取失败，动作校验以后端为准'
  }
  await reload()
})
</script>

<style scoped>
.create-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.role-switch {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}
.required-mark {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}
.notice-text {
  color: #067647;
  font-size: 13px;
  margin: 0 0 8px;
}
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
</style>
