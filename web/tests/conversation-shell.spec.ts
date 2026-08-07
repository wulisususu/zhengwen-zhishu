import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import ChatPanel from "../src/features/ppt-workbench/components/chat/ChatPanel.vue";
import PptResultCard from "../src/features/ppt-workbench/components/chat/PptResultCard.vue";
import { usePptConversationStore } from "../src/features/ppt-workbench/stores/pptConversation";
import { usePptGenerationStore } from "../src/features/ppt-workbench/stores/pptGeneration";
import { usePptProjectStore } from "../src/features/ppt-workbench/stores/pptProject";

describe("conversation shell", () => {
  let pinia: ReturnType<typeof createPinia>;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  const mountChat = (mode: "conversation" | "workbench" = "conversation", running = false) => mount(ChatPanel, {
    props: { running, mode },
    global: { plugins: [pinia] },
  });

  it("renders a complete centered task page for an empty conversation", () => {
    const wrapper = mountChat();
    expect(wrapper.get("h1").text()).toContain("想做一份什么样的 PPT");
    expect(wrapper.get('[aria-label="PPT 需求输入"]')).toBeTruthy();
    expect(wrapper.findAll("[data-prompt-suggestion]").length).toBeGreaterThan(0);
    expect(wrapper.find("[data-recent-projects]").exists()).toBe(false);
    expect(wrapper.get("[aria-label=生成页数]")).toBeTruthy();
    expect(wrapper.text()).not.toContain("后台阶段：");
  });

  it("emits a trimmed valid prompt and ignores empty input", async () => {
    const conversation = usePptConversationStore();
    const wrapper = mountChat();
    conversation.draft = "   ";
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")).toBeUndefined();
    conversation.draft = "  生成年度复盘 PPT  ";
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")?.[0]).toEqual(["生成年度复盘 PPT", 8, "flat", undefined]);
  });

  it("renders the conversation timeline after messages arrive", async () => {
    usePptConversationStore().append({ id: "user-1", role: "user", content: "生成年度复盘", createdAt: "2026-07-17T00:00:00.000Z" });
    const wrapper = mountChat();
    expect(wrapper.get("[data-conversation-timeline]").text()).toContain("生成年度复盘");
    expect(wrapper.find("h1").exists()).toBe(false);
  });

  it("shows Store-driven brief and outline progress without a blank region", async () => {
    const generation = usePptGenerationStore();
    generation.status = "running";
    generation.workflowStage = "understanding";
    const wrapper = mountChat("workbench", true);
    expect(wrapper.get("[data-brief-skeleton]")).toBeTruthy();
    usePptProjectStore().addOutlineItem({ id: "outline-1", title: "封面", description: "说明主题", status: "ready", children: [] });
    generation.workflowStage = "outline";
    await wrapper.vm.$nextTick();
    expect(wrapper.get("[data-outline-item]").text()).toContain("封面");
  });

  it("uses a result card to request reopening after close", async () => {
    const project = usePptProjectStore();
    project.upsertSlide({ id: "slide-1", index: 1, title: "封面", status: "ready", elements: [], userModifiedFields: [], revision: 1 });
    usePptGenerationStore().status = "completed";
    const wrapper = mountChat();
    await wrapper.get('button[aria-label="打开 PPT 编辑器"]').trigger("click");
    expect(wrapper.emitted("open-workbench")).toHaveLength(1);
  });

  it("makes download primary and disables the editor when Legacy has no page data", async () => {
    const wrapper = mount(PptResultCard, {
      props: {
        title: "人工智能安全年度报告",
        completed: true,
        readySlides: 0,
        incrementalSlides: false,
        temporaryTitle: true,
        downloadAvailable: true,
        warnings: ["字体已替换"],
        validationIssues: [],
      },
    });

    expect(wrapper.text()).toContain("PPTX 已生成，当前 Legacy 模式暂不提供在线逐页预览");
    expect(wrapper.text()).not.toContain("0 页内容可用");
    expect(wrapper.text()).toContain("前端临时标题");
    expect(wrapper.get('button[aria-label="等待逐页数据"]').attributes("disabled")).toBeDefined();
    await wrapper.get('button[aria-label="下载 PPTX"]').trigger("click");
    expect(wrapper.emitted("download")).toHaveLength(1);
    expect(wrapper.emitted("open")).toBeUndefined();
  });

  it("keeps the Mock result editor action available", async () => {
    const wrapper = mount(PptResultCard, {
      props: {
        title: "年度复盘",
        completed: true,
        readySlides: 4,
        incrementalSlides: true,
        temporaryTitle: false,
        downloadAvailable: false,
        warnings: [],
        validationIssues: [],
      },
    });

    await wrapper.get('button[aria-label="打开 PPT 编辑器"]').trigger("click");
    expect(wrapper.emitted("open")).toHaveLength(1);
  });

  it("does not call a blocked Legacy result completed when showing warnings", () => {
    const wrapper = mount(PptResultCard, {
      props: {
        title: "未通过检查的文件",
        completed: false,
        failed: true,
        readySlides: 0,
        incrementalSlides: false,
        downloadAvailable: false,
        warnings: [],
        validationIssues: [
          { id: "blocking", severity: "error", blocking: true, message: "文件不完整" },
          { id: "warning", severity: "warning", message: "字体已替换" },
        ],
      },
    });

    expect(wrapper.get("[data-result-warnings]").text()).toBe("警告：字体已替换");
    expect(wrapper.text()).not.toContain("生成完成但有警告");
  });

  it("shows normalized Legacy errors without exposing transport details", () => {
    const generation = usePptGenerationStore();
    generation.fail({
      code: "AUTHENTICATION_REQUIRED",
      message: "登录状态已失效，请重新登录",
      retryable: false,
      httpStatus: 401,
    });
    const wrapper = mountChat("workbench");

    expect(wrapper.get("[data-workflow-error]").text()).toContain("登录状态已失效，请重新登录");
    expect(wrapper.text()).not.toContain("AUTHENTICATION_REQUIRED");
  });

  it("offers a separate native template-fill entry from the normal generator", async () => {
    const wrapper = mountChat();
    await wrapper.get("[data-open-template-fill]").trigger("click");
    expect(wrapper.emitted("open-template-fill")).toHaveLength(1);
  });

});
