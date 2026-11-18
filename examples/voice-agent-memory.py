#
# Copyright (c) 2026, Mnemoverse
#
# SPDX-License-Identifier: BSD-2-Clause
#

"""Voice agent that remembers the caller, with Pipecat and Mnemoverse.

The agent recalls what the caller said in earlier calls before each reply and
saves what they say now, in the Mnemoverse domain ``user:<USER_ID>``. The same
memory is readable from any other tool connected to the same Mnemoverse
account. Tested with Pipecat v1.15.0.

Requirements:
    - Mnemoverse API key (https://console.mnemoverse.com/dashboard/keys)
    - OpenAI API key
    - Deepgram API key (speech-to-text)
    - ElevenLabs API key (text-to-speech)

    Environment variables (set in .env or in your terminal using `export`):
        MNEMOVERSE_API_KEY=mk_live_...
        OPENAI_API_KEY=...
        DEEPGRAM_API_KEY=...
        ELEVENLABS_API_KEY=...

Run:
    python examples/voice-agent-memory.py

and open the printed local URL in a browser to talk to the agent. Say something
about yourself, end the call, start a new one and ask what it remembers.
"""

import os

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams
from pipecat.workers.runner import WorkerRunner

from pipecat_mnemoverse import MnemoverseMemoryService

load_dotenv(override=True)

USER_ID = "pipecat-demo-user"

transport_params = {
    "daily": lambda: DailyParams(audio_in_enabled=True, audio_out_enabled=True),
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


async def initial_greeting(memory: MnemoverseMemoryService) -> str:
    """Build the first instruction from what the agent already knows about the caller."""
    memories = await memory.get_memories(limit=5)
    if not memories:
        return "Greet the caller and ask how you can help."
    known = " ".join(m if len(m) <= 100 else m[:97] + "..." for m in memories)
    return f"Greet the caller as someone you have spoken to before. You remember: {known}"


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    """Run the pipeline with Mnemoverse memory between the user aggregator and the LLM."""
    stt = DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])
    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(voice="pNInz6obpgDQGcFmaJgB"),
    )

    # Reads MNEMOVERSE_API_KEY from the environment.
    memory = MnemoverseMemoryService(
        user_id=USER_ID,
        params=MnemoverseMemoryService.InputParams(top_k=5, read_timeout_secs=1.0),
    )

    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(
            system_instruction=(
                "You are a friendly voice assistant. Keep replies short. "
                "Use what you remember about the caller when it helps."
            ),
        ),
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
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

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )
    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        context.add_message({"role": "developer", "content": await initial_greeting(memory)})
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Entry point for the Pipecat runner."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
