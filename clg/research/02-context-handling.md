# Context Handling: Long-Context, RAG, Memory & Multi-Document Reasoning

## Executive Summary

Context handling has evolved from "fit more tokens" to "intelligently manage, retrieve, and reason over information." The 2024 frontier combines **native long-context models (1M-2M tokens)**, **advanced RAG (Graph, Agentic, Hybrid)**, and **persistent memory systems** to create AI that truly understands context over time.

**Industry State (2024):** Gemini 1.5 achieves 2M tokens natively. RAG has matured into Graph RAG + Agentic RAG. Memory systems (Zep, MemGPT, Letta) enable cross-session persistence. The gap: **no unified, local-first, privacy-preserving context stack**.

---

## 1. Long-Context Architectures

### Context Window Evolution

| Model | Context Window | Architecture | Year |
|-------|---------------|--------------|------|
| GPT-3 | 2K | Standard Transformer | 2020 |
| GPT-4 | 32K | RoPE + scaling | 2023 |
| LLaMA 2 | 4K | RoPE | 2023 |
| **LLaMA 3.1** | **128K** | **RoPE + LongRoPE** | **2024** |
| **Mistral Large 2** | **128K** | **SWA + GQA** | **2024** |
| **Phi-3.5** | **128K** | **LongRoPE/YaRN** | **2024** |
| **Gemini 1.5 Pro** | **1M (2M preview)** | **MoE + RoPE scaling** | **2024** |
| **Claude 3.5** | **200K** | **Undisclosed** | **2024** |

### Extension Techniques

| Technique | Principle | Max Extension | Fine-tuning Cost | Used By |
|-----------|-----------|---------------|------------------|---------|
| **RoPE Scaling (Linear)** | Scale frequency base | 4-8x | Low | LLaMA 2, Mistral |
| **YaRN** | Temperature + scaling | 64x | Low (1K steps) | LLaMA, Mistral, Qwen |
| **LongRoPE** | Progressive + rescaling | 512x+ | Medium (10K steps) | Phi-3.5, LLaMA 3.1 |
| **ALiBi** | Positional bias | Unlimited (theoretical) | None (arch change) | MPT, BLOOM |
| **xPos** | Decaying rotary | 8x+ | Low | Some research models |
| **Ring Attention** | Distributed attention | Millions | High (distributed) | Research |

### Needle-in-Haystack Results (2024)

| Model | 128K | 1M | 2M |
|-------|------|-----|-----|
| **Gemini 1.5 Pro** | 100% | **99.7%** | **99.2%** |
| LLaMA 3.1 405B | 100% | N/A | N/A |
| GPT-4o | 100% | N/A | N/A |
| Claude 3.5 Sonnet | 100% | N/A | N/A |
| Phi-3.5 | 99%+ | N/A | N/A |

**Key Insight:** Gemini 1.5 is the only model with **near-perfect retrieval at 1M+ tokens** due to MoE architecture + massive training context.

---

## 2. RAG Systems: Evolution & Taxonomy

### RAG Generations

```
RAG v1: Naive RAG
├── Chunk → Embed → Retrieve → Generate
├── Problems: Hallucination, no reasoning, fixed retrieval
│
RAG v2: Advanced RAG
├── Hybrid Search (Dense + Sparse)
├── Reranking (Cross-encoder)
├── Query Rewriting/Expansion
├── Metadata Filtering
│
RAG v3: Modular RAG (2024)
├── Graph RAG (Knowledge Graphs)
├── Agentic RAG (Autonomous Agents)
├── Multi-Modal RAG
├── Adaptive RAG (Route by query type)
│
RAG v4: Contextual RAG (Emerging)
├── Context-aware retrieval
├── Self-correcting loops
├── Cross-document reasoning
└── Persistent memory integration
```

### Retrieval Methods Comparison

