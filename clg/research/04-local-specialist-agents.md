# Local Specialist Agents: Small Models, MoE, Edge Deployment & Agent Frameworks

## Executive Summary

The shift from monolithic LLMs to **specialist agent swarms** running locally is the defining trend of 2024. Small Language Models (SLMs: 1-4B params) now match 7B-8B models from 2023. Mixture of Experts (MoE) activates only relevant parameters. Edge deployment (Ollama, MLC-LLM, llama.cpp) runs on consumer hardware. Agent frameworks (LangGraph, Agno, PydanticAI) orchestrate multi-agent workflows.

**Industry State (2024):** Phi-3.5 MoE (6.6B active), Gemma 2 (2B/9B), LLaMA 3.2 (1B/3B), Nemotron-Mini (4B) lead SLMs. Ollama/MLC-LLM/llama.cpp enable universal deployment. The gap: **no framework for dynamic specialist loading with shared context and hardware-aware routing**.

---

## 1. Small Language Models (SLMs): The New Frontier

### Model Landscape (2024)

| Model | Params | Context | Key Strength | License | Deployment |
|-------|--------|---------|--------------|---------|------------|
| **Phi-3.5 Mini** | 3.8B | 128K | Best-in-class reasoning | MIT | ONNX, GGUF, Ollama |
| **Phi-3.5 MoE** | 42B (6.6B active) | 128K | Specialist routing | MIT | ONNX, GGUF |
| **Gemma 2 2B** | 2B | 8K | Tool use, multilingual | Gemma | TF Lite, ONNX, GGUF |
| **Gemma 2 9B** | 9B | 8K | Strong general | Gemma | All platforms |
| **LLaMA 3.2 1B** | 1B | 128K | Ultra-edge, vision | Llama 3.2 | GGUF, MLC-LLM, Core ML |
| **LLaMA 3.2 3B** | 3B | 128K | Best 3B model | Llama 3.2 | All platforms |
| **Nemotron-Mini 4B** | 4B | 128K | Agent-optimized | NVIDIA | TensorRT-LLM, ONNX |
| **SmolLM 1.7B** | 1.7B | 8K | Beats 7B models | Apache 2.0 | Transformers.js, GGUF |
| **Qwen2 1.5B/3B** | 1.5B/3B | 32K/128K | Multilingual, code | Apache 2.0 | All platforms |
| **OpenELM 3B** | 3B | 8K | Apple Neural Engine | Apple | Core ML |

### SLM Benchmark Performance

| Benchmark | Phi-3.5 Mini | Gemma 2 2B | LLaMA 3.2 3B | SmolLM 1.7B | Qwen2 1.5B |
|-----------|--------------|------------|--------------|-------------|------------|
| **MMLU** | 69% | 56% | 63% | 52% | 58% |
| **GSM8K (Math)** | 83% | 65% | 72% | 58% | 68% |
| **HumanEval (Code)** | 62% | 48% | 55% | 42% | 52% |
| **MT-Bench** | 7.2 | 6.1 | 6.8 | 5.8 | 6.3 |
| **Tokens/sec (CPU)** | 45 | 55 | 50 | 60 | 52 |

**Key Insight:** Phi-3.5 Mini (3.8B) beats most 7B models from 2023. MoE variant activates only 6.6B of 42B params.

---

## 2. Mixture of Experts (MoE): Sparse Activation

### Architecture

```
Input → Router → Top-K Experts → Combine → Output
         │
         ├── Expert 1 (Code)
         ├── Expert 2 (Math)
         ├── Expert 3 (Reasoning)
         ├── Expert 4 (Language)
         └── ... (8-64 experts typical)
```

### MoE Models Comparison

| Model | Total Params | Active Params | Experts | Top-K | Router Type |
|-------|-------------|---------------|---------|-------|-------------|
| **Mixtral 8x7B** | 47B | 13B | 8 | 2 | Token Choice |
| **Mixtral 8x22B** | 141B | 39B | 8 | 2 | Token Choice |
| **Phi-3.5 MoE** | 42B | **6.6B** | 16 | 2 | Token Choice |
| **Nemotron 4 340B** | 340B | ~50B | 16 | ? | Token Choice |
| **DeepSeek-V2** | 236B | 21B | 160 | 6 | Expert Choice |
| **DBRX** | 132B | 36B | 16 | 4 | Token Choice |

