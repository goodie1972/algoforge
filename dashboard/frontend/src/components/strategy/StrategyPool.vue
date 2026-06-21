<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useMessage } from 'naive-ui'

const store = useConfigStore()
const message = useMessage()
const saving = ref(false)

interface StrategyMeta {
  id: string
  name: string
  display: string
  file: string
  backup_file: string | null
  default_magic: number
  default_timeframe: string
}

interface PoolEntry {
  enabled: boolean
  magic: number
  timeframe: string
  max_positions: number
  double_first: boolean
}

const allStrategies = ref<StrategyMeta[]>([])
const pool = ref<Record<string, PoolEntry>>({})
const expanded = ref<Set<string>>(new Set())
const loading = ref(true)

const timeframes = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1']

// 策略进出场逻辑 (与交易终端一致)
interface StratLogic {
  desc: string
  long: { title: string; color: string; entry: string[]; exit: string[] }
  short: { title: string; color: string; entry: string[]; exit: string[] }
}

const strategyLogics: Record<string, StratLogic> = {
  m30_rsi_v7: {
    desc: 'M30 RSI+布林带均值回归 (7因子评分≥3)',
    long: {
      title: '做多', color: '#0ecb81',
      entry: ['MA14上升→+1 | 触碰BB下轨→+1', 'RSI<30→+1 | RSI上升→+1', '阈值≥3入场', '位置门禁: 顶部10%禁多', '急跌>1.5%惩罚'],
      exit: ['利润回撤25%止盈 | ATR移动止盈(trail)', 'ATR硬止损(hard)', '趋势感知: 顺势1.5/3.0逆势1.0/2.0'],
    },
    short: {
      title: '做空', color: '#f6465d',
      entry: ['MA14下降→+1 | 触碰BB上轨→+1', 'RSI>65→+1 | RSI下降→+1', 'RSI<20禁空, 20~30扣1分', '位置门禁: 底部10%禁空', '急涨>1.5%惩罚'],
      exit: ['利润回撤25%止盈 | ATR移动止盈(trail)', 'ATR硬止损(hard)', '趋势感知: 顺势1.5/3.0逆势1.0/2.0'],
    },
  },
  m30_stoch_T6V1: {
    desc: 'M30 Stoch 均值回归 (ADX<30才入场)',
    long: {
      title: '做多', color: '#0ecb81',
      entry: ['ADX<30 + BB宽度≤1.0', 'K<20 + K金叉D + close<EMA21', '全震荡市入场，不追趋势'],
      exit: ['Stoch反向交叉+close≥EMA21出场', 'misalign检测: BB中轨方向≠K方向提前出', 'ATR硬止损 1.0×ATR'],
    },
    short: {
      title: '做空', color: '#f6465d',
      entry: ['ADX<30 + BB宽度≤1.0', 'K>80 + K死叉D + close>EMA21'],
      exit: ['Stoch反向交叉+close≤EMA21出场', 'misalign检测提前出', 'ATR硬止损 1.0×ATR'],
    },
  },
  m30_stoch_T6V8: {
    desc: 'M30 Stoch 震荡+趋势双模 (ADX<30震荡/≥30趋势)',
    long: {
      title: '做多', color: '#0ecb81',
      entry: ['震荡(ADX<30+BB≤1.0): K<20+金叉+close<EMA21', '趋势(ADX≥30): DI+>DI-+10 + close>EMA21 + 金叉', '趋势顺势单，震荡逆势接飞刀'],
      exit: ['震荡: Stoch反向交叉出场', '趋势: 从峰值回撤2.0ATR止盈/TP4.0ATR', '趋势: ADX<20衰减出/DI反转出', '硬止损: 震荡1.0ATR/趋势2.0ATR'],
    },
    short: {
      title: '做空', color: '#f6465d',
      entry: ['震荡(ADX<30+BB≤1.0): K>80+死叉+close>EMA21', '趋势(ADX≥30): DI->DI+ +10 + close<EMA21 + 死叉'],
      exit: ['震荡: Stoch反向交叉出场', '趋势: 从最低点回撤2.0ATR止盈/TP4.0ATR', '趋势: ADX<20衰减出/DI反转出'],
    },
  },
  rsi_grading_m30: {
    desc: 'M30 RSI分级评分+MA14+BB (阈值2宽止损)',
    long: {
      title: '做多', color: '#0ecb81',
      entry: ['RSI分级: <20→+2 / 20~30→+1', 'MA14上升→+1 | 触碰BB下轨→+1', '阈值≥2入场, 无RSI方向因子', '回测: 27笔$44 PF=1.67'],
      exit: ['从最高点回撤2.0×ATR止盈(trail)', '亏损3.0×ATR硬止损(hard)'],
    },
    short: {
      title: '做空', color: '#f6465d',
      entry: ['RSI分级: >70→+2 / 65~70→+1', 'MA14下降→+1 | 触碰BB上轨→+1', 'RSI<20禁空, 20~30扣1分'],
      exit: ['从最低点反弹2.0×ATR止盈(trail)', '亏损3.0×ATR硬止损(hard)'],
    },
  },
  h1_v6_hybrid_v6: {
    desc: 'H1 多因子评分 V6 混合 (已下架)',
    long: {
      title: '做多', color: '#0ecb81',
      entry: ['8因子 ≥4入场(逆势≥5)', 'SMA200上+KDJ超卖+BB下轨+KC下轨', 'MACD底背离+RSI<30+低波动'],
      exit: ['利润回撤25%止盈 | ATR移动止盈', 'ATR硬止损 | 趋势感知乘数'],
    },
    short: {
      title: '做空', color: '#f6465d',
      entry: ['5因子 ≥3入场(逆势≥4)', '仅close≤SMA200评分 | KDJ超买+KC上轨', 'MACD顶背离+RSI>70'],
      exit: ['利润回撤25%止盈 | ATR移动止盈', 'ATR硬止损'],
    },
  },
  sanqing_h1_v6: {
    desc: 'H1 EMA9/21 趋势评分系统',
    long: {
      title: '做多', color: '#0ecb81',
      entry: ['6因子 ≥5入场', 'EMA上升趋势+2(金叉+1)', '触碰EMA9反弹+2 | 实体>ATR+1', '高成交量+1 | 吞没形态+2'],
      exit: ['利润回撤25%止盈 | ATR移动止盈', 'ATR硬止损'],
    },
    short: {
      title: '做空', color: '#f6465d',
      entry: ['6因子 ≥5入场', 'EMA下降趋势+2(死叉+1)', '触碰EMA9回落+2 | 实体>ATR+1', '吞没形态+2'],
      exit: ['利润回撤25%止盈 | ATR移动止盈', 'ATR硬止损'],
    },
  },
  gold_autoresearch_h1_v5: {
    desc: 'H1 4因子共识投票',
    long: {
      title: '做多', color: '#0ecb81',
      entry: ['4因子全真入场', '趋势: EMA10>EMA20', '动量: MACD>信号线或Stoch金叉', '波动: ADX>20或ATR上升', '安全: 非(BB上轨+RSI≥70)'],
      exit: ['利润回撤25%止盈 | ATR移动止盈', 'ATR硬止损'],
    },
    short: {
      title: '做空', color: '#f6465d',
      entry: ['4因子全真入场', '趋势: EMA10<EMA20', '动量: MACD<信号线或Stoch死叉', '波动: ADX>20或ATR上升', '安全: RSI>35'],
      exit: ['利润回撤25%止盈 | ATR移动止盈', 'ATR硬止损'],
    },
  },
  mtf_resonance_h1: {
    desc: 'H1+M15 TA-Lib 形态共振',
    long: {
      title: '做多', color: '#0ecb81',
      entry: ['H1+15 双周期形态共振开仓', '双周期同时出现反转形态', '共振方向一致时才入场'],
      exit: ['利润回撤25%止盈 | ATR移动止盈', 'ATR硬止损'],
    },
    short: {
      title: '做空', color: '#f6465d',
      entry: ['H1+M15 双周期形态共振开仓', '双周期同时出现反转形态', '共振方向一致时才入场'],
      exit: ['利润回撤25%止盈 | ATR移动止盈', 'ATR硬止损'],
    },
  },
}