| Method | Recall@10 | Latency | Best For | Frameworks |
|--------|-----------|---------|----------|------------|
| **Dense (BGE/VF/Embed)** | 70-85% | 10-50ms | Semantic similarity | All |
| **Sparse (BM25/SPLADE)** | 60-75% | 5-20ms | Keywords, exact match | Weaviate, Elastic |
| **Hybrid (Dense + Sparse)** | **85-95%** | 20-100ms | **General purpose** | Weaviate, Pinecone, Milvus |
| **Reranked (Cohere/Rerank)** | **90-98%** | +50-200ms | High-stakes QA | Cohere, Voyage, Jina |
| **Graph RAG** | 95%+ (complex) | 200-500ms | Multi-hop, thematic | LlamaIndex, Weaviate |
| **Agentic RAG** | Variable | 500ms-5s | Complex reasoning | LangGraph, AutoGen |

### Reranking Deep Dive

| Reranker | Model Size | Latency (100 docs) | Quality | Multilingual |
|----------|------------|-------------------|---------|--------------|
| **Cohere Rerank 3.5** | API | <100ms | **SOTA** | 100+ langs |
| **Voyage Rerank 2** | API | <100ms | SOTA | 100+ langs |
| **Jina Reranker** | 130M/300M | 50-150ms | Strong | 100+ langs |
| **BGE-Reranker** | 300M | 100-300ms | Strong | 100+ langs |
| **MonoT5/T5-XXL** | 3B/11B | 500ms-2s | Strong | Limited |

**Recommendation:** Use Cohere/Voyage API for production; BGE/Jina for local deployment.

---

## 3. Graph RAG: Knowledge Graphs for Reasoning

### Microsoft Graph RAG (Edge et al., 2024)

**Pipeline:**
1. **Entity/Relation Extraction** → LLM extracts from documents
2. **Knowledge Graph Construction** → Entities as nodes, relations as edges
3. **Community Detection** → Leiden algorithm for hierarchical communities
4. **Community Summaries** → LLM generates summaries per community
5. **Query-Time** → Global (community) + Local (entity) search

**Results:** 20-40% better on complex multi-hop vs vector-only RAG.

### Implementations

| Framework | Graph Construction | Query Engine | Open Source |
|-----------|-------------------|--------------|-------------|
| **LlamaIndex** | PropertyGraphIndex | GraphRAGQueryEngine | ✅ |
| **Weaviate** | GraphQL + Vector | Hybrid Graph/Vector | ✅ |
| **LangChain** | GraphDocument | GraphCypherQAChain | ✅ |
| **Neo4j + LLM** | Cypher + LLM | Text2Cypher | ✅ |
| **Microsoft GraphRAG** | Custom pipeline | Global/Local search | ✅ (partial) |

### When to Use Graph RAG

✅ Complex multi-hop questions ("How does X relate to Y through Z?")
✅ Thematic analysis ("What are the main themes across all docs?")
✅ Entity-centric queries ("Tell me everything about Entity X")
❌ Simple fact lookup (vector search is faster/cheaper)
❌ Real-time requirements (graph construction is slow)

---

## 4. Agentic RAG: Autonomous Retrieval Agents

### Architecture

```
User Query
    ▼
┌─────────────────────────────────────┐
│        PLANNER AGENT                │
│  (Decomposes query, plans steps)    │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│       RETRIEVER AGENTS              │
│  • Vector Search Agent              │
│  • Graph Search Agent               │
│  • Web Search Agent                 │
│  • Tool/API Agent                   │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│       CRITIC / REFLECTOR            │
│  (Evaluates completeness, hallucination) │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│       SYNTHESIZER AGENT             │
│  (Generates final answer + citations) │
└─────────────────────────────────────┘
```

### Frameworks Comparison

| Framework | Approach | State Management | Local LLM Support | Learning Curve |
|-----------|----------|------------------|-------------------|----------------|
| **LangGraph** | Graph-based, cyclic | ✅ Checkpointing | ✅ Excellent | Medium |
| **AutoGen** | Conversational agents | ✅ GroupChat | ✅ Good | Low-Medium |
| **CrewAI** | Role-based crews | ⚠️ Limited | ✅ Good | Low |
| **LlamaIndex Agents** | Query engine tools | ⚠️ Basic | ✅ Excellent | Low |
| **Agno** | Type-safe, functional | ✅ Built-in | ✅ Excellent | Low |

### Key Insight: LangGraph is production standard for complex agentic RAG due to:
- Explicit state management with checkpointing
- Cyclic graphs for self-correction loops
- Excellent local LLM integration (Ollama, llama.cpp)
- LangSmith observability

---