### Routing Strategies

| Strategy | Description | Pros | Cons |
|----------|-------------|------|------|
| **Token Choice** | Each token picks top-K experts | Simple, standard | Load imbalance |
| **Expert Choice** | Each expert picks top-K tokens | Balanced load | Complex, fixed compute |
| **Soft MoE** | Weighted combination | Smooth gradients | More compute |
| **Hierarchical** | Coarse → Fine routing | Scalable | Latency |

### MoE for Specialist Agents

**Phi-3.5 MoE Innovation:** 16 experts, each potentially specializing in different domains. Router learns to activate relevant experts per token. Enables "specialist" behavior within single model.

**Opportunity:** Fine-tune expert specialization explicitly (Code Expert, Math Expert, etc.) + dynamic loading.

---

## 3. Quantization: Making Models Fit

### Quantization Formats

| Format | Bits | Quality | Speed | Platforms | Use Case |
|--------|------|---------|-------|-----------|----------|
| **GGUF Q4_K_M** | 4-bit (K-quant) | **Best 4-bit** | Fast | llama.cpp, Ollama, LM Studio | **Default choice** |
| **GGUF Q8_0** | 8-bit | Near FP16 | Medium | All | Quality-critical |
| **GGUF Q2_K** | 2-bit | Low | Fastest | Mobile/Edge | Extreme compression |
| **AWQ** | 4-bit | Excellent | Fast | vLLM, TensorRT-LLM, AutoAWQ | GPU serving |
| **GPTQ** | 4-bit | Excellent | Fast | AutoGPTQ, vLLM | GPU serving |
| **FP8** | 8-bit (float) | Native | Fastest | H100, TensorRT-LLM | Training/Inference |
| **INT4/INT8 (RTN)** | 4/8-bit | Good | Fast | TensorRT-LLM, ONNX Runtime | Quick quantization |

### K-Quants (llama.cpp) Explained

| Quant | Description | Size (7B) | Perplexity | Speed |
|-------|-------------|-----------|------------|-------|
| **Q4_K_M** | Medium, k-quant, **recommended** | 3.8 GB | Baseline | Fast |
| Q4_K_S | Small, k-quant | 3.5 GB | +0.5% | Faster |
| Q5_K_M | Medium, 5-bit | 4.7 GB | -0.3% | Medium |
| Q6_K | 6-bit | 5.5 GB | -0.5% | Slower |
| **Q8_0** | 8-bit, baseline | 7.2 GB | Best | Slowest |

**Recommendation:** Q4_K_M for most use cases. Q8_0 for quality-critical. Q2_K only for extreme constraints.

---

## 4. Edge Deployment Frameworks

### Framework Comparison

| Framework | Backend | Platforms | API | Model Format | Best For |
|-----------|---------|-----------|-----|--------------|----------|
| **Ollama** | llama.cpp | macOS, Linux, Windows, Docker | OpenAI-compatible | GGUF | **Easiest local deployment** |
| **LM Studio** | llama.cpp | macOS, Windows, Linux | OpenAI-compatible | GGUF | Best UX, benchmarking |
| **MLC-LLM** | TVM Unity | **Browser (WebGPU)**, iOS, Android, Desktop, Server | Custom | HF, GGUF, ONNX | **Universal deployment** |
| **llama.cpp** | C/C++ | CPU, CUDA, Metal, Vulkan, SYCL | Server (OpenAI) | GGUF | **Maximum control, speed** |
| **Transformers.js** | ONNX Runtime Web | **Browser (WebGPU/WASM)** | Custom | ONNX | Zero-install web apps |
| **MediaPipe LLM** | TensorFlow Lite | Android, iOS, Web | Custom | TF Lite | Mobile apps |
| **Core ML** | Apple Neural Engine | iOS, macOS | Swift | Core ML | Apple ecosystem |
| **TensorRT-LLM** | CUDA/TensorRT | NVIDIA GPU | Triton, Custom | FP8/INT4 | **Max throughput on NVIDIA** |
| **vLLM/SGLang** | CUDA | NVIDIA GPU | OpenAI-compatible | HF, AWQ, GPTQ | **High-throughput serving** |

