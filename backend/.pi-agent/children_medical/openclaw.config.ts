export default {
  gateway: {
    host: "127.0.0.1",
    port: 18792,
    auth: { token: process.env.PI_AGENT_TOKEN || "" },
  },
  providers: {
    openaiCompatible: {
      baseUrl: "http://192.168.10.212:8081/v1",
      model: "qwen3.5-35b-a3b",
    },
  },
  agents: {
    defaults: {
      skills: [],
      plugins: [],
    },
    list: [{ id: "children-medical" }],
  },
};
