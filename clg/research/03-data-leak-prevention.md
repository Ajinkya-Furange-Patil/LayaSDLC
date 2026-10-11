# Data Leak Prevention: Privacy, Security, Guardrails & Compliance

## Executive Summary

Data leak prevention has moved from "nice-to-have" to **regulatory requirement** (GDPR, HIPAA, EU AI Act, SOC2). The 2024 landscape spans **PII detection/redaction**, **differential privacy**, **programmable guardrails**, **prompt injection defense**, and **automated compliance**.

**Industry State (2024):** Enterprise solutions (Microsoft Presidio, Private AI, Nightfall) dominate PII detection. Guardrails frameworks (NeMo Guardrails, Guardrails AI, Llama Guard) provide programmable safety. The gap: **no local-first, integrated privacy stack** combining detection, guardrails, encryption, and compliance automation.

---

## 1. PII Detection & Redaction

### Entity Types Covered (Standard)

| Category | Examples | Count |
|----------|----------|-------|
| **Personal Identifiers** | Name, Email, Phone, SSN, Passport, Driver License | 15+ |
| **Financial** | Credit Card, Bank Account, IBAN, SWIFT, Crypto Wallet | 10+ |
| **Medical** | MRN, ICD Codes, PHI, DEA Number, NPI | 10+ |
| **Location** | Address, IP, MAC, GPS, ZIP | 5+ |
| **Biometric** | Face, Fingerprint, Voice Print, DNA | 5+ |
| **Credentials** | API Keys, Passwords, Tokens, Certificates | 10+ |
| **Corporate** | Employee ID, Internal Project Codes, Legal Entity | 10+ |

**Total Standard Entities: 50-60+**

### Detection Approaches

| Approach | Accuracy | Latency | Languages | Customizable | Deployment |
|----------|----------|---------|-----------|--------------|------------|
| **Rule-Based (Regex)** | 60-80% | <1ms | All | ✅ Easy | Anywhere |
| **NLP (spaCy/Stanza)** | 85-95% | 10-50ms | 20+ | ✅ Medium | Python |
| **Transformer (BERT/GLiNER)** | **95-99%** | 50-200ms | 50+ | ✅ Medium | Python/ONNX |
| **LLM-Based** | 98%+ | 200-1000ms | 100+ | ✅ Natural Language | API/Local |
| **Hybrid (Production)** | **99%+** | 10-50ms | 50+ | ✅ | Container/Cloud |

### Leading Solutions

| Solution | Type | Entities | Languages | Deployment | License |
|----------|------|----------|-----------|------------|---------|
| **Microsoft Presidio** | Hybrid (Rule+NLP+Transformer) | 50+ | 20+ | Python, Docker, Azure | MIT |
| **Private AI (PrivateGPT)** | Transformer Ensemble | 50+ | **52** | On-prem Docker/K8s | Commercial |
| **Nightfall AI** | Cloud API + ML | 100+ | 30+ | SaaS | Commercial |
| **BigID** | ML Classification | 100+ | 50+ | SaaS/On-prem | Commercial |
| **AWS Macie** | ML + Rules | 50+ | Limited | AWS Only | AWS |
| **Google DLP** | ML + Rules | 100+ | 50+ | GCP Only | GCP |
| **Llama Guard 3** | LLM Classifier | 14 safety categories | 8+ | Local (GGUF) | Llama License |
| **GLiNER** | Transformer (Bidirectional) | Customizable | 50+ | Local (ONNX/PyTorch) | Apache 2.0 |

### Presidio Deep Dive (Open Source Standard)

```python
# Quick start
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

results = analyzer.analyze(text="My SSN is 123-45-6789", language="en")
anonymized = anonymizer.anonymize(text, results)
# Output: "My SSN is <SSN>"
```

**Architecture:**
- **Analyzer**: RecognizerRegistry (50+ built-in) + NLP Engine (spaCy/Transformers)
- **Anonymizer**: Operators (Replace, Mask, Redact, Hash, Encrypt, Custom)
- **Extensibility**: Custom recognizers via regex, deny-lists, or ML models

