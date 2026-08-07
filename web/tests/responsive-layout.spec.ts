import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ResizablePanel from "../src/features/ppt-workbench/components/shell/ResizablePanel.vue";

describe("panel layout safety", () => {
  it("exposes an accessible vertical separator", () => {
    const wrapper = mount(ResizablePanel, { props: { width: 392, min: 340, max: 520, label: "调整对话宽度" } });
    const separator = wrapper.get('[role="separator"]');
    expect(separator.attributes("aria-label")).toBe("调整对话宽度");
    expect(separator.attributes("aria-orientation")).toBe("vertical");
    expect(separator.attributes("tabindex")).toBe("0");
  });

  it("updates width from keyboard without touching business state", async () => {
    const wrapper = mount(ResizablePanel, { props: { width: 392, min: 340, max: 520, label: "调整对话宽度" } });
    await wrapper.get('[role="separator"]').trigger("keydown", { key: "ArrowRight" });
    expect(wrapper.emitted("update:width")?.[0]).toEqual([400]);
  });

  it("contains a temporary narrow responsive fallback", () => {
    const css = readFileSync(resolve("src/features/ppt-workbench/ppt-workbench.css"), "utf8");
    expect(css).toContain("@media (max-width: 799px)");
    expect(css).toContain("data-responsive-fallback");
  });

  it("animates the chat dock and staggers the rail/editor during opening", () => {
    const css = readFileSync(resolve("src/features/ppt-workbench/ppt-workbench.css"), "utf8");
    expect(css).toContain("ppt-chat-dock");
    expect(css).toContain("animation-delay: 80ms");
    expect(css).toContain("animation-delay: 140ms");
  });
});
