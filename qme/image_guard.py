"""
qme/image_guard.py

Stop the agent reading its own plot images into the LLM context.

deepagents' FilesystemMiddleware auto-encodes image files (.png/.jpg/...) as multimodal blocks
(base64) when read via `read_file`. On a vision-disabled vLLM server (served
`--language-model-only`, qme/llm/vllm.py) that image is rejected with `openai.BadRequestError
400: "At most 0 image(s) may be provided in one prompt."`, an unhandled 400 that crashes the
run (main.py). It cannot be recovered by retrying, because the image persists in the message
history and the same 400 recurs, so it has to be prevented instead.

Reading a plot back is useless anyway (a language-only model cannot see it) and wasteful
(base64 is enormous in tokens), so `read_file` on an image path is intercepted and a short text
stub is returned instead of the image block. build_agent adds this guard only when vision is
off (provider == vllm, which is always `--language-model-only` here). A vision-capable setup
keeps normal image reads.
"""
from __future__ import annotations

import os

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

# The image extensions deepagents multimodal-encodes (deepagents/backends/utils.py:26-34), the
# set that triggers the "At most 0 image(s)" rejection on a language-only server.
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".heif"}


def is_image_path(path: str) -> bool:
    """True if `path` has an image extension deepagents would encode as a multimodal block."""
    return os.path.splitext(str(path).strip().lower())[1] in IMAGE_EXTS


class ImageReadGuard(AgentMiddleware):
    """Intercept `read_file` on an image file and return a text stub instead of letting deepagents emit
    a multimodal block, so a vision-disabled server never receives an image. Any other tool call passes
    straight through. Mirrors SkillGateMiddleware.wrap_tool_call (qme/agent.py)."""

    def wrap_tool_call(self, request, handler):
        tc = request.tool_call or {}
        path = (tc.get("args") or {}).get("file_path", "")
        if tc.get("name") == "read_file" and is_image_path(path):
            return ToolMessage(
                content=(
                    f"REFUSED: `{path}` is an image file, and this model is LANGUAGE-ONLY. It cannot "
                    f"see images, and sending one to the server returns an unrecoverable error that "
                    f"ENDS THE RUN.\n\n"
                    f"Do NOT call read_file on image files (.png, .jpg, .jpeg, .webp, .gif, .heic). "
                    f"This applies to plots you generated yourself: you cannot check a figure by "
                    f"looking at it.\n\n"
                    f"To verify a figure, read the numbers it was plotted FROM: the matching "
                    f"`data/*.json`, or re-run the analysis script that produced it and print the "
                    f"values. Judge the physics from the data, never from the picture."
                ),
                tool_call_id=tc.get("id", ""),
                name="read_file",
                status="success",
            )
        return handler(request)
