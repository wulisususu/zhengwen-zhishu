import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia } from "pinia";
import type { SummaryResult } from "../../src/features/gov-office/types";

const adapter = vi.hoisted(() => ({
  mode: "http",
  getRuntimeStatus: vi.fn(),
  getCurrentActor: vi.fn(),
  listMaterialLibrary: vi.fn(),
  uploadMaterial: vi.fn(),
  summarizeMaterial: vi.fn(),
}));
vi.mock("../../src/features/gov-office/adapters", async (original) => ({
  ...(await original<typeof import("../../src/features/gov-office/adapters")>()),
  getGovOfficeAdapter: () => adapter,
}));
import SummaryPage from "../../src/features/gov-office/pages/SummaryPage.vue";
import { GovOfficeError } from "../../src/features/gov-office/adapters/GovOfficeAdapter";

const MEETING: SummaryResult = {
  origin: "backend",
  mode: "meeting",
  materials: [{ fileId: "5", fileName: "纪要.txt", segments: 4 }],
  sections: [
    { key: "decisions", label: "会议决议", items: [{ text: "同意启动自查", sources: ["S2"], notes: [] }] },
    { key: "tasks", label: "工作任务", items: [
      { text: "完成自查报告", owner: "数据安全处", deadline: "2025年11月30日前", sources: ["S3"], notes: [] },
      { text: "印发通知", owner: "", deadline: "", sources: ["S4"], notes: ["模型给出的责任部门「信息中心」未在所引原文中找到，已置空"] },
    ] },
  ],
  sources: {
    S2: { id: "S2", fileId: "5", fileName: "纪要.txt", page: null, paragraph: 2, text: "会议议定：同意启动政务数据安全自查工作。" },
    S3: { id: "S3", fileId: "5", fileName: "纪要.txt", page: 1, paragraph: 3, text: "由数据安全处牵头，于2025年11月30日前完成自查报告。" },
    S4: { id: "S4", fileId: "5", fileName: "纪要.txt", page: null, paragraph: 4, text: "办公室负责会议通知的印发。" },
  },
  dropped: [{ section: "工作任务", text: "编造的任务", reason: "没有引用有效的原文片段" }],
  generatedAt: "2026-10-26T12:00:00+00:00",
};

let wrapper: VueWrapper | undefined;
beforeEach(() => {
  vi.clearAllMocks();
  adapter.getRuntimeStatus.mockResolvedValue({ origin: "backend", modelMode: "cloud_allowed", label: "", detail: "" });
  adapter.getCurrentActor.mockResolvedValue({ origin: "backend", account: "writer", name: "起草人", department: "", roles: ["drafter"], canFormalIssue: false });
  adapter.listMaterialLibrary.mockResolvedValue([
    { id: "5", name: "纪要.txt", meta: ".txt" },
    { id: "6", name: "台账.xlsx", meta: ".xlsx" },
  ]);
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; });

async function open() {
  wrapper = mount(SummaryPage, { global: { plugins: [createPinia()], stubs: {
    GovLayout: { template: "<div><slot /></div>" },
    GovPageHeader: { props: ["title"], template: "<h1>{{ title }}</h1>" },
  } } });
  await flushPromises();
  return wrapper;
}

it("lists only supported materials and sends the chosen material and mode", async () => {
  adapter.summarizeMaterial.mockResolvedValue(MEETING);
  const w = await open();
  expect(w.get("h1").text()).toBe("提炼总结");
  expect(w.text()).toContain("纪要.txt");
  expect(w.text()).not.toContain("台账.xlsx");
  await w.get('input[name="summary-mode"][value="meeting"]').setValue(true);
  await w.get(".gov-sum__run").trigger("click");
  await flushPromises();
  expect(adapter.summarizeMaterial).toHaveBeenCalledWith("5", "meeting");
});

it("shows every conclusion with its source and opens the cited passage", async () => {
  adapter.summarizeMaterial.mockResolvedValue(MEETING);
  const w = await open();
  await w.get(".gov-sum__run").trigger("click");
  await flushPromises();
  expect(w.text()).toContain("后端已逐条校验出处");
  const rows = w.findAll(".gov-sum__table tbody tr");
  expect(rows[0].text()).toContain("数据安全处");
  expect(rows[1].text()).toContain("原文未写明");
  expect(rows[1].text()).toContain("「信息中心」未在所引原文中找到");
  expect(w.get(".gov-sum__dropped summary").text()).toContain("1 条");
  expect(w.get(".gov-sum__dropped").text()).toContain("没有引用有效的原文片段");
  const chip = w.findAll(".gov-sum__chip").find((c) => c.text() === "S3")!;
  await chip.trigger("click");
  expect(chip.attributes("aria-pressed")).toBe("true");
  expect(w.get(".gov-sum__source").text()).toContain("第1页 第3段");
  expect(w.get(".gov-sum__quote").text()).toBe("由数据安全处牵头，于2025年11月30日前完成自查报告。");
});

it("reports a backend refusal instead of showing a result", async () => {
  adapter.summarizeMaterial.mockRejectedValue(new GovOfficeError("模型服务不可用或返回空内容，未生成提炼结果。", "503"));
  const w = await open();
  await w.get(".gov-sum__run").trigger("click");
  await flushPromises();
  expect(w.get('[role="alert"]').text()).toContain("未生成提炼结果");
  expect(w.find(".gov-sum__section").exists()).toBe(false);
});
