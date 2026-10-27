#!/usr/bin/env bash
# Prints total GPU memory and per-process usage with each process labelled by its port.
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | while IFS=", " read -r pid mem unit; do
  cmd=$(tr "\0" " " < /proc/$pid/cmdline 2>/dev/null | grep -oE "(--port [0-9]+|Kev[^ /]*gguf|Gemma[^ /]*Q4_K_M.gguf|Qwen[^ /]*Q4_K_M.gguf|breeze_infer[^ ]*|sunshine|Xorg|halo)" | tr "\n" " ")
  echo "  $pid $mem MiB  $cmd"
done
