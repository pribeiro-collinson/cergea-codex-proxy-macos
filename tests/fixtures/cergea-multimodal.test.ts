import { describe, expect, test } from "bun:test";
import { parseConfig } from "../src/config.ts";
import { routeModelForMessages } from "../src/router.ts";
import type { Message, Tool } from "../src/types.ts";

function config() {
  return parseConfig({
    listen: "127.0.0.1:18789",
    defaultProvider: "cergea",
    defaultModel: "cergea/zai-glm-5",
    providers: {
      cergea: {
        adapter: "openai-chat",
        baseUrl: "https://example.invalid/v1",
        apiKeyEnv: "CERGEA_LITELLM_API_KEY",
        visionFallbackModel: "claude-haiku-5-5",
        toolFallbackModel: "zai-glm-5",
        models: [
          {
            id: "zai-glm-5",
            contextWindow: 200000,
            maxOutputTokens: 16384,
            reasoning: true,
            reasoningLevels: ["low", "medium", "high"],
            defaultReasoningLevel: "high",
            inputModalities: ["text", "image"],
            routeImagesToFallback: true,
          },
          {
            id: "claude-haiku-5-5",
            contextWindow: 1000000,
            maxOutputTokens: 16384,
            reasoning: true,
            reasoningLevels: ["low", "medium", "high"],
            defaultReasoningLevel: "high",
            inputModalities: ["text", "image"],
          },
          {
            id: "claude-sonnet-5-5",
            contextWindow: 1000000,
            maxOutputTokens: 16384,
            reasoning: true,
            reasoningLevels: ["low", "medium", "high"],
            defaultReasoningLevel: "high",
            inputModalities: ["text", "image"],
          },
          {
            id: "mistral-mixtral-8x7b-instruct",
            contextWindow: 32000,
            maxOutputTokens: 4096,
            reasoning: false,
            reasoningLevels: [],
            defaultReasoningLevel: "none",
            inputModalities: ["text", "image"],
            routeImagesToFallback: true,
            supportsToolCalling: false,
          },
        ],
      },
    },
  });
}

const imageMessage: Message = {
  role: "user",
  content: [
    { type: "text", text: "Analyze this image" },
    { type: "image", url: "data:image/png;base64,synthetic-test" },
  ],
};
const textMessage: Message = { role: "user", content: [{ type: "text", text: "Follow up in text" }] };

describe("Cergea multimodal routing", () => {
  test("advertises GLM image input but routes image turns to Haiku", () => {
    const cfg = config();
    const glm = cfg.providers.cergea?.models.find((model) => model.id === "zai-glm-5");
    expect(glm?.inputModalities).toEqual(["text", "image"]);
    expect(glm?.routeImagesToFallback).toBe(true);
    const result = routeModelForMessages("cergea/zai-glm-5", cfg, [imageMessage]);
    expect(result.slug).toBe("cergea/claude-haiku-5-5");
  });

  test("does not reroute when Haiku is selected directly", () => {
    const result = routeModelForMessages("cergea/claude-haiku-5-5", config(), [imageMessage]);
    expect(result.slug).toBe("cergea/claude-haiku-5-5");
  });

  test("returns text-only follow-ups to GLM even when an earlier image remains in history", () => {
    const result = routeModelForMessages("cergea/zai-glm-5", config(), [
      imageMessage,
      { role: "assistant", content: [{ type: "text", text: "Image analyzed" }] },
      textMessage,
    ]);
    expect(result.slug).toBe("cergea/zai-glm-5");
  });

  test("does not reroute a vision-capable model", () => {
    const result = routeModelForMessages("cergea/claude-sonnet-5-5", config(), [imageMessage]);
    expect(result.slug).toBe("cergea/claude-sonnet-5-5");
  });

  test("advertises Mistral image paste and routes image turns to Haiku", () => {
    const cfg = config();
    const mistral = cfg.providers.cergea?.models.find((model) => model.id === "mistral-mixtral-8x7b-instruct");
    expect(mistral?.inputModalities).toEqual(["text", "image"]);
    expect(mistral?.routeImagesToFallback).toBe(true);
    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", cfg, [imageMessage]);
    expect(result.slug).toBe("cergea/claude-haiku-5-5");
  });

  test("returns text-only Mistral follow-ups to Mistral when an earlier image remains in history", () => {
    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", config(), [
      imageMessage,
      { role: "assistant", content: [{ type: "text", text: "Image analyzed" }] },
      textMessage,
    ]);
    expect(result.slug).toBe("cergea/mistral-mixtral-8x7b-instruct");
  });

  test("returns to the selected text model when submitted history contains no image", () => {
    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", config(), [textMessage]);
    expect(result.slug).toBe("cergea/mistral-mixtral-8x7b-instruct");
  });

  test("routes tool-bearing Mistral requests to GLM instead of sending unsupported Bedrock parameters", () => {
    const tool: Tool = { type: "function", name: "exec", description: "Run a command", parameters: {} };
    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", config(), [textMessage], [tool]);
    expect(result.slug).toBe("cergea/zai-glm-5");
  });

  test("image routing takes precedence over tool fallback for Mistral", () => {
    const tool: Tool = { type: "function", name: "exec", description: "Run a command", parameters: {} };
    const result = routeModelForMessages("cergea/mistral-mixtral-8x7b-instruct", config(), [imageMessage], [tool]);
    expect(result.slug).toBe("cergea/claude-haiku-5-5");
  });

  test("does not reroute tool-capable GLM requests", () => {
    const tool: Tool = { type: "function", name: "exec", description: "Run a command", parameters: {} };
    const result = routeModelForMessages("cergea/zai-glm-5", config(), [textMessage], [tool]);
    expect(result.slug).toBe("cergea/zai-glm-5");
  });

  test("fails clearly if forced image routing has no configured fallback", () => {
    const value = config();
    const provider = value.providers.cergea;
    if (!provider) throw new Error("test fixture provider missing");
    delete provider.visionFallbackModel;
    expect(() => routeModelForMessages("cergea/zai-glm-5", value, [imageMessage])).toThrow(
      "has no visionFallbackModel configured",
    );
  });
});
