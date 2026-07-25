<script setup lang="ts">
import { Type, Square, Circle, Minus, Image as ImageIcon, BarChart3, Table, FileImage, Trash2, ArrowUpToLine, ArrowUp, ArrowDown, ArrowDownToLine, ZoomIn, ZoomOut, Maximize, MoreHorizontal } from "lucide-vue-next";

defineProps<{ hasSelection: boolean; selectionType: "image" | "other" | "" }>();
const emit = defineEmits<{ action: [id: string] }>();

function fire(id: string, event: Event) {
  emit("action", id);
  const details = (event.currentTarget as HTMLElement).closest("details");
  details?.removeAttribute("open");
}
</script>

<template>
  <div class="ppt-tool-row" role="toolbar" aria-label="幻灯片对象工具">
    <button type="button" class="ppt-tool-btn" @click="fire('add-text', $event)">
      <Type class="ppt-tool-ico" /> 文本
    </button>

    <details class="ppt-more">
      <summary class="ppt-tool-btn" aria-label="形状"> <Square class="ppt-tool-ico" /> 形状 </summary>
      <div class="ppt-pop absolute z-40 mt-1 w-36 p-1">
        <button type="button" class="ppt-menu-item" @click="fire('add-rect', $event)"> <Square class="ppt-menu-ico" /> 矩形 </button>
        <button type="button" class="ppt-menu-item" @click="fire('add-ellipse', $event)"> <Circle class="ppt-menu-ico" /> 椭圆 </button>
      </div>
    </details>

    <button type="button" class="ppt-tool-btn" @click="fire('add-line', $event)">
      <Minus class="ppt-tool-ico" /> 线条
    </button>

    <button type="button" class="ppt-tool-btn" @click="fire('add-image', $event)">
      <ImageIcon class="ppt-tool-ico" /> 图片
    </button>

    <details class="ppt-more">
      <summary class="ppt-tool-btn" aria-label="图表"> <BarChart3 class="ppt-tool-ico" /> 图表 </summary>
      <div class="ppt-pop absolute z-40 mt-1 w-40 p-1">
        <button type="button" class="ppt-menu-item" @click="fire('add-chart', $event)"> <BarChart3 class="ppt-menu-ico" /> 新建图表 </button>
        <button type="button" class="ppt-menu-item" @click="fire('import-chart', $event)"> 导入图表数据 </button>
      </div>
    </details>

    <details class="ppt-more">
      <summary class="ppt-tool-btn" aria-label="表格"> <Table class="ppt-tool-ico" /> 表格 </summary>
      <div class="ppt-pop absolute z-40 mt-1 w-40 p-1">
        <button type="button" class="ppt-menu-item" @click="fire('add-table', $event)"> <Table class="ppt-menu-ico" /> 新建表格 </button>
        <button type="button" class="ppt-menu-item" @click="fire('import-table', $event)"> 导入表格数据 </button>
      </div>
    </details>

    <span class="ppt-tool-sep" />

    <details class="ppt-more">
      <summary class="ppt-tool-btn" :disabled="!hasSelection" aria-label="排列与层级"> 排列 </summary>
      <div class="ppt-pop absolute z-40 mt-1 w-40 p-1">
        <button type="button" class="ppt-menu-item" :disabled="!hasSelection" @click="fire('arrange-top', $event)"> <ArrowUpToLine class="ppt-menu-ico" /> 置于顶层 </button>
        <button type="button" class="ppt-menu-item" :disabled="!hasSelection" @click="fire('arrange-up', $event)"> <ArrowUp class="ppt-menu-ico" /> 上移一层 </button>
        <button type="button" class="ppt-menu-item" :disabled="!hasSelection" @click="fire('arrange-down', $event)"> <ArrowDown class="ppt-menu-ico" /> 下移一层 </button>
        <button type="button" class="ppt-menu-item" :disabled="!hasSelection" @click="fire('arrange-bottom', $event)"> <ArrowDownToLine class="ppt-menu-ico" /> 置于底层 </button>
      </div>
    </details>

    <details class="ppt-more">
      <summary class="ppt-tool-btn" aria-label="更多工具"> <MoreHorizontal class="ppt-tool-ico" /> 更多 </summary>
      <div class="ppt-pop absolute right-0 z-40 mt-1 w-44 p-1">
        <button type="button" class="ppt-menu-item" @click="fire('extract-images', $event)"> <FileImage class="ppt-menu-ico" /> 文档图片 </button>
        <template v-if="selectionType === 'image'">
          <button type="button" class="ppt-menu-item" @click="fire('fit-contain', $event)"> 适应 </button>
          <button type="button" class="ppt-menu-item" @click="fire('fit-cover', $event)"> 填充 </button>
          <button type="button" class="ppt-menu-item" @click="fire('crop', $event)"> 裁切 </button>
        </template>
        <button type="button" class="ppt-menu-item" :disabled="!hasSelection" @click="fire('delete', $event)"> <Trash2 class="ppt-menu-ico" /> 删除 </button>
        <div class="ppt-tool-sep my-1" />
        <button type="button" class="ppt-menu-item" @click="fire('zoom-in', $event)"> <ZoomIn class="ppt-menu-ico" /> 放大 </button>
        <button type="button" class="ppt-menu-item" @click="fire('zoom-out', $event)"> <ZoomOut class="ppt-menu-ico" /> 缩小 </button>
        <button type="button" class="ppt-menu-item" @click="fire('zoom-reset', $event)"> <Maximize class="ppt-menu-ico" /> 重置缩放 </button>
      </div>
    </details>
  </div>
</template>
