import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  // ── 主模型：Qwen3.5 35B（任务编排 + 工具调用）──
  pi.registerProvider("qwen35b", {
    name: "Qwen3.5 35B (任务编排)",
    baseUrl: "http://192.168.10.212:8081/v1",
    apiKey: "ollama",
    api: "openai-completions",
    models: [
      {
        id: "Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf",
        name: "Qwen3.5 35B",
        reasoning: false,
        input: ["text"],
        cost: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
        },
        contextWindow: 32768,
        maxTokens: 7000,
        compat: {
          supportsDeveloperRole: false,
          supportsTools: true,
          supportsStore: false,
          maxTokensField: "max_tokens",
        },
      },
    ],
  });

  // ── 医疗模型：HuatuoGPT-o1-7B（少儿医疗专业问答）──
  pi.registerProvider("huatuo", {
    name: "HuatuoGPT-o1-7B (少儿医疗)",
    baseUrl: "http://115.190.225.138:8083/v1",
    apiKey: "sk-huatuo123",
    api: "openai-completions",
    models: [
      {
        id: "HuatuoGPT-o1-7B",
        name: "HuatuoGPT-o1 7B",
        reasoning: false,
        input: ["text"],
        cost: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
        },
        contextWindow: 32768,
        maxTokens: 2048,
        compat: {
          supportsDeveloperRole: false,
          supportsTools: false,
          supportsStore: false,
          maxTokensField: "max_tokens",
        },
      },
    ],
  });
}