// 策略颜色映射 (按 backup_name)
const strategyColors: Record<string, string> = {
  m30_rsi_v7: '#f0a020',
  m30_stoch_T6V1: '#20c080',
  m30_stoch_T6V8: '#2080f0',
  rsi_grading_m30: '#e040a0',
  h1_v6_hybrid_v6: '#808080',
  sanqing_h1_v6: '#9220f0',
  gold_autoresearch_h1_v5: '#20c080',
  mtf_resonance_h1: '#2080f0',
  H1_bakome_backup: '#808080',
  H1_xaubot_backup: '#808080',
}

// 已启用策略
const enabledCount = computed(() =>
  Object.values(pool.value).filter(p => p.enabled).length
)

onMounted(async () => {
  let fetched: StrategyMeta[] = []
  try {
    const res = await fetch('/api/strategies/available')
    const data = await res.json()
    fetched = data.strategies || []
  } catch (e) {
    console.error('获取策略清单失败', e)
  }

  await store.fetch()
  const existing = store.items.strategy_pool || {}

  const merged: Record<string, PoolEntry> = {}
  for (const meta of fetched) {
    const curr = (existing as any)[meta.id]
    merged[meta.id] = {
      enabled: curr?.enabled !== undefined ? curr.enabled : false,
      magic: curr?.magic || meta.default_magic,
      timeframe: curr?.timeframe || meta.default_timeframe,
      max_positions: curr?.max_positions ?? 1,
      double_first: curr?.double_first ?? false,
    }
  }
  pool.value = merged
  allStrategies.value = fetched
  loading.value = false
})

