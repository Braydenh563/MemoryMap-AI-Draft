# Choosing an AI model

MemoryMap works without any AI at all: you just get keyword search and
`Uncategorised` filing. For auto-filing and chat answers, install
[Ollama](https://ollama.com) and pull a model:

```bash
ollama pull llama3.2
```

Any Ollama model works, and you can switch between them in-app from
**Settings → Models** without restarting: the same list is there, with a
download button next to each, and each model's own metadata says whether
it can use tools, think, or see images.

**Sorted by size, not by quality**, because the real question is what your
machine can run. Start at the top of the tier that fits your RAM; if
answers feel slow, drop a tier.

Every size below is the download for Ollama's default tag, checked against
the library rather than estimated. **The download is not the memory you
need**: leave room for the runtime, the context window, and the operating
system. Budget roughly 1.3 to 1.8 times the file size, more for long
contexts.

## Runs on almost anything, no GPU needed

| Model | Size | Why |
| :-- | :-- | :-- |
| `qwen3.5:0.8b` | 1.0 GB | Filing and classification only. Too small for chat |
| `llama3.2` | 2.0 GB | **The default.** Fast, and a good first choice |
| `granite4.1:3b` | 2.1 GB | Strong instruction-following at a small size |
| `phi4-mini` | 2.5 GB | Compact, concise answers, decent at code |
| `qwen3.5:2b` | 2.7 GB | The lightest one genuinely worth chatting to |
| `qwen3.5:4b` | 3.4 GB | Follows instructions closely, good for agent mode |

## 8 GB of RAM, or any modern GPU: the real step up in answer quality

| Model | Size | Why |
| :-- | :-- | :-- |
| `deepseek-r1:7b` | 4.7 GB | Reasoning-heavy prompts, when slower answers are fine |
| `qwen2.5-coder:7b` | 4.7 GB | Code and structured text. A specialist, not a chat model |
| `llama3.1:8b` | 4.9 GB | Better reasoning, and reliable tool calls in agent mode |
| `qwen3:8b` | 5.2 GB | The previous generation's thinking model, still solid |
| `qwen3.5:9b` | 6.6 GB | Best tool use at this size. Thinks, so slower per answer |
| `mistral-nemo` | 7.1 GB | Long-document work, a large context window |
| `gemma4:e2b` | 7.2 GB | See the note on `e` sizes below. Fast for its download |
| `gemma4:12b` | 7.6 GB | Long-form writing and summarising |
| `llama3.2-vision` | 7.8 GB | Reads images, at 11B |

**`e2b` and `e4b` do not mean 2 GB and 4 GB.** The `e` is *effective*
parameters: the model is built so that only part of it does the work for a
given token, which is why it answers faster than its size suggests. The
whole thing still downloads and still has to be held in memory. `gemma4:e2b`
is a 7.2 GB download and `gemma4:e4b` is 9.6 GB, so neither is a small-laptop
model despite the name. (Earlier versions of this page said 3.5 GB and 5 GB.
They were wrong.)

## 16 GB and up

| Model | Size | Why |
| :-- | :-- | :-- |
| `gemma4:e4b` | 9.6 GB | Better writing than anything above it here |
| `qwen3.5:27b` | 17 GB | Strong general reasoning and coding |
| `gemma4:26b` | 19 GB | The 26B Gemma. `gemma4:26b-a4b` is not a tag; this is |
| `qwen3:30b-a3b` | 19 GB | Mixture-of-experts: 30B stored, 3B active per token |
| `gemma4:31b` | 20 GB | Large dense multimodal model |
| `qwen3.5:35b-a3b` | 24 GB | The most capable here, and still quick. Needs ~32 GB |

**Mixture-of-experts, and why `a3b` is not a small model.** A tag like
`35b-a3b` holds 35B of weights and computes with about 3B of them at a time.
It downloads and loads like a 35B model and *answers* at roughly the speed of
a 3B one. The active count buys you speed, never memory. If you have the
memory, these are the best answers on this page.

Anything larger (Qwen's 122B-A10B and 397B-A17B families, DeepSeek's big MoE
releases, 70B and up) is a multi-GPU or workstation choice. They are fine
models and poor defaults for a notebook app whose work is retrieval, filing
and chat.

## Tools, thinking and vision are three different things

- **Tool calling** lets the model ask for an action. It does not make the
  model good at deciding which one: small models call the wrong tool, or
  call it and ignore the result.
- **Thinking** spends extra tokens reasoning before answering. Better on
  hard questions, slower and more expensive on easy ones.
- **Vision** accepts images. The model, the backend and the app all have to
  agree, and a vision model usually ships as two files: the model and a
  separate `mmproj` projector.

**For agent mode**, prefer a model Ollama reports as tool-capable. Settings →
Models shows this under "Can use tools", read from the model rather than
guessed. `qwen3.5:9b` and `llama3.1:8b` are the most reliable of the list
above; the smallest models can use tools but forget to.

**A small model on a large notebook is fine.** MemoryMap never stuffs the
whole notebook into one prompt: it retrieves a handful of relevant notes
first, so prompt size stays small regardless of how many notes you have. A
smaller model reasons less well about what it is given; it does not choke on
notebook size. If answers are slow, drop a tier or shorten the context
before assuming the notebook is too big.

## Community quants, and the mirrors on this project's account

[HauhauCS](https://huggingface.co/HauhauCS) publishes `Q*_K_P` imatrix
quantisations: custom, per-model builds that spend their bits on the weights
that matter most for that model. They are usually a little larger than the
standard quantisation at the same level and hold up better than it does.
Treat "a quant level better" as a rule of thumb rather than a benchmark.

`Q6_K_P` is often too big for the machine that wants it, so
[braydenh563](https://huggingface.co/braydenh563) mirrors the smaller ones
under names Ollama will actually pull:

- `Q4_K_P` is renamed `Q4_K_M`.
- `Q5_K_P` is renamed `Q5_K_M`.
- `Q6_K_P` keeps its name, which Ollama accepts as-is.

The Qwen3.6 mirror's own card puts it plainly: "Q4_K_M is still Q4_K_P but
just renamed so that I can pull it directly into ollama." This is a
filename convention for compatibility, not a claim that the standard `K_M`
quantiser produced the file. Renaming the quant is also a separate thing
from removing vision: the `-Text` mirrors drop the `mmproj` and cannot read
images, whichever quant they carry.

Sizes below are the real file sizes in those repositories.

| Mirror | Q4 | Q5 | Q6 | Vision | Good for |
| :-- | --: | --: | --: | :-- | :-- |
| [Gemma 4 E2B](https://huggingface.co/braydenh563/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive-Ollama) | 3.4 GB | 3.7 GB | 3.9 GB | 940 MB mmproj | Filing, quick chat, CPU boxes |
| [Gemma 4 E4B](https://huggingface.co/braydenh563/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Ollama) | 5.4 GB | 5.8 GB | 6.3 GB | 945 MB mmproj | The practical 8 to 16 GB pick |
| [Gemma 4 26B-A4B](https://huggingface.co/braydenh563/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-Ollama) | 16.9 GB | 19.3 GB | 22.8 GB | 1.2 GB mmproj | Writing, roleplay, long context |
| [Qwen3.6 35B-A3B](https://huggingface.co/braydenh563/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Ollama) | 23.4 GB | 28.0 GB | 30.6 GB | 899 MB mmproj | Coding, tool use, agent work |
| [Qwen3.6 35B 1M + MTP](https://huggingface.co/braydenh563/Qwen3.6-35B-Uncensored-HauhauCS-1M-MTP-Ollama) | 21.7 GB | | | 899 MB mmproj | A 1M context ceiling |

Text-only mirrors exist for the
[Gemma 4 E2B](https://huggingface.co/braydenh563/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive-Ollama-Text),
[Gemma 4 E4B](https://huggingface.co/braydenh563/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Ollama-Text),
[26B-A4B](https://huggingface.co/braydenh563/Gemma4-26B-A4B-Uncensored-HauhauCS-Bal-Ollama-Text)
and
[35B-A3B](https://huggingface.co/braydenh563/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggr-Ollama-Text)
lines. Take one when MemoryMap is only handling text: it is a smaller
download with nothing to configure.

Two things worth knowing before you pick from this table. The Gemma 26B-A4B
card aims at writing, roleplay and steady long-context output, and says
Qwen3.6 is the stronger choice for agentic coding and tool use. And the 1M
package grafts an official MTP speculative-decoding layer on: imported into
Ollama it loads the tensors but does not currently go faster for it, so use
llama.cpp with draft-MTP if that speedup is the reason you want it. Treat
"1M context" as a ceiling rather than a promise, too: the card puts a 1M f16
KV cache at about 44 GB, with roughly 262K resident on a 32 GB card.

## Vision models

A vision model is normally two files: the language model, and a projector
(`mmproj`) that turns an image into something the model can read. Missing
the projector is the usual reason a "vision" model silently cannot see.

| Model | Size | Why |
| :-- | :-- | :-- |
| [`LiquidAI/LFM2.5-VL-1.6B-GGUF`](https://huggingface.co/LiquidAI/LFM2.5-VL-1.6B-GGUF) | ~1 GB | The smallest thing that genuinely reads an image |
| `llama3.2-vision` | 7.8 GB | One `ollama pull`, no projector to wire up |
| [Qwen3-VL GGUF](https://huggingface.co/Qwen) | varies | The strongest general multimodal family here |
| Gemma 4 E4B, above | 5.4 GB | Images and audio, on a laptop |

Ollama's own vision tags are the easy route. The GGUF releases are stronger
and need the projector supplied by hand.

## OCR models

OCR models are not vision chat models: they are tuned to transcribe, keep
layout, read tables, and emit Markdown or boxes. Run one as a separate
extraction step and feed its text into MemoryMap the way you would any
other note.

| Model | Why |
| :-- | :-- |
| [`ggml-org/GLM-OCR-GGUF`](https://huggingface.co/ggml-org/GLM-OCR-GGUF) | Small, multilingual, good at tables. The easiest to run |
| [`ggml-org/DeepSeek-OCR-GGUF`](https://huggingface.co/ggml-org/DeepSeek-OCR-GGUF) | Higher accuracy on documents and screenshots |
| [`sahilchachra/Unlimited-OCR-GGUF`](https://huggingface.co/sahilchachra/Unlimited-OCR-GGUF) | Long documents to Markdown. Needs its fp16 projector |

GLM-OCR through llama.cpp is one line:

```bash
llama-server -hf ggml-org/GLM-OCR-GGUF
```

Use `--temp 0` for OCR: you want transcription, not invention.

## Not using Ollama?

**Settings → Models → Model backend** points MemoryMap at anything that
serves the OpenAI API instead: **LM Studio**, **llama.cpp**'s server,
**Jan** and **vLLM** are all the same choice, differing only by address.
Pick "LM Studio / llama.cpp / Jan / vLLM", leave the address blank for the
usual one (`localhost:1234/v1`) or fill in your own port, and press
Connect. It applies straight away, no restart, and nothing to put in
`.env`.

Everything works the same on either backend: tool calls, streaming,
thinking models, and the token counts on each message. Two differences
worth knowing: downloading models is an Ollama feature (every other server
is handed a model you already have, so that panel hides itself), and Ollama
is the only one that lets the app *ask* for a context window. Elsewhere the
window is whatever the server was started with, so MemoryMap reads it and
rations the prompt to fit.

Pulling a GGUF from Hugging Face into Ollama needs a compatible
architecture, a tokenizer, a chat template, and the projector if it sees.
`Q4_K_M` is the usual compromise, `Q5_K_M` and `Q6_K` buy quality for size,
`Q8_0` is for when memory is plentiful and `F16` is for GPUs. Check the
licence while you are there.

## Embeddings

The **embedding** model for semantic search (`BAAI/bge-small-en-v1.5`)
downloads itself the first time it's needed. Settings → Models names
whichever one is actually loaded. No Ollama pull required, and you can
switch to an Ollama embedding model later, with an automatic re-index.

An embedding model is not a chat model, and changing one does not change
the other. A bigger instruct model will not improve search.

## If you want a path rather than a table

1. `ollama pull llama3.2`, and see whether it is already enough.
2. Too weak: `qwen3.5:4b`, then `qwen3.5:9b` if you have the memory.
3. For agent mode, check "Can use tools" in Settings, then test it on a
   real multi-step task before trusting it.
4. For images on a laptop, Gemma 4 E4B with its `mmproj`, or LFM2.5-VL.
5. At 24 to 32 GB, Gemma 4 26B-A4B or Qwen3.6 35B-A3B at Q4 or Q5.
6. For OCR, run GLM-OCR separately and paste the text in.

Tags and sizes move. Before relying on a number here, check the
[Ollama library](https://ollama.com/library) or the model's own
[Hugging Face](https://huggingface.co/models) card.