### Ollama: De Facto Standard for Local LLM

```bash
# Install & run
ollama pull phi3.5:3.8b
ollama run phi3.5:3.8b

# API (OpenAI compatible)
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "phi3.5:3.8b", "messages": [{"role": "user", "content": "Hello"}]}'
```

**Features:**
- 100+ models in library (Llama, Gemma, Phi, Qwen, Mistral, etc.)
- Modelfile for custom models (system prompt, parameters, adapters)
- GPU auto-detection (CUDA, Metal, ROCm, Vulkan)
- Multimodal support (LLaVA, LLaMA 3.2 Vision)
- Python/JS/Go SDKs

### MLC-LLM: Universal Deployment (Unique)

**Runs Same Model On:**
- Browser (WebGPU) - **Only framework doing this well**
- iOS/Android (Metal/Vulkan)
- Desktop (CUDA/Metal/Vulkan)
- Server (CUDA)

```python
# Python
from mlc_llm import MLCEngine
engine = MLCEngine("Phi-3.5-mini-instruct-q4f16_1-MLC")
for chunk in engine.chat.completions.create(messages=[...], stream=True):
    print(chunk.choices[0].delta.content, end="")

# Web (JavaScript)
import { MLCEngine } from "@mlc-ai/web-llm";
const engine = await MLCEngine("Phi-3.5-mini-instruct-q4f16_1-MLC");
const reply = await engine.chat.completions.create({messages: [...]});
```

---

## 5. Agent Frameworks: Orchestrating Specialists

### Framework Comparison

| Framework | Paradigm | Type Safety | State Mgmt | Local LLM | Multi-Agent | Learning Curve |
|-----------|----------|-------------|------------|-----------|-------------|----------------|
| **LangGraph** | Graph (Cyclic) | ⚠️ TypedDict | ✅ Checkpointing | ✅ Excellent | ✅ Native | Medium |
| **AutoGen** | Conversational | ❌ Dynamic | ✅ GroupChat | ✅ Good | ✅ Native | Low |
| **CrewAI** | Role-Based Crews | ❌ Dynamic | ⚠️ Basic | ✅ Good | ✅ Native | Low |
| **Agno** | Functional/Type-Safe | ✅ **Pydantic** | ✅ Built-in | ✅ **Excellent** | ✅ Teams | Low |
| **PydanticAI** | Functional/Type-Safe | ✅ **Pydantic** | ✅ Graph-based | ✅ Good | ✅ Graph | Low |
| **LlamaIndex Agents** | Tool-Based | ⚠️ Partial | ⚠️ Basic | ✅ Excellent | ⚠️ Limited | Low |
| **Semantic Kernel** | Planner + Skills | ⚠️ Partial | ✅ | ✅ Good | ⚠️ | Medium |

### LangGraph: Production Standard for Complex Workflows

```python
from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama

# Define state
class AgentState(TypedDict):
    messages: List[BaseMessage]
    next_agent: str

# Specialist agents
code_agent = ChatOllama(model="codellama:7b")
math_agent = ChatOllama(model="deepseek-math:7b")
writer_agent = ChatOllama(model="phi3.5:3.8b")

# Router (supervisor)
def route(state):
    # LLM or rule-based routing
    return {"next_agent": "code_agent"}  # or math_agent, writer_agent

# Build graph
workflow = StateGraph(AgentState)
workflow.add_node("router", route)
workflow.add_node("code_agent", code_agent)
workflow.add_node("math_agent", math_agent)
workflow.add_node("writer_agent", writer_agent)
workflow.add_conditional_edges("router", lambda s: s["next_agent"])
workflow.set_entry_point("router")

app = workflow.compile()
result = app.invoke({"messages": [HumanMessage("Write Python code to solve quadratic equation")]})
```

