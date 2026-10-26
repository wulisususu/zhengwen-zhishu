import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter, RouterView } from 'vue-router';
import { defineComponent } from 'vue';
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
const adapter = vi.hoisted(() => ({ mode: 'http', listPolicies: vi.fn(), searchPolicies: vi.fn(), getCurrentActor: vi.fn(), listDocuments: vi.fn() }));
vi.mock('../../src/api.js', () => ({ default: api }));
vi.mock('../../src/features/gov-office/adapters', () => ({ getGovOfficeAdapter: () => adapter }));
import { govOfficeRoutes } from '../../src/features/gov-office/routes';
let wrapper: VueWrapper | undefined;
beforeEach(() => {
 vi.clearAllMocks(); sessionStorage.clear(); localStorage.setItem('mqw-session', JSON.stringify({token:'real-role-session'}));
 adapter.listPolicies.mockResolvedValue({items:[],total:101}); adapter.searchPolicies.mockResolvedValue({hits:[]});
 adapter.getCurrentActor.mockResolvedValue({roles:['drafter'],account:'drafter'}); adapter.listDocuments.mockResolvedValue([]);
 api.get.mockImplementation((url: string) => Promise.resolve({data:{code:0,data:url==='/gov/actor'?{roles:['drafter']}:url==='/gov/policies/stats'?{total:101,unverified:101}:{items:[],total:101}}}));
});
afterEach(() => { wrapper?.unmount(); wrapper=undefined; vi.unstubAllGlobals(); });
async function open(path: string) {
 const router=createRouter({history:createMemoryHistory(),routes:[...govOfficeRoutes,{path:'/gongwen',component:defineComponent({template:'<div>起草</div>'})}]});
 await router.push(path);await router.isReady();
 wrapper=mount(RouterView,{global:{plugins:[createPinia(),router],stubs:{GovLayout:{template:'<div data-testid="workbench"><slot /></div>'},GovPageHeader:{props:['title'],template:'<h1>{{title}}</h1>'},AppHeader:{template:'<div data-testid="legacy-header" />'}}}});
 await flushPromises();return {router,w:wrapper};
}
it('switches between a dedicated library and the real QA composer inside the workbench',async()=>{
 const {router,w}=await open('/gov/library');
 expect(w.get('h1').text()).toBe('政策库');expect(w.find('.policy-library').exists()).toBe(true);
 expect(w.find('.gov-composer-input').exists()).toBe(false);
 await router.push('/gov/policy-qa');await flushPromises();
 expect(w.get('h1').text()).toBe('政策问答');expect(w.find('.gov-composer-input').exists()).toBe(true);
 expect(w.find('.policy-library').exists()).toBe(false);expect(w.find('[data-testid="legacy-header"]').exists()).toBe(false);
 expect(w.find('main.h-dvh').exists()).toBe(false);expect(w.find('[data-testid="workbench"]').exists()).toBe(true);
 await router.push('/gov/library');await flushPromises();expect(w.find('.policy-library').exists()).toBe(true);
});
it('uses the real authenticated streaming API and passes the complete cited clause into drafting',async()=>{
 const content='第三条 申请条件应同时具备：正常经营；无失信记录；资金用于生产经营。';
 const citation={index:1,citation_id:'clause:7',clause_id:7,policy_title:'办法',clause_no:'第三条',content,status:'待核实',excerpt:{pre:'',hl:'无失信记录',post:''}};
 const answer={status:'answered',sufficiency:'partial',question:'申请条件是什么',conclusion:'须满足三项条件[1]。',citations:[citation],meta:{candidates:1,generated_by:'llm'}};
 const fetcher=vi.fn().mockResolvedValue(new Response('data: '+JSON.stringify({type:'final',data:answer})+'\n\n',{headers:{'Content-Type':'text/event-stream'}}));vi.stubGlobal('fetch',fetcher);
 const {router,w}=await open('/gov/policy-qa');await w.get('.gov-composer-input').setValue('申请条件是什么');await w.get('.gov-send').trigger('click');await flushPromises();
 expect(fetcher).toHaveBeenCalledWith('/api/v1/policy/qa/stream',expect.objectContaining({method:'POST',headers:expect.objectContaining({Authorization:'Bearer real-role-session'})}));
 expect(w.text()).toContain('须满足三项条件');expect(w.text()).toContain('含待核实依据');
 await w.get('.gov-cite-card').trigger('click');
 expect(w.get('[aria-label="政策引用原文"]').classes()).toContain('policy-chat__citation--embedded');
 await w.get('[aria-label="关闭引用原文"]').trigger('click');expect(w.find('[aria-label="政策引用原文"]').exists()).toBe(false);
 await w.findAll('button').find(b=>b.text()==='加入公文起草依据')!.trigger('click');await flushPromises();
 expect(router.currentRoute.value.path).toBe('/gongwen');
 expect(JSON.parse(sessionStorage.getItem('mqw-gongwen-references')!)[0].content).toBe(content.slice(3).trim());
});
it('cancels a running answer when navigating back to the library',async()=>{
 let signal: AbortSignal | undefined;
 vi.stubGlobal('fetch',vi.fn((_url,options)=>new Promise((_resolve,reject)=>{
  signal=options.signal;signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')));
 })));
 const {router,w}=await open('/gov/policy-qa');await w.get('.gov-composer-input').setValue('政务服务如何办理');await w.get('.gov-send').trigger('click');await flushPromises();
 expect(signal).toBeDefined();expect(signal?.aborted).toBe(false);
 await router.push('/gov/library');await flushPromises();expect(signal?.aborted).toBe(true);
});
