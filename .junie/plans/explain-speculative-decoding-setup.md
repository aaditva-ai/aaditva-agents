---
sessionId: session-260831-161243-2suf
---

# Requirements

### Overview & Goals
Explain how speculative decoding benchmarking was executed using the LM Studio CLI (`lms.exe`) and provide clear instructions for replicating the setup via CLI or using same-family model pairs in the LM Studio GUI.

### Scope
- **In Scope**: Explanation of CLI vs. GUI speculative model loading, command execution details, and tokenizer compatibility recommendations.
- **Out of Scope**: Source code modifications or external model quantization.

# Technical Design

### Current Implementation
LM Studio CLI (`lms.exe`) allows programmatically passing speculative decoding flags (`--speculative-draft-simple` and `--speculative-draft-model`), bypassing GUI dropdown filters that check strict tokenizer compatibility.

### Proposed Approach
1. **CLI Execution**: Use `lms.exe load` to explicitly pair target models with `qwen2.5-0.5b-instruct`.
2. **GUI Configuration**: Use same-tokenizer model pairings (such as `qwen/qwen2.5-7b-instruct` with `qwen2.5-0.5b-instruct`) so the GUI dropdown populates the draft model automatically.

# Delivery Steps

###   Step 1: Document LM Studio CLI speculative decoding workflow
Provide concrete instructions for loading target and draft models using `lms.exe`.

- Detail `lms load` parameters including `--speculative-draft-simple` and `--speculative-draft-model`.
- Document local model identifiers stored in LM Studio cache (`qwen2.5-0.5b-instruct` and `google/gemma-4-e4b`).

###   Step 2: Document GUI-compatible model configurations
Provide instructions for configuring matching tokenizer pairs within the LM Studio GUI.

- Highlight tokenizer compatibility rules (e.g., Qwen 2.5 7B target with Qwen 2.5 0.5B draft).
- Provide troubleshooting steps for API verification at `http://localhost:1234`.