**Why LangGraph Wins:**
- Explicit state with checkpointing (pause/resume, human-in-loop)
- Cyclic graphs for self-correction
- LangSmith observability
- Best local LLM integration

### Agno: Modern Type-Safe Alternative

```python
from agno.agent import Agent
from agno.models.ollama import Ollama
from agno.tools.python import PythonTools

# Specialist agents
coder = Agent(
    name="Coder",
    model=Ollama(id="codellama:7b"),
    tools=[PythonTools()],
    instructions=["Write clean, tested Python code"]
)

math_expert = Agent(
    name="MathExpert",
    model=Ollama(id="deepseek-math:7b"),
    instructions=["Solve math problems step by step"]
)

# Team with supervisor
team = Agent(
    name="TeamLead",
    model=Ollama(id="phi3.5:3.8b"),
    team=[coder, math_expert],
    instructions=["Route to appropriate specialist"]
)

# Run
team.print_response("Solve x^2 + 5x + 6 = 0 and write Python code to verify")
```

---

## 6. Specialist Agent Architecture: The Vision

### Dynamic Specialist Swarm

```
┌─────────────────────────────────────────────────────────────────┐
│                    SUPERVISOR (1-3B)                            │
│  • Routes queries to specialists                                │
│  • Maintains shared context                                     │
│  • Aggregates responses                                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  CODE AGENT   │  │  MATH AGENT   │  │ WRITING AGENT │
│ (CodeLlama    │  │ (DeepSeek-    │  │ (Phi-3.5      │
│  7B/13B)      │  │  Math 7B)     │  │  3.8B)        │
├───────────────┤  ├───────────────┤  ├───────────────┤
│ Tools:        │  │ Tools:        │  │ Tools:        │
│ - Python REPL │  │ - Calculator  │  │ - Search      │
│ - Linter      │  │ - Symbolic    │  │ - Summarize   │
│ - Debugger    │  │   Math        │  │ - Format      │
└───────┬───────┘  └───────┬───────┘  └───────┬───────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
              ┌───────────────────────┐
              │   SHARED MEMORY       │
              │  (Encrypted, Local)   │
              │  - Episodic           │
              │  - Semantic           │
              │  - Procedural         │
              └───────────────────────┘
```

### Key Innovations Needed

1. **Dynamic Model Loading**: Hot-swap specialists via MLC-LLM/llama.cpp in <1s
2. **Shared KV Cache**: Specialists attend to same context (cross-attention)
3. **Hardware-Aware Routing**: Route to quantized variant based on device
4. **Specialist Marketplace**: Install/uninstall agents like apps

---

## 7. Tool Use & Structured Output

### Small Model Tool Calling

| Model | Tool Calling | Structured Output | Notes |
|-------|--------------|-------------------|-------|
| **Gemma 2** | ✅ Native | ✅ JSON Schema | Best SLM for tools |
| **Phi-3.5** | ✅ Via TypeChat | ✅ JSON Schema | Microsoft TypeChat |
| **Nemotron-Mini** | ✅ Native | ✅ JSON Schema | NVIDIA optimized |
| **LLaMA 3.2** | ✅ Native | ✅ JSON Schema | Meta tool calling |
| **Qwen2** | ✅ Native | ✅ JSON Schema | Strong function calling |
| **SmolLM** | ⚠️ Prompt-based | ⚠️ Prompt-based | Needs guidance |

### Structured Output Frameworks

| Framework | Approach | Local LLM Support | Streaming |
|-----------|----------|-------------------|-----------|
| **SGLang** | Constrained decoding (regex/grammar) | ✅ | ✅ |
| **Outlines** | Regex/JSON Schema/Type-guided | ✅ | ✅ |
| **Guidance** | Template + constraint | ✅ | ✅ |
| **Instructor** | Pydantic + retries | ✅ (via API) | ❌ |
| **PydanticAI** | Native Pydantic | ✅ | ✅ |

**SGLang Example:**
```python
from sglang import function, gen, set_default_backend, RuntimeEndpoint

set_default_backend(RuntimeEndpoint("http://localhost:30000"))

@function
def extract_info(s, text: str):
    s += "Extract name, email, company as JSON:\n" + text + "\n"
    s += gen("json", max_tokens=200, regex=r'\{.*\}')

result = extract_info.run(text="John Doe (john@acme.com) works at Acme Corp")
# Returns validated JSON
```