**Used In Production:** Microsoft 365, Purview, Azure AI, thousands of enterprises.

### GLiNER: Emerging Local Alternative

- **Bidirectional transformer** (DeBERTa-based) for NER
- **Zero-shot**: Define entities in natural language
- **Fast**: ~50ms on CPU, ~10ms on GPU
- **Small**: 100M-1B parameters
- **Apache 2.0**: Commercial-friendly

```python
from gliner import GLiNER
model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
entities = model.predict_entities(text, ["person", "email", "custom_entity"])
```

---

## 2. Differential Privacy for LLMs

### Core Concepts

| Parameter | Meaning | Typical Values |
|-----------|---------|----------------|
| **ε (epsilon)** | Privacy budget (lower = more private) | 0.1 - 10 |
| **δ (delta)** | Failure probability | 10⁻⁵ - 10⁻⁶ |
| **Sensitivity** | Max change one record causes | Clipped gradients |
| **Mechanism** | Noise addition method | Gaussian, Laplace |

### LLM-Specific Methods

| Method | Stage | Privacy | Utility Loss | Complexity |
|--------|-------|---------|--------------|------------|
| **DP-SGD** | Training | Strong | 5-20% | Medium |
| **LoRA + DP** | Fine-tuning | Strong | 2-10% | Low |
| **PATE** | Inference (Teacher Ensemble) | Strong | 10-30% | High |
| **Local DP** | Data Collection | Strongest | 20-50% | Low |
| **Prompt DP** | Inference (Prompt Noise) | Weak-Medium | 5-15% | Low |

### Frameworks

| Framework | Language | DP-SGD | Privacy Accounting | LLM Support |
|-----------|----------|--------|-------------------|-------------|
| **Opacus** | PyTorch | ✅ | RDP, GDP | ✅ (via PEFT) |
| **TensorFlow Privacy** | TensorFlow | ✅ | RDP | ✅ |
| **JAX Privacy** | JAX | ✅ | RDP | ✅ |
| **PySyft/OpenMined** | PyTorch | ✅ | RDP | Federated |

### Practical Guidance

- **Training from scratch**: DP-SGD with ε=1-3, expect 10-20% quality loss
- **Fine-tuning**: LoRA + DP-SGD with ε=0.5-2, expect 2-10% loss
- **Inference only**: PATE or prompt noise (weaker guarantees)
- **Data collection**: Local DP for user-provided data

---

## 3. Guardrails & Output Filtering

### Guardrails Taxonomy

```
Guardrails
├── Input Rails (Pre-LLM)
│   ├── PII Detection/Redaction
│   ├── Prompt Injection Detection
│   ├── Jailbreak Detection
│   ├── Topic/Content Filtering
│   └── Rate Limiting / Quotas
│
├── Output Rails (Post-LLM)
│   ├── PII Leakage Detection
│   ├── Hallucination Detection
│   ├── Factuality Verification
│   ├── Format/Schema Validation
│   ├── Toxicity/Bias Detection
│   └── Competitor/IP Detection
│
├── Dialog Rails (Conversation Flow)
│   ├── State Machines (Colang)
│   ├── Policy Enforcement
│   ├── Escalation Paths
│   └── Context-Aware Responses
│
├── Retrieval Rails (RAG-Specific)
│   ├── Source Verification
│   ├── Citation Validation
│   ├── Relevance Filtering
│   └── Freshness Checks
│
└── Execution Rails (Tool/Action Safety)
    ├── Parameter Validation
    ├── Permission Checks
    ├── Dry-Run Mode
    └── Audit Logging
```

### Framework Comparison

