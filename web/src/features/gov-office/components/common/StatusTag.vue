<script setup lang="ts">
import type { Tone } from "../../types";

withDefaults(defineProps<{ tone?: Tone | "outline"; label: string }>(), { tone: "neutral" });
</script>

<template>
  <span class="gov-tag" :class="`gov-tag--${tone}`">{{ label }}</span>
</template>