---

## 8. On-Device Fine-Tuning

### Methods

| Method | Params Trained | VRAM (4B) | Quality | Speed | Use Case |
|--------|----------------|-----------|---------|-------|----------|
| **Full Fine-tune** | 100% | 48 GB+ | Best | Slow | Research |
| **LoRA** | 0.1-1% | 8-16 GB | Near-full | Medium | Production |
| **QLoRA** | 0.1-1% | 6-10 GB | Near-full | Medium | **Consumer GPU** |
| **DoRA** | 0.1-1% | 8-16 GB | Better than LoRA | Medium | Quality-critical |
| **Prompt Tuning** | 0.01% | 4-6 GB | Good | Fast | Quick adaptation |

### Local Fine-Tuning Stack

```bash
# Unsloth (Fastest QLoRA)
pip install unsloth
# 2-5x faster than standard QLoRA

# Or Axolotl (Config-driven)
pip install axolotl
axolotl train config.yml

# Or llama.cpp LoRA (CPU/Apple Silicon)
./llama-lora-train -m model.gguf -d data.jsonl -o adapter.lora
```

---

## 9. Hardware-Aware Deployment

### Device Capability Matrix

| Device | Compute | Memory | Best Models | Framework |
|--------|---------|--------|-------------|-----------|
| **Phone (NPU)** | 10-50 TOPS | 4-8 GB | 1-3B INT4 | MLC-LLM, Core ML, MediaPipe |
| **Laptop (Integrated GPU)** | 5-20 TFLOPS | 8-16 GB | 3-7B INT4 | Ollama, llama.cpp, MLC-LLM |
| **Laptop (dGPU: RTX 4060)** | 15-30 TFLOPS | 8 GB | 7-13B INT4/FP8 | Ollama, TensorRT-LLM, vLLM |
| **Desktop (RTX 4090)** | 80-100 TFLOPS | 24 GB | 70B INT4, 13B FP16 | vLLM, TensorRT-LLM, SGLang |
| **Server (H100)** | 2000+ TFLOPS | 80 GB | 400B+ FP8 | TensorRT-LLM, vLLM cluster |
| **Jetson Orin** | 200-275 TOPS | 32-64 GB | 7-13B INT4/FP8 | TensorRT-LLM, MLC-LLM |

### Auto-Selection Logic (Innovation Opportunity)

```python
def select_model(task: str, hardware: HardwareInfo) -> ModelConfig:
    # Benchmark candidates on this hardware
    candidates = MODEL_ZOO[task]  # e.g., ["phi3.5:3.8b-q4", "gemma2:2b-q4", "qwen2:1.5b-q4"]
    
    scores = {}
    for model in candidates:
        # Micro-benchmark: 10 token generation
        tps, mem, latency = benchmark(model, hardware)
        scores[model] = score(tps, mem, latency, hardware.thermal)
    
    return max(scores, key=scores.get)
```

---

## 10. Industry Implementations

### Company Strategies

| Company | SLM Strategy | MoE | Edge Deployment | Agent Framework |
|---------|--------------|-----|-----------------|-----------------|
| **Microsoft** | Phi-3.5 (3.8B, MoE) | ✅ Phi-3.5 MoE | ONNX Runtime, Olive | AutoGen, TypeChat |
| **Google** | Gemma 2 (2B/9B/27B) | ❌ | MediaPipe, TF Lite, Web | - |
| **Meta** | LLaMA 3.2 (1B/3B/11B/90B) | ❌ | llama.cpp, MLC-LLM, Core ML | Llama Stack |
| **NVIDIA** | Nemotron-Mini 4B | ❌ | TensorRT-LLM, MLC-LLM | NeMo Agent |
| **Apple** | OpenELM (270M-3B) | ❌ | Core ML, Private Cloud Compute | - |
| **Hugging Face** | SmolLM (135M-1.7B) | ❌ | Transformers.js, Optimum | - |
| **Mistral** | Ministral (3B/8B) | ✅ Mixtral | llama.cpp, vLLM | - |