| Framework | Language | Rail Types | Latency | Extensibility | Local-First | License |
|-----------|----------|------------|---------|---------------|-------------|---------|
| **NeMo Guardrails** | Colang/Python | All 5 | <10ms/rail | ✅ Python Actions | ✅ | Apache 2.0 |
| **Guardrails AI** | Python (Pydantic) | Input/Output/Execution | <5ms | ✅ Validators Hub | ✅ | Apache 2.0 |
| **Llama Guard 3** | LLM Classifier | Input/Output | 100-500ms | ❌ Fixed categories | ✅ (GGUF) | Llama License |
| **Guidance (MS)** | Python | Generation Control | Low | ✅ | ✅ | MIT |
| **Custom Rules** | Any | Custom | Minimal | ✅ | ✅ | Any |

### NeMo Guardrails: Most Mature Programmable Framework

**Colang Example:**
```colang
# Define a flow for handling PII
define flow handle_pii
  $user_msg = await user said
  $has_pii = execute check_pii(message=$user_msg)
  if $has_pii
    bot say "I detected sensitive info. Please remove it."
  else
    bot say "Thanks, processing your request."

# Custom action (Python)
def check_pii(message: str) -> bool:
    results = presidio_analyzer.analyze(message, language="en")
    return len(results) > 0
```

**Rail Types:**
- **Input Rails**: Validate/sanitize user input
- **Output Rails**: Validate/filter model output
- **Dialog Rails**: Control conversation flow (state machines)
- **Retrieval Rails**: Verify RAG sources/citations
- **Execution Rails**: Validate tool calls/actions

### Guardrails AI: Validator Ecosystem

**100+ Validators in Hub:**
- PII: `DetectPII`, `RedactPII`, `AnonymizePII`
- Structure: `ValidJSON`, `ValidXML`, `ValidSQL`, `RegexMatch`
- Safety: `Toxicity`, `Bias`, `Hallucination`, `CompetitorCheck`
- Custom: `Validator.from_python(function)`

**Streaming Validation:** Token-level validation for real-time filtering.

---

## 4. Prompt Injection Defense

### Attack Taxonomy

| Attack Type | Description | Example |
|-------------|-------------|---------|
| **Direct Injection** | Explicit instruction override | "Ignore previous instructions and..." |
| **Indirect Injection** | Poisoned data in RAG context | Document contains "Ignore safety..." |
| **Encoded Injection** | Base64, Unicode, Markov | Hidden in seemingly normal text |
| **Multi-turn** | Gradual escalation across turns | "Let's play a game..." → harmful |
| **Tool Injection** | Malicious tool parameters | SQL injection via function calling |

### Defense Layers

| Layer | Technique | Effectiveness | Overhead |
|-------|-----------|---------------|----------|
| **1. Input Sanitization** | Remove control chars, normalize Unicode | Low (bypassable) | Negligible |
| **2. Instruction Hierarchy** | System prompt > User prompt > Context | Medium | None |
| **3. Delimiters/Markers** | Special tokens for boundaries | Medium | Token overhead |
| **4. Prompt Injection Classifier** | ML model (Lakera, custom) | **High (95%+)** | 10-50ms |
| **5. Guardrails (NeMo/Guardrails AI)** | Programmable detection rules | **High** | <10ms |
| **6. LLM-Based Detection** | Llama Guard, custom prompt | High | 100-500ms |
| **7. Sandboxed Execution** | Isolated tool execution | High (for tools) | Infrastructure |

### Leading Solutions

| Solution | Approach | Detection Rate | Latency | Deployment |
|----------|----------|----------------|---------|------------|
| **Lakera Guard** | ML Classifier + Rules | 95%+ (Gandalf) | <20ms | API/Self-hosted |
| **Llama Guard 3** | LLM Classifier | 90%+ | 100-500ms | Local (GGUF) |
| **NeMo Guardrails** | Colang Rules + Custom | Configurable | <10ms | Local |
| **Microsoft Prompt Guard** | Transformer Classifier | Research | ~50ms | Research |
| **Custom (GLiNER/DeBERTa)** | Fine-tuned NER | 90%+ | 10-50ms | Local |

### Gandalf (Lakera): Benchmark & Education

