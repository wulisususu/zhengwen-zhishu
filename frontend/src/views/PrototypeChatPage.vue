<template>
  <main class="page">
    <header><span class="mark">✺</span><strong>中科信创（南京）</strong></header>
    <div class="layout">
      <aside>
        <button class="new" @click="empty = true">＋　新聊天</button>
        <nav><button class="active">▣　聊天</button><button>▤　文档</button><button>▱　PPT生成</button><button>♙　智能体</button></nav>
        <h3>历史对话</h3>
        <div class="history"><button v-for="item in history" :key="item" :class="{ selected: !empty && selected === item }" @click="open(item)">{{ item }}</button></div>
        <div class="user"><i>◎</i><b>123</b><span>›</span></div>
      </aside>
      <section class="workspace">
        <div class="canvas">
          <template v-if="empty"><h1>有什么可以帮您</h1></template>
          <template v-else>
            <div class="user-msg">{{ selected }}</div>
            <div class="reply">南京的历史底蕴深厚，可以追溯到几千年前。作为中国古代的重要城市之一，南京见证了无数历史事件的变迁。从古代的吴国、东吴、宋、齐、梁、陈到明、清，南京一直是政治、文化和经济的中心。南京的古迹丰富，包括故宫、天坛、中山陵等著名景点，展示了中华文明的辉煌。</div>
            <div class="actions">▣　♧</div>
          </template>
        </div>
        <form class="composer" @submit.prevent="empty = text.trim() ? false : empty">
          <textarea v-model="text" placeholder="请输入你想咨询的问题" />
          <div><button type="button" class="plus">＋</button><button class="pill">写文档</button><button class="pill">知识库</button><span></span><button type="button" class="mic">♩</button><button class="send">➤</button></div>
        </form>
      </section>
    </div>
  </main>
</template>
<script setup>
import { ref } from 'vue'
const history = ['写一篇2000字的南京历史底蕴', '南京的历史底蕴', '低空经济是什么', '具身智能是指什么']
const selected = ref('南京的历史底蕴')
const empty = ref(true)
const text = ref('')
function open (item) { selected.value = item; empty.value = false }
</script>
<style scoped>
*{box-sizing:border-box}.page{height:100dvh;overflow:hidden;background:#eaf3fe;color:#111827;font-family:Arial,"Microsoft YaHei",sans-serif}header{height:76px;background:#fff;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;padding:0 32px;gap:10px;font-size:16px}.mark{color:#1677ff;font-size:24px}.layout{height:calc(100dvh - 76px);display:flex}aside{width:262px;flex:none;background:#fff;border-right:1px solid #dce6f1;padding:14px 20px;display:flex;flex-direction:column}button{border:0;background:transparent;color:#34445f;font:inherit;cursor:pointer}.new,nav button{width:100%;height:40px;text-align:left;padding:0 12px;font-weight:600;border-radius:8px}.new{margin-bottom:8px}nav{display:grid;gap:8px}nav .active{background:#286fff;color:#fff}nav button:nth-child(2){background:#fde3ea}h3{font-size:14px;margin:38px 10px 12px}.history{display:grid;gap:8px;overflow:auto}.history button{text-align:left;padding:11px 10px;border-radius:8px;font-size:13px}.history .selected{background:#fde3ea;box-shadow:0 0 0 1px #63a4ff inset}.user{margin-top:auto;border-top:1px solid #eee;padding:14px 2px;display:flex;gap:12px;align-items:center}.user i{background:#dceaff;border-radius:50%;padding:10px}.user span{margin-left:auto;font-size:26px}.workspace{min-width:0;flex:1;display:flex;flex-direction:column;padding:14px 14px 0}.canvas{flex:1;background:rgba(255,255,255,.78);overflow:auto;padding:42px 8%;position:relative}.canvas h1{text-align:center;margin:0;padding-top:12px;font-size:40px}.user-msg{margin-left:auto;background:#fff;border-radius:8px;padding:10px 16px;width:max-content;max-width:70%;font-size:13px}.reply{background:#fff;margin-top:70px;padding:18px;line-height:2;border-radius:6px;font-size:13px}.actions{font-size:13px;margin-top:8px;color:#667085}.composer{width:min(665px,90%);background:#fff;margin:0 auto;padding:14px 18px;border:2px solid #65b3ff;border-radius:18px 18px 0 0;box-shadow:0 7px 18px #b9d7f866}.composer textarea{width:100%;height:62px;border:0;resize:none;outline:0;font:14px inherit}.composer div{display:flex;gap:8px;align-items:center}.composer div span{flex:1}.plus,.mic,.send{width:36px;height:30px;font-size:22px}.pill{font-size:12px;background:#fdeef2;padding:8px 12px}.send{background:#286fff;color:#fff;border-radius:5px;font-size:18px}@media(max-width:700px){aside{display:none}.workspace{padding:8px}.canvas h1{font-size:28px}.composer{width:100%}}
header{height:64px;padding:0 28px}.layout{height:calc(100dvh - 64px);padding:10px 8px 0}.layout aside{width:232px;margin-left:0;padding:12px 16px;border:1px solid #dce6f1;border-radius:12px}.workspace{min-height:0;padding:0 0 0 10px}.canvas{min-height:0}.composer{flex:none;width:min(1035px,92%);height:132px;margin:0 auto 14px;padding:14px 18px 10px;border-width:1px;border-radius:18px}.composer textarea{height:70px}
</style>
