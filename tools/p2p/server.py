#!/usr/bin/env python3
"""Launch Open-P2P and relay a changing instruction file to its stdin.

An empty file is no instruction: sent as NONE, which our inference.py patch (open-p2p.patch) maps
back to the empty text the server starts with, since upstream ignores empty lines."""

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path

NONE = "<none>"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("600M", "1200M"), default="600M")
    parser.add_argument("--instruction", default="/home/minjune/m8work/run/p2p-instruction.txt")
    parser.add_argument("--log", default="/home/minjune/m8work/logs/p2p-server.log")
    parser.add_argument("--fps-test-frames", type=int, default=20)
    parser.add_argument("--no-compile", action="store_true")
    args = parser.parse_args()
    root = Path(os.environ.get("OPEN_P2P_ROOT", "/home/minjune/m8work/open-p2p"))
    instruction = Path(args.instruction)
    instruction.parent.mkdir(parents=True, exist_ok=True)
    instruction.touch(exist_ok=True)
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [str(root / ".venv/bin/python"), "elefant/policy_model/inference.py",
        "--config", f"checkpoints/{args.model}/model_config.yaml",
        "--checkpoint_path", f"checkpoints/{args.model}/checkpoint-step=00500000.ckpt",
        "--device", "cuda", "--input_text", "--fps_test_frames", str(args.fps_test_frames)]
    if args.no_compile:
        command.append("--no-compile")
    env = os.environ.copy()
    env.setdefault("P2P_GEMMA_MODEL_ID", "unsloth/embeddinggemma-300m")
    with log_path.open("a", buffering=1) as log:
        process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.PIPE,
            stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        stopping = False
        def stop(_sig, _frame):
            nonlocal stopping
            stopping = True
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        last = None
        try:
            while not stopping and process.poll() is None:
                value = instruction.read_text(errors="replace").strip()
                if value != last:
                    if value or last:  # empty is the server's initial instruction
                        process.stdin.write((value or NONE).replace("\n", " ") + "\n")
                        process.stdin.flush()
                    last = value
                    log.write(f"instruction-file update: {value!r}\n")
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        raise SystemExit(process.returncode or 0)


if __name__ == "__main__":
    main()
