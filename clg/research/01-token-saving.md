# Token Saving: Context Compression & Efficiency Optimization

## Executive Summary

Token saving is the single highest-leverage optimization for LLM deployment. Every token saved reduces compute, memory, latency, and cost proportionally. This research covers the four pillars of token efficiency: **KV cache optimization**, **attention mechanism improvements**, **prompt/context compression**, and **speculative decoding**.

**Industry State (2024):** Production systems achieve 2-4x token savings through combined techniques. The frontier is adaptive, hardware-aware compression that learns per-user patterns.

---

## 1. KV Cache Optimization

### The Problem
KV cache grows linearly with context length: 2 × layers × heads × head_dim × seq_len × bytes_per_param. For LLaMA-3.1-70B at 128K context: ~140 GB FP16.

### Industry Solutions

| Technique | Memory Reduction | Quality Loss | Adoption |
|-----------|-----------------|--------------|----------|
| **INT8 Quantization** | 2x | <0.5% perplexity | TensorRT-LLM, vLLM, llama.cpp |
| **INT4 Quantization** | 4x | <1% perplexity | NVIDIA (Nemotron), llama.cpp Q4_K |
| **FP8 (H100+)** | 2x | Negligible | Together Engine, TensorRT-LLM |
| **KV Cache Eviction** | Variable | Task-dependent | H2O, SnapKV, PyramidKV |
| **Cross-layer Sharing** | 2-4x | <2% | MiniCache, CacheGen |

### Key Papers & Implementations

1. **TensorRT-LLM KV Cache Quantization** (NVIDIA, 2023-2024)
   - Production-grade INT8/FP8 quantization
   - Calibration-aware quantization per layer
   - Integrated in vLLM, SGLang, Together Engine

2. **H2O: Heavy-Hitter Oracle for Efficient KV Cache Eviction** (Zhang et al., 2024)
   - Retain only "heavy hitter" tokens by attention score
   - 50% cache reduction with minimal quality loss
   - Dynamic eviction policy

3. **SnapKV: LLM Knows What You Need** (Li et al., 2024)
   - Pre-compute important token positions
   - 3.6x speedup, 82% memory reduction
   - No fine-tuning required

4. **PyramidKV: Dynamic KV Cache Compression** (Liu et al., 2024)
   - Hierarchical compression: recent=full, older=compressed
   - Adapts to attention patterns

### Company Implementations

- **NVIDIA**: TensorRT-LLM (INT8/FP8, production standard)
- **Together AI**: Together Inference Engine (FP8 KV cache)
- **vLLM/SGLang**: PagedAttention + prefix caching + quantization
- **llama.cpp**: GGUF K-quants (Q4_K_M, Q8_0) for CPU/GPU
- **Microsoft**: KV cache quantization in Phi-3.5 deployment

---

## 2. Attention Mechanism Optimization

### FlashAttention Evolution

| Version | Key Innovation | Speedup | Hardware |
|---------|---------------|---------|----------|
| FlashAttention-1 | IO-aware tiling, softmax fusion | 2-4x vs naive | Ampere+ |
| FlashAttention-2 | Parallelism, work partitioning | 2x vs FA-1 | Ampere/Hopper |
| **FlashAttention-3** | **Async pipeline, FP8, warp specialization** | **2-3x vs FA-2** | **Hopper (H100)** |

### Alternative Attention Patterns

| Pattern | Complexity | Context Scaling | Quality Trade-off | Used By |
|---------|------------|-----------------|-------------------|---------|
| **Full Attention** | O(n²) | Quadratic | Baseline | GPT-3, LLaMA-1/2 |
| **Sliding Window (SWA)** | O(n×w) | Linear | Local context only | Mistral, Mixtral |
| **Grouped Query (GQA)** | O(n²/h) | Quadratic | Minimal | LLaMA 3.1, Gemma 2, Phi-3.5 |
| **Multi-Query (MQA)** | O(n²/h) | Quadratic | Some quality loss | PaLM, early LLaMA |
| **Linear Attention** | O(n) | Linear | Requires retraining | RecurrentGemma, Griffin |
| **Sparse Attention** | O(n√n) | Sub-quadratic | Pattern-dependent | BigBird, Longformer |