## 5. Memory Systems: Beyond Context Window

### Memory Taxonomy

```
Memory Systems
├── Short-term (In-Context)
│   ├── Conversation Buffer
│   ├── Summary Memory
│   └── Sliding Window
│
├── Long-term (Persistent)
│   ├── Episodic (Events/Conversations)
│   │   ├── Zep (Temporal KG)
│   │   ├── MemGPT / Letta
│   │   └── LangChain ConversationMemory
│   ├── Semantic (Facts/Knowledge)
│   │   ├── Vector Store + Consolidation
│   │   ├── Graph Memory
│   │   └── Fact Extraction Pipelines
│   └── Procedural (Skills/Patterns)
│       ├── Few-shot Examples
│       ├── Tool Usage Patterns
│       └── User Preference Learning
```

### Leading Systems

| System | Type | Persistence | Local-First | Encryption | Consolidation |
|--------|------|-------------|-------------|------------|---------------|
| **Zep** | Episodic (Temporal KG) | PostgreSQL | ❌ Cloud | ⚠️ Optional | LLM-based |
| **MemGPT / Letta** | Episodic + Semantic | SQLite/PostgreSQL | ✅ | ❌ | LLM-based |
| **LangChain Memory** | All types | In-memory/Redis | ✅ | ❌ | Manual |
| **LlamaIndex Memory** | Semantic + Episodic | Vector/Graph | ✅ | ❌ | LLM-based |
| **Custom (This Project)** | **All + Encrypted** | **SQLCipher** | ✅ | ✅ | **LLM-based** |

### Zep Architecture (State of the Art)

```
User Message
    ▼
┌─────────────────────────────────────┐
│      EXTRACTION LAYER               │
│  • Entity/Relation Extraction       │
│  • Fact Extraction                  │
│  • Temporal Anchoring               │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│      TEMPORAL KNOWLEDGE GRAPH       │
│  • Nodes: Entities, Events, Facts   │
│  • Edges: Relations, Temporal       │
│  • Versioning: Valid time intervals │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│      RETRIEVAL LAYER                │
│  • Graph Traversal                  │
│  • Vector Search (Embeddings)       │
│  • Time-travel Queries              │
└─────────────────────────────────────┘
```

---

## 6. Multi-Document Reasoning

### Challenges

1. **Cross-Document Coreference**: Same entity, different names
2. **Contradiction Detection**: Docs disagree
3. **Citation/Attribution**: Which doc supports claim?
4. **Synthesis**: Combine info from 10+ docs
5. **Scalability**: 100+ docs in context

### Solutions

| Approach | Method | Pros | Cons |
|----------|--------|------|------|
| **Long Context** | Stuff all in context | Simple, full attention | Limited to 128K-2M |
| **RAG + Rerank** | Retrieve top-K, rerank | Scalable | Loses global context |
| **Graph RAG** | Build KG from all docs | Global reasoning | Slow build |
| **Map-Reduce** | Summarize each → combine | Handles arbitrary scale | Loses detail |
| **Iterative** | Agent loops retrieve→read | Adaptive | Latency |
| **Cross-Encoder** | Joint encoding | Best quality | O(n²) compute |

### Best Practice (2024)

**Hybrid: Graph RAG + Agentic Retrieval**
1. Build knowledge graph from document corpus (offline)
2. Agentic retriever plans multi-step search
3. Cross-encoder reranks final candidates
4. Synthesizer generates with citations

---

## 7. Context Window Management Strategies

### Dynamic Allocation

| Strategy | Description | Use Case |
|----------|-------------|----------|
| **Priority-Based** | Score chunks by relevance, keep top-K | RAG with long context |
| **Sliding Window** | Keep recent N tokens | Chat, streaming |
| **Hierarchical** | Recent=full, older=summarized | Long conversations |
| **Importance Scoring** | LLM rates chunk importance | Knowledge-intensive |
| **Compression** | LLMLingua compress old context | Very long context |

### Implementation (vLLM/SGLang)

```python
# vLLM: Automatic prefix caching
# SGLang: RadixAttention (tree-based prefix cache)
# Both: Zero-code, handles shared prefixes automatically
```

---

## 8. Industry Implementations

### Enterprise RAG Stacks

