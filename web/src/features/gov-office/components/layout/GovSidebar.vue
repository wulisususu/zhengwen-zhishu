<script setup lang="ts">
import { computed, type Component } from "vue";
import { RouterLink } from "vue-router";
import {
  BookOpen,
  FileCheck,
  FilePen,
  History,
  House,
  ListChecks,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
} from "lucide-vue-next";
import type { Actor, RuntimeStatus } from "../../types";

const props = defineProps<{
  collapsed: boolean;
  runtime: RuntimeStatus | null;
  pendingCount: number;
  actor: Actor | null;
  /** Non-empty only in the demo environment. */
  demoActors: Actor[];
}>();
const emit = defineEmits<{ (e: "toggle"): void; (e: "switch-actor", account: string): void }>();

const ROLE_SHORT = { drafter: "起草人", reviewer: "审核人" } as const;
function roleLabel(a: Actor) {
  return a.roles.map((r) => ROLE_SHORT[r]).join("、") || "无角色";
}
const nextDemoActor = computed(() => props.demoActors.find((a) => a.account !== props.actor?.account));

interface NavItem {
  to: string;
  label: string;
  icon: Component;
  exact?: boolean;
  badge?: "pending";
}

const groups: { label: string; items: NavItem[] }[] = [
  { label: "", items: [{ to: "/gov", label: "工作台首页", icon: House, exact: true }] },
  {
    label: "政策知识",
    items: [
      { to: "/gov/library", label: "政策库", icon: BookOpen },
      { to: "/gov/policy-qa", label: "政策问答", icon: MessageSquare },
    ],
  },
  {
    label: "文稿业务",
    items: [
      { to: "/gov/draft", label: "公文起草", icon: FilePen },
      { to: "/gov/proofread", label: "文稿审校", icon: FileCheck },
      { to: "/gov/summary", label: "提炼总结", icon: ListChecks },
    ],
  },
  {
    label: "管理与合规",
    items: [
      { to: "/gov/review-center", label: "审核中心", icon: ShieldCheck, badge: "pending" },
      { to: "/gov/audit-log", label: "审计日志", icon: History },
    ],
  },
];

const runtimeLabel = computed(() => props.runtime?.label ?? "模型状态读取中…");
const runtimeDetail = computed(() => props.runtime?.detail ?? "");
const runtimeKnown = computed(() => !!props.runtime && props.runtime.modelMode !== "unknown");
</script>