### Industry Adoption

- **Mistral**: SWA + GQA = 2x speedup, 50% KV cache reduction at 128K
- **Google**: RecurrentGemma (linear attention) matches Transformer quality
- **Meta**: GQA in LLaMA 3.1 (8 groups for 70B, 4 for 8B)
- **Microsoft**: Phi-3.5 uses GQA + SWA hybrid

---

## 3. Prompt & Context Compression

### Compression Taxonomy

```
Prompt Compression
├── Task-Aware (requires task labels)
│   ├── Selective Context (Li et al., 2023)
│   ├── RECOMP (Xu et al., 2023)
│   └── LLMLingua-1 (Jiang et al., 2023)
└── Task-Agnostic (general purpose)
    ├── LLMLingua-2 (Jiang et al., 2024) ⭐ SOTA
    ├── LongLLMLingua (Jiang et al., 2024)
    ├── AutoCompressor (Kim et al., 2024)
    └── Semantic Compression (various)
```

### Benchmark Comparison

| Method | Compression Ratio | Quality Retention | Latency Overhead | Task-Agnostic |
|--------|------------------|-------------------|------------------|---------------|
| **LLMLingua-2** | **20x** | **98%+** | Low (small model) | ✅ |
| LongLLMLingua | 6-10x | Improves long-context | Medium | ✅ |
| Selective Context | 2-4x | 95%+ | Low | ❌ |
| RECOMP | 2-3x | 95%+ | Medium | ❌ |
| AutoCompressor | 10x | 95%+ | High (training) | ✅ |

### LLMLingua-2 Deep Dive (SOTA)

**Architecture:**
- Small encoder (GPT-2 size) trained via data distillation
- Compresses prompt → pseudo-tokens → feeds to target LLM
- Trained on diverse tasks, generalizes to unseen tasks

**Integration:**
- Milvus/LlamaIndex/LangChain: `llmlingua.compress_prompt()`
- Together AI: Built-in compression API
- Custom: ~50 lines of Python + model weights

**Limitations:**
- Compressor model adds latency (~10-50ms)
- Struggles with highly structured prompts (code, few-shot)
- Quality drops at >30x compression

---

## 4. Speculative Decoding

### Core Idea
Small draft model proposes N tokens → Large model verifies in parallel → Accept/reject → 2-3x speedup with **zero quality loss**.

### Methods Comparison

| Method | Draft Model | Speedup | Complexity | Deployment |
|--------|-------------|---------|------------|------------|
| **Standard** | Separate small model | 2-2.5x | Medium | vLLM, TensorRT-LLM |
| **Medusa** | Multi-head on target | 2-2.5x | Low (fine-tune heads) | vLLM, SGLang, llama.cpp |
| **EAGLE** | Feature retrieval + draft | 2.5-3x | Medium | vLLM, Together Engine |
| **Lookahead** | No draft (window attention) | 1.5-2x | Very Low | Any |
| **SpecInfer** | Tree-based drafting | 2-3x | High | Research |

### Production Status

- **vLLM**: Supports Medusa, EAGLE, standard speculative decoding
- **SGLang**: Native speculative decoding with RadixAttention
- **TensorRT-LLM**: Highly optimized Medusa/EAGLE kernels
- **llama.cpp**: Medusa heads support (GGUF format)
- **Together AI**: EAGLE integration in production engine

### Key Insight
Speculative decoding is **orthogonal** to quantization and compression - stack them for multiplicative gains.

---

## 5. Tokenization Improvements

### Current Landscape

| Tokenizer | Vocab Size | Approach | Used By |
|-----------|------------|----------|---------|
| **BPE (GPT-2/3/4)** | 50K-100K | Byte-pair encoding | OpenAI, Meta, Mistral |
| **SentencePiece (Unigram)** | 32K-256K | Probabilistic | Google (Gemma), T5 |
| **Byte-level BPE** | 256 base | UTF-8 bytes + merges | LLaMA 3, GPT-4o |
| **Semantic Tokenization** | Variable | Meaning-based | Research |

### Innovations

