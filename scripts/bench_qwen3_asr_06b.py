import time
import subprocess

import librosa

from open_llm_vtuber.asr.qwen3_asr import VoiceRecognition


def main() -> None:
    path = "/mnt/c/AI/Open-LLM-VTuber/doc/黑神话/狐妖.mp3"
    audio, sr = librosa.load(path, sr=16000, mono=True)
    audio_sec = len(audio) / 16000
    print(f"AUDIO_SEC={audio_sec:.3f} SR={sr}", flush=True)

    started = time.perf_counter()
    asr = VoiceRecognition(
        backend="vllm",
        model_name="Qwen/Qwen3-ASR-0.6B",
        device_map="cuda:0",
        dtype="bfloat16",
        language="Chinese",
        context="请严格逐字转写音频中的原话，不要润色、不要改写、不要补全、不要总结。",
        max_new_tokens=128,
        max_inference_batch_size=1,
        vllm_gpu_memory_utilization=0.25,
        vllm_tensor_parallel_size=1,
        vllm_max_model_len=1024,
        vllm_enforce_eager=False,
    )
    print(f"INIT_SEC={time.perf_counter() - started:.3f}", flush=True)
    subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
    )

    for idx in range(1, 4):
        started = time.perf_counter()
        text = asr.transcribe_np(audio)
        elapsed = time.perf_counter() - started
        print(f"RUN={idx} TEXT={text}", flush=True)
        print(f"RUN={idx} ELAPSED={elapsed:.3f} RTF={elapsed / audio_sec:.4f}", flush=True)


if __name__ == "__main__":
    main()