function toggleStrategy(id: string) {
  if (pool.value[id]) {
    pool.value[id].enabled = !pool.value[id].enabled
  }
}

function toggleExpand(id: string) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
  expanded.value = new Set(expanded.value)
}

function getLogic(name: string): StratLogic | null {
  return strategyLogics[name] || null
}

function getColor(name: string): string {
  return strategyColors[name] || '#808080'
}

async function save() {
  saving.value = true
  try {
    // 只传 enabled=true 的到 runtime_config
    const payload: Record<string, any> = {}
    for (const [id, cfg] of Object.entries(pool.value)) {
      payload[id] = {
        enabled: cfg.enabled,
        magic: cfg.magic,
        timeframe: cfg.timeframe,
        max_positions: cfg.enabled ? cfg.max_positions : 0,
        double_first: cfg.double_first,
      }
    }
    await store.updateStrategyPool(payload)
    message.success('策略配置已保存，引擎将在下个 tick 生效')
  } catch (e: any) {
    message.error(e?.message || '保存失败')
  }
  saving.value = false
}
</script>

<template>
  <n-space vertical size="medium">
    <n-alert type="info" :bordered="false" closable>
      共 {{ allStrategies.length }} 个策略，已启用 {{ enabledCount }} 个。
      左侧开关控制是否进入实盘交易。展开 > 查看完整进出场逻辑。
    </n-alert>

    <n-spin :show="loading">
      <n-empty v-if="!loading && !allStrategies.length" description="未发现可交易策略" />

      <n-card v-for="meta in allStrategies" :key="meta.id" size="small" :bordered="true"
        :style="{
          opacity: pool[meta.id]?.enabled ? 1 : 0.55,
          borderLeft: `4px solid ${getColor(meta.name)}`,
        }">

        <!-- 顶栏: 开关 + 名称 + 标签 + Magic + TF -->
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <n-switch :value="pool[meta.id]?.enabled"
              @update:value="toggleStrategy(meta.id)" size="small" />
            <n-text strong style="font-size: 14px;">{{ meta.display }}</n-text>
            <n-tag size="tiny" :bordered="false"
              :color="{ color: getColor(meta.name) }" text-color="#fff">
              {{ meta.name }}
            </n-tag>
            <n-tag v-if="meta.backup_file" size="tiny" :bordered="false" type="info">
              {{ meta.backup_file }}
            </n-tag>
          </div>

          <div style="display: flex; align-items: center; gap: 12px;">
            <n-space size="small" align="center">
              <n-text depth="3" style="font-size: 11px;">Magic</n-text>
              <n-input-number v-model:value="pool[meta.id].magic" size="tiny"
                :min="100000" :max="999999"
                @click.stop style="width: 90px;" />
            </n-space>
            <n-select v-model:value="pool[meta.id].timeframe"
              :options="timeframes.map(t => ({ label: t, value: t }))"
              size="tiny" style="width: 65px;" @click.stop />
            <n-button text size="tiny" style="font-size: 16px; width: 24px;"
              @click.stop="toggleExpand(meta.id)">
              {{ expanded.has(meta.id) ? '▼' : '▶' }}
            </n-button>
          </div>
        </div>

        <!-- 持仓参数 (展开后显示) -->
        <div v-if="expanded.has(meta.id)" style="margin-top: 6px;">
          <div style="display: flex; gap: 16px; align-items: center; margin-bottom: 8px;">
            <n-space align="center" size="small">
              <n-text depth="3" style="font-size: 11px;">最大持仓</n-text>
              <n-input-number v-model:value="pool[meta.id].max_positions"
                size="tiny" :min="1" :max="5" style="width: 60px;" @click.stop />
            </n-space>
            <n-space align="center" size="small">
              <n-text depth="3" style="font-size: 11px;">双倍首单</n-text>
              <n-switch v-model:value="pool[meta.id].double_first" size="small" @click.stop />
            </n-space>
          </div>

          <!-- 进出场逻辑 -->
          <template v-if="getLogic(meta.name)">
            <n-text depth="2" style="font-size: 12px; display: block; margin-bottom: 6px;">
              {{ getLogic(meta.name)!.desc }}
            </n-text>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
              <!-- 做空 -->
              <div style="background: #1a1a2e; border-radius: 4px; padding: 6px 8px; border-left: 3px solid #f6465d;">
                <div style="font-weight:700; color:#f6465d; font-size:12px; margin-bottom:4px;">▼ 做空</div>
                <div style="font-size:10px; color:#8b8f97; margin-bottom:2px;">开仓:</div>
                <div v-for="(l, li) in getLogic(meta.name)!.short.entry" :key="'se'+li"
                  style="font-size:10px; color:#ccc; padding:1px 0;">· {{ l }}</div>
                <div style="font-size:10px; color:#8b8f97; margin:4px 0 2px;">平仓:</div>
                <div v-for="(l, li) in getLogic(meta.name)!.short.exit" :key="'sx'+li"
                  style="font-size:10px; color:#999; padding:1px 0;">· {{ l }}</div>
              </div>
              <!-- 做多 -->
              <div style="background: #1a1a2e; border-radius: 4px; padding: 6px 8px; border-left: 3px solid #0ecb81;">
                <div style="font-weight:700; color:#0ecb81; font-size:12px; margin-bottom:4px;">▲ 做多</div>
                <div style="font-size:10px; color:#8b8f97; margin-bottom:2px;">开仓:</div>
                <div v-for="(l, li) in getLogic(meta.name)!.long.entry" :key="'le'+li"
                  style="font-size:10px; color:#ccc; padding:1px 0;">· {{ l }}</div>
                <div style="font-size:10px; color:#8b8f97; margin:4px 0 2px;">平仓:</div>
                <div v-for="(l, li) in getLogic(meta.name)!.long.exit" :key="'lx'+li"
                  style="font-size:10px; color:#999; padding:1px 0;">· {{ l }}</div>
              </div>
            </div>
          </template>
          <div v-else style="font-size:11px; color:#8b8f97; padding:4px 0;">暂无详细策略说明</div>
        </div>
      </n-card>

      <n-button type="primary" :loading="saving" @click="save" block size="large"
        :disabled="loading">
        保存策略配置
      </n-button>
    </n-spin>
  </n-space>
</template>