### Open Source Ecosystem

- **Model Hubs**: Hugging Face (500K+), Ollama Library, LM Studio
- **Quantization**: llama.cpp (GGUF), AutoAWQ, AutoGPTQ, Optimum
- **Serving**: vLLM, SGLang, TensorRT-LLM, TGI, Ollama
- **Agents**: LangGraph, AutoGen, CrewAI, Agno, PydanticAI
- **Compilation**: MLC-LLM (TVM), ONNX Runtime, TensorRT, Core ML

---

## 11. Innovation Opportunities

### High Impact + High Feasibility

1. **Hardware-Aware Model Routing** (See `innovations.json`)
   - Auto-benchmark + select optimal model per device/task

2. **Specialist Agent Swarm** (See `innovations.json`)
   - Dynamic loading, shared context, modular specialists

### High Impact + Medium Feasibility

3. **Cross-Session Encrypted Memory** (See `innovations.json`)
   - Persistent memory for specialist agents

4. **On-Device LoRA Fine-Tuning Pipeline**
   - User teaches specialist new skills locally

### Research Frontiers

5. **Collaborative Multi-Agent on Single Device**
   - Specialists communicate via shared latent space
6. **Adaptive Quantization Per Layer Per Task**
   - Router chooses quantization, not just expert
7. **Specialist Distillation from Large Models**
   - Auto-generate training data from 70B for 3B specialists

---

## 12. Benchmarks & Metrics

See `benchmarks.json` for detailed numbers. Key aggregates:

| Metric | Phi-3.5 Mini | Gemma 2 2B | LLaMA 3.2 3B | SmolLM 1.7B |
|--------|--------------|------------|--------------|-------------|
| **MMLU** | 69% | 56% | 63% | 52% |
| **Code (HumanEval)** | 62% | 48% | 55% | 42% |
| **Math (GSM8K)** | 83% | 65% | 72% | 58% |
| **CPU Tok/s (Q4_K_M)** | 45 | 55 | 50 | 60 |
| **VRAM (Q4_K_M)** | 2.8 GB | 1.5 GB | 2.2 GB | 1.2 GB |
| **Model Size (Q4_K_M)** | 2.2 GB | 1.2 GB | 1.8 GB | 1.0 GB |

---

## 13. Research Gaps & Future Directions

1. **Unified Specialist Framework**: No framework handles dynamic loading + shared context + hardware routing
2. **Specialist Training Pipeline**: Auto-generate specialist training data from large models
3. **Latency-Optimized Swarm**: Sub-100ms specialist switching
4. **Privacy-Preserving Agent Communication**: Encrypted inter-agent messages
5. **Benchmark Standardization**: No standard benchmark for multi-agent specialist systems
6. **Energy-Aware Routing**: Battery/thermal constraints on mobile
7. **Federated Specialist Learning**: Specialists improve from user feedback locally

---

## 14. References

### Key Papers (2023-2024)
- Phi-3/3.5: Microsoft Research blogs
- Gemma 2: Google DeepMind blog
- LLaMA 3.2: Meta AI blog
- Mixtral MoE: Jiang et al., 2024
- DeepSeek-V2 MoE: DeepSeek AI, 2024
- QLoRA: Dettmers et al., 2023
- MLC-LLM: MLC AI Team, 2023
- vLLM: Kwon et al., 2023
- SGLang: Zheng et al., 2024
- LangGraph: LangChain blog, 2024

### Repositories
- Ollama: github.com/ollama/ollama
- llama.cpp: github.com/ggerganov/llama.cpp
- MLC-LLM: github.com/mlc-ai/mlc-llm
- vLLM: github.com/vllm-project/vllm
- SGLang: github.com/sgl-project/sglang
- LangGraph: github.com/langchain-ai/langgraph
- Agno: github.com/agno-agi/agno
- PydanticAI: github.com/pydantic/pydantic-ai
- Transformers.js: github.com/huggingface/transformers.js

---

*Last Updated: 2026-10-11 | Part of College Project Research Dashboard*