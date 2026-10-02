"""
qme/llm/vllm.py
Manages a standalone vLLM server subprocess: launch, health checks, model
warm-up, and clean shutdown. The server runs from the current environment when
vllm is installed in it, or from a separate one named by `python_bin`.
"""

import os
import subprocess
import time
import urllib.request
import urllib.error
import json
import logging
import signal
from typing import Optional

from ._orphan import write_pidfile, reap_own_orphan, clear_pidfile

logger = logging.getLogger("qme.llm.vllm")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class VllmServer:
    def __init__(
        self,
        model: str,
        host: str = "127.0.0.1:11436",
        gpu_id: Optional[str] = None,
        context_length: Optional[int] = None,
        gpu_memory_utilization: Optional[float] = None,
        tensor_parallel_size: Optional[int] = None,
        launch_timeout_seconds: int = 180,
        base_dir: Optional[str] = None,
        enforce_eager: bool = True,
        tool_call_parser: Optional[str] = "pythonic",
        chat_template: Optional[str] = None,
        reasoning_parser: Optional[str] = None,
        rope_scaling: Optional[dict] = None,
        startup_cleanup: str = "own",
        python_bin: Optional[str] = None,
        log_dir: Optional[str] = None,
        pid_dir: Optional[str] = None,
    ):
        """
        Initializes the vLLM server wrapper.

        Args:
            model: HuggingFace model ID or local directory path.
            host: IP and port to bind (default: 127.0.0.1:11442).
            gpu_id: CUDA_VISIBLE_DEVICES ID to restrict the server to.
            context_length: Max context length (max-model-len).
            gpu_memory_utilization: Fraction of GPU memory to use (0.0 to 1.0).
            tensor_parallel_size: Number of GPUs to use for tensor parallel execution.
            launch_timeout_seconds: Time to wait for server to load model weights.
            base_dir: Base directory for local model storage/caching.
            tool_call_parser: vLLM tool-call parser name (default 'pythonic';
                set to None or '' to disable tool-calling support). Required
                whenever any agent does `llm.bind_tools(...)`; without this
                vLLM rejects requests with tool_choice='auto'. Common values:
                'pythonic' (generic), 'hermes' (Hermes-tuned), 'mistral',
                'llama3_json'. For Gemma 3/4 'pythonic' usually works.
            chat_template: optional path to a Jinja chat template file. Pass
                when the default template doesn't render `tool_calls` /
                `tools` properly.
            reasoning_parser: vLLM reasoning-content parser name (e.g.
                'gemma4', 'deepseek_r1'). REQUIRED when both thinking mode
                and tool calling are enabled, otherwise the model's
                thinking trace leaks into response.content alongside the
                final answer. Leave None to disable reasoning extraction.
            python_bin: python executable of the environment where vllm is
                installed. Defaults to $QME_VLLM_PYTHON; if that is unset and
                vllm is importable in the current environment, the current
                interpreter is used (single-environment setup), else plain
                "python3" from PATH.
            log_dir: where to write vllm_server.log (default: base_dir or cwd).
            pid_dir: where the crash-recovery pid file lives. Give it a stable,
                run-independent location so `startup_cleanup: own` can reap an
                orphaned server even when the next launch happens from a
                different working directory. Defaults to base_dir or cwd.
            rope_scaling: optional dict of HF rope_scaling config, emitted as
                `--hf-overrides {"rope_scaling": <dict>}`. Use to serve a model
                ABOVE its native context via YaRN (e.g. Qwen2.5 32K→128K:
                {"rope_type": "yarn", "factor": 4.0,
                 "original_max_position_embeddings": 32768}). vLLM 0.21 dropped
                the standalone `--rope-scaling` flag; this is the supported path.
                Leave None to serve at native length (no flag emitted).
        """
        self.model = model
        self.host = host
        self.gpu_id = str(gpu_id).strip() if gpu_id is not None else "-1"
        self.context_length = context_length
        self.gpu_memory_utilization = gpu_memory_utilization
        self.launch_timeout_seconds = launch_timeout_seconds
        self.base_dir = base_dir
        self.enforce_eager = enforce_eager
        self.tool_call_parser = (tool_call_parser or "").strip() or None
        self.chat_template = (chat_template or "").strip() or None
        self.reasoning_parser = (reasoning_parser or "").strip() or None
        self.rope_scaling = rope_scaling or None
        # Which python runs the server: the configured one, else $QME_VLLM_PYTHON,
        # else this very interpreter when vllm is installed alongside the driver
        # (the single-environment setup), else plain "python3" from PATH.
        self.python_bin = (python_bin or "").strip() or os.environ.get("QME_VLLM_PYTHON", "")
        if not self.python_bin:
            import importlib.util
            import sys
            self.python_bin = sys.executable if importlib.util.find_spec("vllm") else "python3"
        self.log_dir = (log_dir or "").strip() or None

        # Determine tensor parallel size automatically if not specified
        if tensor_parallel_size is None:
            if self.gpu_id and self.gpu_id != "-1":
                self.tensor_parallel_size = len([x for x in self.gpu_id.split(",") if x.strip()])
            else:
                self.tensor_parallel_size = 1
        else:
            self.tensor_parallel_size = tensor_parallel_size

        self.startup_cleanup = (startup_cleanup or "own").strip().lower()
        # Per-JOB pid-file, keyed by gpu_id (the scarce resource): a run reaps only the
        # server it (or a prior crash on the same GPUs) launched, so different-GPU parallel
        # runs get independent pid-files and never reap each other.
        gpu_tag = (self.gpu_id or "all").replace(",", "-").replace(" ", "") or "all"
        self._pidfile = os.path.join(pid_dir or base_dir or ".", f"vllm_gpu{gpu_tag}.pid")

        self.process: Optional[subprocess.Popen] = None
        self.env = os.environ.copy()
        self.log_file = None

        logger.info(
            "Initializing VllmServer (Model: %s, Host: %s, GPUs: %s, TP Size: %d)",
            self.model,
            self.host,
            self.gpu_id if self.gpu_id != "-1" else "All",
            self.tensor_parallel_size,
        )

    def _kill_all_user_servers(self):
        """AGGRESSIVE (opt-in, startup_cleanup='all'): SIGKILL EVERY vLLM process owned by
        the current user, including ones from other concurrent runs. Used only when
        explicitly requested; the default 'own' mode reaps just our own pid-file'd server."""
        logger.info("startup_cleanup='all': killing ALL same-user vLLM instances...")
        try:
            import psutil
            import getpass
            username = getpass.getuser()
            for proc in psutil.process_iter(['pid', 'name', 'username', 'cmdline']):
                try:
                    if proc.info['username'] == username:
                        cmdline = proc.info['cmdline']
                        name = proc.info['name']
                        
                        is_vllm = False
                        if cmdline:
                            is_vllm = any('vllm' in arg.lower() for arg in cmdline)
                        if name:
                            is_vllm = is_vllm or 'vllm' in name.lower()
                            
                        if is_vllm:
                            # Skip our own process and our parent process to avoid self-termination
                            if proc.info['pid'] in (os.getpid(), os.getppid()):
                                continue
                            logger.info("Killing dangling vLLM process: PID %d (%s)", proc.info['pid'], name or "unknown")
                            proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception as e:
            logger.debug("Failed to clean up old vLLM processes: %s", e)

    def _port_in_use(self) -> bool:
        """Check if something is already listening on our host:port."""
        import socket
        host_ip, port = self.host.rsplit(":", 1)
        port = int(port)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host_ip, port))
                return False
        except OSError:
            return True

    def _find_free_port(self, start_port: int, max_tries: int = 20) -> int:
        """Scan upward from start_port to find a free port."""
        import socket
        host_ip = self.host.split(":")[0]
        for offset in range(max_tries):
            port = start_port + offset
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    s.bind((host_ip, port))
                    return port
            except OSError:
                continue
        raise RuntimeError(
            f"Could not find a free port in range {start_port}-{start_port + max_tries - 1}"
        )

    def start(self) -> "VllmServer":
        """Starts the vLLM server subprocess."""
        # Startup cleanup: the default 'own' reaps only the server we (this job, these GPUs)
        # spawned last time via our pid-file; it NEVER touches a vLLM from another run. A
        # busy port is handled non-destructively by _find_free_port below.
        if self.startup_cleanup == "own":
            reap_own_orphan(self._pidfile, "vllm", logger)
        elif self.startup_cleanup == "all":
            self._kill_all_user_servers()
        # "none": touch nothing
        time.sleep(1)  # Give OS time to free port

        # Check if port is occupied
        if self._port_in_use():
            host_ip, orig_port = self.host.rsplit(":", 1)
            orig_port = int(orig_port)
            logger.warning(
                "Port %s is occupied. Searching for a free port...",
                self.host,
            )
            free_port = self._find_free_port(orig_port + 1)
            self.host = f"{host_ip}:{free_port}"
            logger.info("Will use port %d instead.", free_port)

        # Set environment variables
        if self.gpu_id != "-1":
            self.env["CUDA_VISIBLE_DEVICES"] = self.gpu_id
        
        # Conservative NCCL/symmetric-memory settings for bridge/PCIe GPU
        # topologies; harmless on NVLink systems.
        self.env["VLLM_ALLREDUCE_USE_SYMM_MEM"] = "0"
        self.env["DISABLE_SYMMETRIC_MEMORY"] = "1"
        self.env["NCCL_P2P_DISABLE"] = "1"
        
        # Build launch command
        host_ip, port = self.host.rsplit(":", 1)
        
        cmd = [
            self.python_bin,
            "-u",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model", self.model,
            "--host", host_ip,
            "--port", str(port),
        ]

        if self.context_length is not None:
            cmd.extend(["--max-model-len", str(self.context_length)])
        # HF config overrides (e.g. rope_scaling/YaRN to serve above native context).
        # Emitted ONLY when configured → absent for models served at native length (gemma).
        if self.rope_scaling:
            cmd.extend(["--hf-overrides", json.dumps({"rope_scaling": self.rope_scaling})])
        if self.gpu_memory_utilization is not None:
            cmd.extend(["--gpu-memory-utilization", str(self.gpu_memory_utilization)])
        if self.tensor_parallel_size is not None and self.tensor_parallel_size > 1:
            cmd.extend(["--tensor-parallel-size", str(self.tensor_parallel_size)])

        if self.enforce_eager:
            cmd.append("--enforce-eager")

        # Disable custom all-reduce kernels to avoid NVLink bridge topology deadlocks
        cmd.append("--disable-custom-all-reduce")

        # Text-only agents: skip the multimodal half of a multimodal model.
        # Without this, Gemma-4 hangs in encoder-cache profiling of video items.
        cmd.append("--language-model-only")

        # Function-calling support, required by every agent that does
        # `llm.bind_tools(...)`. Without these flags vLLM rejects requests
        # with tool_choice='auto' (HTTP 400). Set tool_call_parser=None in
        # config to skip and disable tool-calling.
        if self.tool_call_parser:
            cmd.extend([
                "--enable-auto-tool-choice",
                "--tool-call-parser", self.tool_call_parser,
            ])
        # Reasoning parser: separates the model's "thinking" trace from
        # the final response.content. Pair with tool-calling for models
        # that combine both (Gemma-4: --tool-call-parser gemma4
        # --reasoning-parser gemma4). Without it, thinking tokens leak
        # into response.content and downstream JSON/text parsing breaks.
        if self.reasoning_parser:
            cmd.extend(["--reasoning-parser", self.reasoning_parser])
        if self.chat_template:
            cmd.extend(["--chat-template", self.chat_template])

        logger.info("Launching vLLM with command: %s", " ".join(cmd))

        # Apply environment configurations
        if self.base_dir:
            model_dir = os.path.join(self.base_dir, "models")
            os.makedirs(model_dir, exist_ok=True)
            self.env["HF_HOME"] = self.base_dir
            self.env["HF_HUB_CACHE"] = model_dir

        # Open log file
        log_path = os.path.join(self.log_dir or self.base_dir or ".", "vllm_server.log")
        self.log_file = open(log_path, "w")

        try:
            self.process = subprocess.Popen(
                cmd,
                env=self.env,
                stdout=self.log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Could not launch the vLLM server: {self.python_bin!r} not found. "
                f"Set llm.vllm.server_python (or QME_VLLM_PYTHON) to the python of the "
                f"environment where vllm is installed.")

        # Record OUR server's PID so a future run (same GPUs) can reap it if we crash.
        write_pidfile(self._pidfile, self.process.pid)

        # Wait and verify the server is healthy and model is loaded
        self._wait_for_server(timeout=self.launch_timeout_seconds)

        # Double check process is still alive
        if self.process.poll() is not None:
            raise RuntimeError(
                f"vLLM process exited immediately (exit code {self.process.returncode}). "
                "Check vllm_server.log for details."
            )

        logger.info(
            "vLLM Server is up and ready (PID=%d, host=%s, CUDA_VISIBLE_DEVICES=%s).",
            self.process.pid,
            self.host,
            self.env.get("CUDA_VISIBLE_DEVICES", "(all)"),
        )
        return self

    def _wait_for_server(self, timeout: int = 180):
        """Blocks until vLLM server is responsive and healthy."""
        start_time = time.time()
        last_progress_log = start_time
        progress_interval = 30  # seconds between "still waiting" updates
        logger.info("Waiting for vLLM health endpoint to respond (timeout=%ds)...", timeout)
        while time.time() - start_time < timeout:
            if self.process and self.process.poll() is not None:
                raise RuntimeError("vLLM process exited during startup.")
            try:
                url = f"http://{self.host}/health"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        logger.info("vLLM health check passed (after %.1fs).", time.time() - start_time)
                        return
            except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError):
                # Expected during startup: vLLM hasn't bound its socket yet.
                # Log progress periodically instead of per-poll to keep output clean.
                now = time.time()
                if now - last_progress_log >= progress_interval:
                    logger.info("vLLM still starting up... (%ds elapsed)", int(now - start_time))
                    last_progress_log = now
                time.sleep(2)
        raise TimeoutError(
            f"vLLM /health did not respond within {timeout}s. "
            f"Check {os.path.join(self.log_dir or self.base_dir or '.', 'vllm_server.log')} for details."
        )

    def ensure_model_loaded(self, prompt: str = "ping", max_tokens: int = 1, timeout: int = 120):
        """
        Round-trip a real generation call so we know the model can serve, not
        just that the HTTP socket is open.
        """
        url = f"http://{self.host}/v1/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        logger.info("Probing vLLM with a 1-token completion to confirm the model is responsive...")
        start_time = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(
                f"vLLM /v1/chat/completions probe failed: {e}. "
                f"The HTTP server is up but the model cannot generate. "
                f"Check {os.path.join(self.log_dir or self.base_dir or '.', 'vllm_server.log')}."
            ) from e
        elapsed = time.time() - start_time
        choices = payload.get("choices", [])
        if not choices:
            raise RuntimeError(f"vLLM returned no choices in probe response: {payload!r}")
        logger.info("vLLM model %s is generating (probe took %.2fs).", self.model, elapsed)

    def stop(self):
        """Explicitly terminates the vLLM server and all its child workers."""
        if self.process:
            logger.info("Stopping vLLM server group...")
            pgid = self.process.pid
            try:
                # Send SIGTERM to the process group
                os.killpg(pgid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning("vLLM server group did not stop with SIGTERM, sending SIGKILL...")
                    os.killpg(pgid, signal.SIGKILL)
                    self.process.wait(timeout=2)
            except ProcessLookupError:
                pass  # already dead
            except Exception as e:
                logger.debug("Error while stopping process group: %s", e)
            self.process = None

        if self.log_file and not self.log_file.closed:
            self.log_file.close()

        # We stopped cleanly, so drop the pid-file and the next run won't treat this
        # (now-dead) PID as an orphan to reap.
        clear_pidfile(self._pidfile)

    def __del__(self):
        self.stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
