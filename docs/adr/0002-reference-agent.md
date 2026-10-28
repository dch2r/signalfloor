# ADR 0002: A reference agent as the system under test

- Status: Accepted
- Date: 2026-10-28

## Context

signalfloor measures LLM applications, so the project needs a real one to measure. A demo on
made up numbers would not show that the tool works on actual agent output. The application
should also be the kind of thing teams build today: retrieval, tool calls and several steps.

## Decision

1. Build a small retrieval agent in `packages/agent`. It is part of the workspace but never
   published, and its classifier makes PyPI refuse an upload.
2. Use HotpotQA as the task. Every question needs facts from two Wikipedia passages, so a
   single search is not enough and the agent has to search, read and search again. Every
   question has a gold answer, so each case gets an exact match and F1 score with no hand
   labelling.
3. Pool the passages of all loaded questions into one corpus. With 200 questions that is
   about 2,000 passages, so retrieval has to find the right ones among many distractors.
4. Download the dataset at run time and cache it locally. HotpotQA is CC BY-SA 4.0, and
   keeping it out of the repository keeps the code under Apache 2.0 only.
5. Talk to the model through the OpenAI compatible chat API. During development that is a
   local model served by Ollama, which costs nothing. Switching to a hosted model is a
   change of base URL and model name.
6. Tests never call a real model. They use a scripted fake so CI stays fast and free, and
   real runs happen on demand.

## Consequences

- The full loop can be shown end to end: change the agent, run the eval, and let signalfloor
  say whether the change was real.
- A local 1.7B model on a laptop answers in about 10 to 15 seconds, so a 100 question run takes
  around 20 minutes. Eval runs are a deliberate step, not something done on every commit.
- Scores from a small local model will be low in absolute terms. That is fine because the
  point is comparing versions of the agent, not chasing a leaderboard.
