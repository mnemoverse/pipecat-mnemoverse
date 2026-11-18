# pipecat-mnemoverse

Memory for [Pipecat](https://github.com/pipecat-ai/pipecat) agents with [Mnemoverse](https://mnemoverse.com). Before each reply the agent recalls what the user said in earlier sessions; what the user says now is saved for the next one. Memories live in your Mnemoverse account, so the same memory is readable from any other tool connected to it, such as Claude, ChatGPT, Cursor or VS Code.

This integration is maintained by the Mnemoverse team, who run the Mnemoverse memory service.

## Installation

```bash
pip install pipecat-mnemoverse
```

or with uv:

```bash
uv add pipecat-mnemoverse
```

Create an API key at [console.mnemoverse.com](https://console.mnemoverse.com/dashboard/keys) and set it in the environment:

```bash
export MNEMOVERSE_API_KEY=mk_live_...
```

## Usage

Place `MnemoverseMemoryService` after the user context aggregator and before the LLM:

```python
from pipecat_mnemoverse import MnemoverseMemoryService

memory = MnemoverseMemoryService(
    user_id="caller-42",  # memories go to the domain user:caller-42
    params=MnemoverseMemoryService.InputParams(top_k=5, read_timeout_secs=1.0),
)

pipeline = Pipeline(
    [
        transport.input(),
        stt,
        user_aggregator,
        memory,
        llm,
        tts,
        transport.output(),
        assistant_aggregator,
    ]
)
```

On every LLM context frame the service:

1. takes the latest user message and recalls up to `top_k` memories from the domain;
2. puts them into the context as one message (a "developer" message at position 1 by default), replacing the one it added for the previous user message;
3. saves the new messages of the configured roles in the background, each message once.

Recall sits on the path to the LLM, so it waits at most `read_timeout_secs` (1 second by default) and the frame moves on without memories if recall takes longer or fails.

Each new user message costs two requests: one recall before the reply and one write after it. With `"assistant"` in `store_roles`, each reply adds one more write. Reads and writes count together against your plan's daily query limit: the Free plan's 1,000 queries a day is about 500 user messages. Plans and limits are on [mnemoverse.com/pricing](https://mnemoverse.com/pricing).

### Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `api_key` | `MNEMOVERSE_API_KEY` | Mnemoverse API key |
| `user_id` | | The person the agent talks to; memories go to the domain `user:<user_id>` |
| `domain` | | A Mnemoverse domain to use instead, for example `project:support` |
| `InputParams.top_k` | 5 | Memories to recall per user message |
| `InputParams.min_relevance` | 0.3 | Minimum relevance of a recalled memory, 0 to 1 |
| `InputParams.read_timeout_secs` | 1.0 | Longest wait for recall |
| `InputParams.store_roles` | `("user",)` | Roles to save; add `"assistant"` to save the agent's replies |
| `InputParams.system_prompt` | `"Relevant memories from earlier conversations:\n\n"` | Opening of the memory message |
| `InputParams.add_as_system_message` | `True` | Insert memories as a "developer" message instead of a user message |
| `InputParams.position` | 1 | Where in the context the memory message goes |

`min_relevance` drops recalled memories below the threshold. Broad questions, such as "what do you remember about me?", can score below the default 0.3 and come back with nothing; if that happens in your agent, try a lower value such as 0.15.

`get_memories(limit=10)` returns the newest memories of the domain, for example to build a greeting when a call connects.

One API key reads and writes the whole memory of the account it was created in. Give each user their own domain, as `user_id` does, and keep the key on your server. How Mnemoverse handles keys and data: [mnemoverse.com/docs/api/security](https://mnemoverse.com/docs/api/security).

Pass your own `AsyncMnemoClient` as `client=` to share one connection pool between services; the service then leaves it open when the pipeline ends, and closing it is yours. A recall query longer than the API's 5,000 characters is cut to its last 5,000, and a message longer than 10,000 characters is saved as its first 10,000.

## Example

[`examples/voice-agent-memory.py`](examples/voice-agent-memory.py) is a voice agent that greets a returning caller with what it remembers. It needs `MNEMOVERSE_API_KEY`, `OPENAI_API_KEY`, `DEEPGRAM_API_KEY` and `ELEVENLABS_API_KEY`:

```bash
pip install "pipecat-ai[deepgram,elevenlabs,openai,silero,webrtc]" pipecat-mnemoverse python-dotenv
python examples/voice-agent-memory.py
```

Open the local URL it prints, tell the agent something about yourself, end the call, start a new one and ask what it remembers.

## Compatibility

Tested with the `mnemoverse` Python SDK 0.5.2 and Pipecat v1.16.0 on Python 3.11, 3.12 and 3.13, and with Pipecat v1.15.0 on Python 3.11. It needs SDK 0.5.2 or later: in earlier versions a recall cut off by `read_timeout_secs`, or refused with a client error such as 401, 403 or a quota 429, while the client was probing the service after an outage could leave that client refusing every call until the process restarted.

## Issues

[github.com/mnemoverse/pipecat-mnemoverse/issues](https://github.com/mnemoverse/pipecat-mnemoverse/issues/new)

## License

BSD 2-Clause, as Pipecat. See [LICENSE](LICENSE).
