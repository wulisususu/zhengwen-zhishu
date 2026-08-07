<template>
  <header class="flex h-16 shrink-0 items-center justify-between border-b border-[#E5E7EB] bg-[rgba(255,255,255,0.82)] px-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)] backdrop-blur-[14px]">
    <button type="button" class="min-w-0 rounded-[14px] px-3 py-2 text-left transition-colors duration-150 hover:bg-[#F8FAFC]" @click="$emit('goHome')">
      <div class="flex items-center gap-2.5">
        <img
          :src="zkxcMark"
          alt="中科信创"
          class="h-[20px] w-[20px] shrink-0 rounded-[4px] object-contain"
        />
        <div class="min-w-0">
          <div v-if="title" class="truncate text-[18px] font-semibold leading-5 tracking-[-0.02em] text-[#111827]">{{ title }}</div>
          <div
            v-if="subtitle"
            :class="title
              ? 'truncate pt-1 text-[12px] font-medium leading-4 text-[#667085]'
              : 'truncate text-[18px] font-semibold leading-5 tracking-[-0.02em] text-[#111827]'"
          >
            {{ subtitle }}
          </div>
        </div>
      </div>
    </button>
    <button
      v-if="showLogout"
      type="button"
      class="rounded-[12px] border border-[#E4E7EC] bg-white px-3.5 py-2 text-[13px] font-medium text-[#475467] shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-all duration-150 hover:border-[#D0D5DD] hover:bg-[#F8FAFC] hover:text-[#111827]"
      @click="logout"
    >
      退出
    </button>
  </header>
</template>

<script setup>
import { useAuthStore } from '../stores/auth.js'
import zkxcMark from '../assets/zkxc-mark.svg'

defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  showLogout: { type: Boolean, default: true },
})

const emit = defineEmits(['goHome', 'logout'])
const auth = useAuthStore()

function logout() {
  auth.clearSession()
  emit('logout')
}
</script>