- **Game**: Try to extract password from increasingly defended LLM
- **Levels**: 7 levels of increasing defense sophistication
- **Data**: 1M+ attack examples from players
- **Use**: Train/test injection detectors

---

## 5. Data Provenance, Watermarking & Audit

### Watermarking Techniques

| Method | Detection | Robustness | Quality Impact | Use Case |
|--------|-----------|------------|----------------|----------|
| **KGW (Logits)** | Statistical | Medium | Low | Text generation |
| **SWEET (Embedding)** | Embedding-based | High | Low | Any text |
| **Semantic Watermark** | Meaning-preserving | High | Very Low | High-value content |
| **KTH (Token-Level)** | Per-token | Low | None | Research |

### Audit Trail Requirements (Regulatory)

| Regulation | Audit Requirements |
|------------|-------------------|
| **GDPR Art. 30** | Record of processing activities |
| **HIPAA** | Access logs, breach notification |
| **EU AI Act** | High-risk AI system logs |
| **SOC2** | Security, availability, confidentiality |
| **ISO 27001** | Information security management |

### Automated Compliance Tools

| Tool | Focus | Automation Level | Evidence Collection |
|------|-------|------------------|---------------------|
| **Credo AI** | AI Governance | Workflow + Some Auto | Manual + API |
| **OneTrust** | Privacy/GRC | Workflow | Manual |
| **Vanta** | SOC2/Compliance | Infrastructure Auto | API Integrations |
| **NIST AI RMF** | Risk Management | Framework | Manual |
| **Custom (This Project)** | **Technical Evidence Auto-Generation** | **Full Auto from Logs** | **Automated** |

---

## 6. Federated & Split Learning

### Approaches

| Method | Data Location | Model Updates | Privacy | Communication |
|--------|---------------|---------------|---------|---------------|
| **Federated Learning (FL)** | Client devices | Model weights | Medium | High (rounds) |
| **Split Learning** | Client + Server | Activations/Gradients | High | Medium |
| **Vertical FL** | Different features | Gradients | High | Medium |
| **Local-Only** | Client only | None | Maximum | None |

### Frameworks

- **Flower**: Friendly FL framework, supports LLMs
- **PySyft/OpenMined**: Privacy-preserving ML ecosystem
- **TensorFlow Federated**: Google's FL framework
- **NVIDIA FLARE**: Enterprise FL platform

---

## 7. Compliance Automation: The Gap

### Current State: Manual Questionnaires

```
Auditor asks: "How do you handle PII in LLM outputs?"
Team: *Manually* collects logs, writes evidence, formats report
Time: 40-200 hours per audit
```

### Future State: Technical Evidence Automation

```
System: *Automatically* generates from guardrail/PII/agent logs
- PII Detection Logs → GDPR Art. 30 Evidence
- Guardrail Violations → EU AI Act Incident Reports
- Access Logs → SOC2/HIPAA Access Control Evidence
- Model Cards → EU AI Act Technical Documentation
Time: Minutes per audit
```

### Innovation: Compliance Autopilot (See `innovations.json`)

**Pipeline:**
```
Structured Logs (Guardrails + PII + Agent Actions)
        ▼
Regulation-Control Mapping Matrix (GDPR, HIPAA, SOC2, EU AI Act)
        ▼
Evidence Extractor (Relevant log segments per control)
        ▼
LLM Report Generator (Fills auditor templates)
        ▼
Export: PDF/HTML/JSON for Auditors
```

---

## 8. Local-First Privacy Stack (The Gap)

### What Exists (Cloud)

| Layer | Cloud Solutions |
|-------|-----------------|
| PII Detection | Private AI, Nightfall, AWS Macie, Google DLP |
| Guardrails | NeMo Guardrails (can run local), Guardrails AI |
| Vector DB | Pinecone, Weaviate Cloud, Zilliz Cloud |
| Embeddings | Cohere, Voyage, OpenAI API |
| Compliance | Credo AI, OneTrust, Vanta |

### What's Missing: Integrated Local Stack

