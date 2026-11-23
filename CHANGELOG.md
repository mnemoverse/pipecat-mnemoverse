# Changelog

All notable changes to `pipecat-mnemoverse`.

## [Unreleased]

### Changed

- Building the package (from the repository or the sdist) uses `hatchling==1.33.0` exactly instead of any `hatchling>=1.24`.

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
- README and docstrings: the service saves messages to the same domain it recalls from, so a domain shared by several callers carries one caller's words to the others; `store_roles=()` reads a domain without saving to it.
- README: the example's install command includes the `daily` and `runner` extras of `pipecat-ai`, which the example imports.
- Each recalled memory takes one numbered line of the memory message: its whitespace, line breaks included, collapses to single spaces and `<` `>` become `‹` `›`, as in langchain-mnemoverse, so one memory cannot read as several.
