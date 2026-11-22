# Changelog

All notable changes to `pipecat-mnemoverse`.

## [0.1.0] - 2026-11-21

### Added

- `MnemoverseMemoryService`, a Pipecat frame processor that recalls memories for the latest user message, inserts them into the LLM context as one message and saves new messages of the configured roles in the background, each once.
- `get_memories()` for the newest memories of the domain.
- Example voice agent in `examples/voice-agent-memory.py`.
- README: requests per user message against the plan's daily limit, and when to lower `min_relevance`.
- Requires `mnemoverse>=0.5.2,<0.6.0` and `pipecat-ai>=1.15.0,<2`.
- A client passed in as `client=` stays open when the pipeline ends; recall queries and saved messages are kept within the API's character limits; a domain over 100 characters is refused.
- At most `top_k` memories reach the context, also when the server returns more.
- The memory message the service inserts is recognised by its exact text, so a message that happens to open with `system_prompt`, or any message when `system_prompt` is empty, is still saved.
- When the pipeline ends, saves still running get up to 5 seconds (`SAVE_DRAIN_SECS`) to finish before the service closes its client; any left are cancelled with a warning, so the last message of a call is no longer cut off by the close and no new connection pool is opened after it. Error logs name the exception type, also when its message is empty.
