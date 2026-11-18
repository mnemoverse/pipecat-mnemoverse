# Changelog

All notable changes to `pipecat-mnemoverse`.

## [0.1.0] - Unreleased

### Added

- `MnemoverseMemoryService`, a Pipecat frame processor that recalls memories for the latest user message, inserts them into the LLM context as one message and saves new messages of the configured roles in the background, each once.
- `get_memories()` for the newest memories of the domain.
- Example voice agent in `examples/voice-agent-memory.py`.
- README: requests per user message against the plan's daily limit, and when to lower `min_relevance`.
