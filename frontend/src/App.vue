<template>
  <router-view />
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from './stores/auth.js'
const auth = useAuthStore()
onMounted(() => auth.loadSession())
</script>
