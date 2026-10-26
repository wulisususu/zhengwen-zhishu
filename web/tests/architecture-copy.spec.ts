// Architecture copy: drafting and policy QA call the cloud government model API (no local NPU
// inference). Pages must not claim on-device inference or that content never leaves the unit.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = (path: string) => readFileSync(path, "utf8");
const PAGES = ["src/views/GongwenPage.vue", "src/views/PolicyPage.vue", "src/views/WelcomePage.vue", "src/views/AgentDirectoryPage.vue", "index.html"];
const FORBIDDEN = /端侧|NPU|本地推理|本地模型|不出设备|不出单位|不出域|不出本机|离线运行/;

describe("model architecture copy", () => {
  it.each(PAGES)("%s makes no on-device or data-locality claim", (path) => {
    expect(source(path)).not.toMatch(FORBIDDEN);
  });

  it.each(["src/views/GongwenPage.vue", "src/views/WelcomePage.vue", "src/views/AgentDirectoryPage.vue"])(
    "%s states that generation uses the cloud government model API", (path) => {
      expect(source(path)).toContain("云端政务模型 API");
    });

  it("tells users that content is sent to the cloud service", () => {
    expect(source("src/views/GongwenPage.vue")).toContain("内容会发送至该服务");
    expect(source("src/views/WelcomePage.vue")).toContain("内容会发送至该服务");
  });
});