<template>
  <nav class="gov-nav" :class="{ 'is-collapsed': collapsed }" aria-label="工作台导航">
    <div class="gov-nav__brand">
      <span class="gov-nav__mark" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M8 13h8" />
          <path d="M8 17h5" />
        </svg>
      </span>
      <span v-if="!collapsed" class="gov-nav__brand-text">
        <span class="gov-nav__title">政务办公智能体</span>
        <span class="gov-nav__subtitle">公文 · 政策 · 审校</span>
      </span>
    </div>

    <div class="gov-nav__groups">
      <div v-for="group in groups" :key="group.label || 'root'" class="gov-nav__group">
        <div v-if="group.label && !collapsed" class="gov-nav__group-label">{{ group.label }}</div>
        <RouterLink
          v-for="item in group.items"
          :key="item.to"
          :to="item.to"
          class="gov-nav__item"
          :active-class="item.exact ? '' : 'is-active'"
          :exact-active-class="'is-active'"
          :title="collapsed ? item.label : undefined"
          :aria-label="collapsed ? item.label : undefined"
        >
          <component :is="item.icon" :size="18" aria-hidden="true" />
          <span v-if="!collapsed" class="gov-nav__label">{{ item.label }}</span>
          <span v-if="item.badge === 'pending' && pendingCount > 0" class="gov-nav__badge">{{ pendingCount }}</span>
        </RouterLink>
      </div>
    </div>

    <div class="gov-nav__footer">
      <template v-if="demoActors.length && actor">
        <div v-if="!collapsed" class="gov-nav__identity">
          <span class="gov-nav__identity-label">演示身份（演示权限，正式权限由后端控制）</span>
          <div class="gov-nav__identity-seg" role="group" aria-label="切换演示身份">
            <button
              v-for="a in demoActors"
              :key="a.account"
              type="button"
              :class="{ 'is-active': a.account === actor.account }"
              :aria-pressed="a.account === actor.account"
              @click="emit('switch-actor', a.account)"
            >
              {{ roleLabel(a) }}
            </button>
          </div>
          <span class="gov-nav__identity-account">{{ actor.account }} · {{ actor.name }}</span>
        </div>
        <button
          v-else
          type="button"
          class="gov-nav__identity-mini"
          :title="`演示身份：${actor.name}（${actor.account}）。点击切换为${nextDemoActor ? roleLabel(nextDemoActor) : ''}`"
          :aria-label="`当前演示身份 ${actor.name}，点击切换`"
          @click="nextDemoActor && emit('switch-actor', nextDemoActor.account)"
        >
          {{ roleLabel(actor).slice(0, 1) }}
        </button>
      </template>
      <div v-else-if="actor && !collapsed" class="gov-nav__identity-account">{{ actor.name }} · {{ roleLabel(actor) }}</div>
      <div v-if="!collapsed" class="gov-nav__runtime" :title="runtimeDetail">
        <span class="gov-nav__dot" :class="{ 'is-known': runtimeKnown }" aria-hidden="true" />
        <span>{{ runtimeLabel }}</span>
      </div>
      <button
        type="button"
        class="gov-nav__toggle"
        :aria-label="collapsed ? '展开导航' : '收起导航'"
        :title="collapsed ? runtimeLabel : undefined"
        @click="emit('toggle')"
      >
        <PanelLeftOpen v-if="collapsed" :size="18" aria-hidden="true" />
        <PanelLeftClose v-else :size="18" aria-hidden="true" />
        <span v-if="!collapsed">收起导航</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.gov-nav {
  width: var(--gov-nav-width);
  height: 100%;
  background: var(--gov-navy);
  color: var(--gov-nav-text);
  display: flex;
  flex-direction: column;
  padding: 16px 12px 12px;
  overflow-y: auto;
  transition: width 0.15s ease;
}
.gov-nav.is-collapsed { width: var(--gov-nav-width-collapsed); padding: 16px 10px 12px; }
.gov-nav__brand { display: flex; align-items: center; gap: 10px; padding: 0 2px 20px; }
.gov-nav__mark {
  width: 32px; height: 32px; flex: 0 0 32px; border-radius: var(--gov-r-md);
  background: var(--gov-primary); display: inline-flex; align-items: center; justify-content: center;
}
.gov-nav.is-collapsed .gov-nav__brand { justify-content: center; padding-left: 0; padding-right: 0; }
.gov-nav__brand-text { display: flex; flex-direction: column; min-width: 0; }
.gov-nav__title { font-size: 15px; font-weight: 700; color: #fff; letter-spacing: 0.5px; white-space: nowrap; }
.gov-nav__subtitle { font-size: 12px; color: var(--gov-nav-muted); }
.gov-nav__groups { display: flex; flex-direction: column; gap: 4px; flex: 1 1 auto; }
.gov-nav__group { display: flex; flex-direction: column; gap: 2px; }
.gov-nav__group + .gov-nav__group { margin-top: 10px; }
.gov-nav__group-label { font-size: 12px; color: var(--gov-nav-muted); padding: 6px 12px; }
.gov-nav__item {
  position: relative; display: flex; align-items: center; gap: 10px; height: 40px; padding: 0 12px;
  border-radius: var(--gov-r-md); color: var(--gov-nav-text); text-decoration: none; font-size: 14px;
}
.gov-nav.is-collapsed .gov-nav__item { justify-content: center; padding: 0; }
.gov-nav__item:hover { background: rgba(255, 255, 255, 0.07); color: #fff; }
.gov-nav__item.is-active { background: rgba(255, 255, 255, 0.14); color: #fff; font-weight: 500; }
.gov-nav__label { flex: 1 1 auto; white-space: nowrap; }
.gov-nav__badge {
  min-width: 20px; height: 20px; padding: 0 6px; border-radius: 10px; background: var(--gov-red); color: #fff;
  font-size: 12px; display: inline-flex; align-items: center; justify-content: center;
}
.gov-nav.is-collapsed .gov-nav__badge { position: absolute; top: 2px; right: 2px; min-width: 16px; height: 16px; font-size: 11px; padding: 0 4px; }
.gov-nav__footer { border-top: 1px solid rgba(255, 255, 255, 0.12); padding-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.gov-nav__identity { display: flex; flex-direction: column; gap: 6px; padding: 0 4px 4px; }
.gov-nav__identity-label { font-size: 12px; line-height: 17px; color: var(--gov-nav-muted); }
.gov-nav__identity-seg { display: flex; border: 1px solid rgba(255, 255, 255, 0.22); border-radius: var(--gov-r-md); overflow: hidden; }
.gov-nav__identity-seg button { flex: 1 1 0; height: 30px; border: 0; background: transparent; color: var(--gov-nav-text); font-size: 13px; cursor: pointer; }
.gov-nav__identity-seg button.is-active { background: #fff; color: var(--gov-navy); font-weight: 500; }
.gov-nav__identity-account { font-size: 12px; color: var(--gov-nav-text); padding: 0 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gov-nav__identity-mini {
  width: 36px; height: 36px; align-self: center; border-radius: 18px; border: 1px solid rgba(255, 255, 255, 0.3);
  background: rgba(255, 255, 255, 0.08); color: #fff; font-size: 14px; font-weight: 700; cursor: pointer;
}
.gov-nav__runtime { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; line-height: 18px; padding: 0 4px; }
.gov-nav__dot { width: 8px; height: 8px; flex: 0 0 8px; margin-top: 5px; border-radius: 4px; background: var(--gov-nav-muted); }
.gov-nav__dot.is-known { background: #4cc38a; }
.gov-nav__toggle {
  display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 10px; border-radius: var(--gov-r-md);
  border: 0; background: transparent; color: var(--gov-nav-text); font-size: 13px; cursor: pointer;
}
.gov-nav.is-collapsed .gov-nav__toggle { justify-content: center; padding: 0; }
.gov-nav__toggle:hover { background: rgba(255, 255, 255, 0.07); color: #fff; }
</style>