```
┌─────────────────────────────────────────────────────────────┐
│                    LOCAL PRIVACY STACK                       │
├─────────────────────────────────────────────────────────────┤
│  █ PII Detection:     Presidio / GLiNER (Local)            │
│  █ Guardrails:        NeMo Guardrails (Local)              │
│  █ Embeddings:        BGE-M3 / Nomic / SmolLM (Local)      │
│  █ Vector Store:      Milvus Lite / Chroma / LanceDB + Encryption │
│  █ LLM Inference:     Ollama / llama.cpp / MLC-LLM         │
│  █ Audit Logs:        Local SQLite + Structured Logging    │
│  █ Compliance:        Auto-generated from logs             │
│  █ Encryption:        SQLCipher / Age / libsodium          │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. Innovation Opportunities

### High Impact + High Feasibility

1. **Real-Time PII Detection in Streaming Outputs**
   - Token-level PII detection during generation
   - Immediate redaction/blocking before user sees

2. **Privacy-First Local RAG** (See `innovations.json`)
   - Fully local pipeline with encryption + guardrails

3. **Compliance Autopilot** (See `innovations.json`)
   - Auto-generate DPIA, SOC2 evidence, EU AI Act docs

### High Impact + Medium Feasibility

4. **Context-Aware Privacy Policies**
   - Role-based: Doctor sees PHI, Billing sees codes only
   - Dynamic redaction based on user context

5. **Local-First Prompt Injection Defense**
   - GLiNER/DeBERTa classifier running on-device
   - No cloud API calls for security

### Research Frontiers

6. **Differential Privacy for RAG**: Private retrieval + generation
7. **Zero-Knowledge Proofs for LLM Execution**: Verify correct model ran
8. **Automated Red-Teaming**: Continuous adversarial testing
9. **Privacy-Preserving Fine-Tuning**: Local LoRA + DP-SGD

---

## 10. Benchmarks & Metrics

See `benchmarks.json` for detailed numbers. Key aggregates:

| Task | Presidio | Private AI | GLiNER | Llama Guard 3 |
|------|----------|------------|--------|---------------|
| **PII F1 (English)** | 95% | 99% | 92% | N/A |
| **PII F1 (Multilingual)** | 85% | 99% | 88% | N/A |
| **Latency (per doc)** | <50ms | <50ms | ~50ms | 100-500ms |
| **Injection Detection** | N/A | N/A | N/A | 90%+ |
| **Guardrails Overhead** | N/A | N/A | N/A | <10ms/rail |

---

## 11. Research Gaps & Future Directions

1. **Unified Local Privacy Stack**: No integrated solution exists
2. **Streaming PII Detection**: Real-time redaction during generation
3. **Technical-to-Regulatory Translation**: Auto-map logs to compliance controls
4. **Adaptive Privacy**: Context-aware policies (role, jurisdiction, data sensitivity)
5. **Private RAG**: Encrypted vectors + private retrieval + secure generation
6. **Continuous Compliance**: Real-time drift detection from regulatory changes
7. **Cross-Border Data Flows**: Automated Schrems II / adequacy assessments

---

## 12. References

### Key Papers & Resources
- Presidio: github.com/microsoft/presidio
- NeMo Guardrails: github.com/NVIDIA/NeMo-Guardrails
- Guardrails AI: github.com/guardrails-ai/guardrails
- Llama Guard 3: ai.meta.com/blog/llama-3-1-llama-guard-3/
- Lakera Gandalf: lakera.ai/gandalf
- GLiNER: github.com/urchade/GLiNER
- Opacus (DP-SGD): github.com/pytorch/opacus
- Differential Privacy for LLMs surveys (2023-2024)
- EU AI Act Technical Standards (2024)
- NIST AI Risk Management Framework

### Industry Blogs
- Microsoft Presidio Blog
- NVIDIA NeMo Guardrails Blog
- Guardrails AI Blog
- Lakera Blog
- Private AI Blog
- Credo AI Blog

---

*Last Updated: 2026-10-11 | Part of College Project Research Dashboard*