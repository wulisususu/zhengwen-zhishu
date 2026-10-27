<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import GovLayout from "../components/layout/GovLayout.vue";
import GovPageHeader from "../components/layout/GovPageHeader.vue";

const MODULES: Record<string, { title: string; goal: string; items: string[]; dependency: string }> = {
  library: {
    title: "政策库",
    goal: "让每一条依据都可追溯、可核验有效性。",
    items: ["政策元数据：文号、发布机关、适用地区、发布 / 生效 / 失效日期", "按“第X条 / 一、/（一）”切分为条款，作为最小引用单元", "状态管理：现行有效、已废止、已被替代、待核实", "废止与替代关系；问答与审校默认排除已废止条款"],
    dependency: "依赖后端政策与条款数据表、入库与切分接口。",
  },
  "audit-log": {
    title: "审计日志",
    goal: "检索、生成、审校、审核、导出全过程可追踪。",
    items: ["记录依据快照、检索结果、模型与版本、操作人", "按文稿、人员、操作类型、时间筛选", "导出操作单独留痕", "只读，不可修改或删除"],
    dependency: "依赖后端审计表；所有业务写操作需统一落库。",
  },
};

const route = useRoute();
const info = computed(() => MODULES[route.meta.module as string] ?? MODULES.library);
</script>

<template>
  <GovLayout>
    <GovPageHeader :title="info.title" subtitle="规划中的模块，本阶段未实现">
      <template #meta><span class="gov-tag gov-tag--neutral">待开发</span></template>
    </GovPageHeader>
    <div class="gov-planned">
      <section class="gov-card gov-planned__card">
        <p class="gov-planned__goal">{{ info.goal }}</p>
        <ul class="gov-planned__items">
          <li v-for="item in info.items" :key="item">{{ item }}</li>
        </ul>
        <div class="gov-banner gov-banner--info">{{ info.dependency }}</div>
      </section>
    </div>
  </GovLayout>
</template>

<style scoped>
.gov-planned { flex: 1 1 auto; overflow-y: auto; padding: 24px; }
.gov-planned__card { max-width: 760px; padding: 24px; display: flex; flex-direction: column; gap: 14px; }
.gov-planned__goal { margin: 0; font-size: 15px; color: var(--gov-text-1); }
.gov-planned__items { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; font-size: 14px; line-height: 22px; color: var(--gov-text-2); }
</style>