| Company | Product | Key Features | Pricing |
|---------|---------|--------------|---------|
| **Cohere** | North / Command R+ | RAG-optimized LLM, Rerank, Embed | API |
| **Pinecone** | Serverless + Assistant | Managed vector DB, RAG-in-a-box | Serverless |
| **Weaviate** | Cloud + Verba | Graph RAG, Hybrid, PII, Open Source | Freemium |
| **LlamaIndex** | LlamaCloud + LlamaParse | Managed parsing, Graph RAG | Freemium |
| **LangChain** | LangGraph + LangSmith | Agentic RAG, Observability | Freemium |
| **NVIDIA** | NeMo Retriever | End-to-end RAG pipeline | Enterprise |
| **Elastic** | ELSER + RAG Templates | Sparse vectors, Hybrid search | Freemium |

### Open Source Leaders

- **Vector DBs**: Milvus, Weaviate, Chroma, LanceDB, Qdrant
- **Frameworks**: LangChain, LlamaIndex, LangGraph, Haystack
- **Embeddings**: BGE, E5, GTE, Nomic, Jina (all open)
- **Rerankers**: BGE-Reranker, Jina-Reranker, MonoT5

---

## 9. Innovation Opportunities

### High Impact + High Feasibility

1. **Privacy-First Local RAG** (See `innovations.json`)
   - Fully local: embeddings, vector search, PII, guardrails
   - Encrypted vector store + SQLCipher
   - Zero cloud dependency

2. **Context-Aware Memory Consolidation**
   - LLM summarizes/consolidates memories based on query patterns
   - Importance scoring personalized per user

### High Impact + Medium Feasibility

3. **Cross-Session Encrypted Memory** (See `innovations.json`)
   - Persistent across restarts
   - User-controlled keys, GDPR delete

4. **Proactive Context Prefetching**
   - Predict next query from user behavior
   - Pre-load relevant context

### Research Frontiers

5. **Multimodal Context** (Text + Code + Images + Audio)
6. **Personalized Context Ranking** (Learn user preferences)
7. **Contextual Compression** (Compress based on current query)
8. **Reasoning Traces as Context** (Store CoT for future use)

---

## 10. Benchmarks & Metrics

See `benchmarks.json` for detailed numbers. Key aggregates:

| Task | Vector Only | Hybrid | +Rerank | Graph RAG | Agentic RAG |
|------|------------|--------|---------|-----------|-------------|
| **Simple QA** | 75% | 85% | 90% | 88% | 92% |
| **Multi-hop** | 45% | 60% | 70% | **85%** | **88%** |
| **Thematic** | 30% | 40% | 50% | **80%** | **82%** |
| **Latency** | 50ms | 100ms | 200ms | 500ms | 2-5s |

---

## 11. Research Gaps & Future Directions

1. **Unified Context Stack**: No single system handles long-context + RAG + memory + privacy
2. **Local-First Enterprise RAG**: Cloud dependency is blocker for regulated industries
3. **Adaptive Retrieval**: Route query to optimal strategy (vector/graph/agentic) automatically
4. **Memory Consolidation**: LLM-based compression of long-term memories
5. **Cross-Modal Context**: Unified representation for text, code, images, audio
6. **Real-Time Knowledge Updates**: Incremental graph/vector updates without rebuild

---

## 12. References

### Key Papers (2023-2024)
- RAG Survey (Gao et al., 2024)
- Graph RAG (Edge et al., 2024)
- LongRoPE (Ding et al., 2024)
- Gemini 1.5 Technical Report (2024)
- Agentic RAG surveys (LangChain, LlamaIndex blogs)
- Zep/MemGPT/Letta papers
- Cohere Rerank 3.5 / Voyage Rerank 2 benchmarks

### Industry Resources
- LlamaIndex Graph RAG: docs.llamaindex.ai/en/stable/examples/property_graph/
- Weaviate Graph RAG: weaviate.io/blog/graph-rag
- LangGraph Agentic RAG: langchain-ai.github.io/langgraph/tutorials/rag/
- Cohere RAG Guide: docs.cohere.com/docs/rag
- Voyage AI Benchmarks: blog.voyageai.com

---

*Last Updated: 2026-10-11 | Part of College Project Research Dashboard*