1. **LLaMA 3 Tokenizer**: 128K vocab, byte-level, better code/math tokenization
2. **Gemma 2**: 256K vocab, better multilingual
3. **Matryoshka Tokenization** (Research): Nested vocabularies for adaptive compression
4. **ByteLatent Transformer** (Meta, 2024): Byte-level patches, no fixed vocab

---

## 6. Combined Production Stack (2024 Best Practices)

```
┌─────────────────────────────────────────────────────────────┐
│                    REQUEST                                    │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LLMLingua-2 Compression (20x, task-agnostic)               │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  vLLM / SGLang / TensorRT-LLM                               │
│  ├── PagedAttention (optimal KV cache)                      │
│  ├── Prefix Caching (30-70% hit rate)                       │
│  ├── KV Cache INT8/FP8 Quantization (2-4x memory)           │
│  ├── FlashAttention-3 (H100) / FlashAttention-2 (A100)      │
│  └── Speculative Decoding (Medusa/EAGLE, 2-3x speed)        │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    RESPONSE                                   │
└─────────────────────────────────────────────────────────────┘
```

**Typical Combined Gains:**
- **Memory**: 8-16x reduction (quantization + compression + paging)
- **Throughput**: 20-50x vs naive HF Transformers
- **Latency**: 2-5x improvement (speculative + attention)
- **Cost**: 10-20x reduction per request

---

## 7. Innovation Opportunities

### High Impact + High Feasibility

1. **Adaptive Context Compression** (See `innovations.json`)
   - Per-user learned compression policies
   - 2-3x better compression than LLMLingua on user-specific workloads

2. **Semantic Cache with TTL** (See `innovations.json`)
   - Meaning-based cache invalidation
   - Knowledge freshness awareness

### Medium Impact + High Feasibility

3. **Hardware-Aware KV Quantization Policy**
   - Auto-select INT4/INT8/FP8 per layer per GPU
   - Thermal-aware dynamic adjustment

4. **Cross-Session KV Cache Sharing**
   - Share cached prefixes across user sessions
   - Privacy-preserving via encryption

### High Impact + Medium Feasibility

5. **Speculative Compression**
   - Draft model proposes compressed context
   - Target model verifies decompression quality

---

## 8. Benchmarks & Metrics

See `benchmarks.json` for detailed numbers. Key aggregates:

| Metric | Baseline (HF) | Optimized Stack | Improvement |
|--------|--------------|-----------------|-------------|
| **Throughput (tok/s)** | 50 | 1500 | **30x** |
| **Memory (GB, 128K ctx)** | 140 | 10 | **14x** |
| **Latency (TTFT, ms)** | 2000 | 100 | **20x** |
| **Cost per 1M tokens** | $10 | $0.50 | **20x** |

---

## 9. Research Gaps & Future Directions

1. **Adaptive Compression**: No production system learns per-user patterns
2. **Unified Compression+Speculation**: Joint optimization unexplored
3. **Hardware-Software Co-design**: NPU-specific quantization policies
4. **Compression for Reasoning**: Chain-of-thought compression barely studied
5. **Multimodal Compression**: Image/video token compression nascent

---

## 10. References

### Key Papers (2023-2024)
- FlashAttention-3 (Dao et al., 2024)
- LLMLingua-2 (Jiang et al., 2024)
- LongLLMLingua (Jiang et al., 2024)
- LongRoPE (Ding et al., 2024)
- vLLM/PagedAttention (Kwon et al., 2023)
- SGLang (Zheng et al., 2024)
- Medusa (Cai et al., 2024)
- EAGLE (Li et al., 2024)
- H2O/SnapKV/PyramidKV (2024)
- BitNet (Microsoft, 2024)
- RecurrentGemma (Google, 2024)

### Industry Blogs & Repos
- NVIDIA TensorRT-LLM: github.com/NVIDIA/TensorRT-LLM
- Together AI: github.com/togethercomputer
- vLLM: github.com/vllm-project/vllm
- SGLang: github.com/sgl-project/sglang
- llama.cpp: github.com/ggerganov/llama.cpp
- LLMLingua: github.com/microsoft/LLMLingua
- Milvus: github.com/milvus-io/milvus

---

*Last Updated: 2026-10-11 | Part of College Project Research Dashboard*