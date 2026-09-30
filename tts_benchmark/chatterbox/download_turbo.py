import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

def download_file_parallel(url: str, output_path: Path, num_threads: int = 16, chunk_size: int = 2 * 1024 * 1024):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Resolving redirect for {url}...", flush=True)
    head_resp = requests.head(url, allow_redirects=True, timeout=15)
    direct_url = head_resp.url
    total_size = int(head_resp.headers.get("content-length", 0))
    print(f"Target file: {output_path.name} | Total size: {total_size / (1024 * 1024):.2f} MB", flush=True)
    
    if output_path.exists() and output_path.stat().st_size == total_size:
        print(f"File already complete: {output_path}", flush=True)
        return output_path

    part_path = output_path.with_suffix(output_path.suffix + ".part")
    if not part_path.exists() or part_path.stat().st_size != total_size:
        with open(part_path, "wb") as f:
            f.seek(total_size - 1)
            f.write(b"\0")
            
    chunks = []
    for start in range(0, total_size, chunk_size):
        end = min(start + chunk_size - 1, total_size - 1)
        chunks.append((start, end))
        
    print(f"Divided into {len(chunks)} chunks of up to {chunk_size / (1024*1024):.1f} MB. Downloading with {num_threads} threads...", flush=True)
    
    completed_bytes = 0
    start_time = time.time()
    last_report_time = start_time
    
    def download_chunk(chunk_range):
        c_start, c_end = chunk_range
        headers = {"Range": f"bytes={c_start}-{c_end}"}
        retries = 3
        for attempt in range(retries):
            try:
                resp = requests.get(direct_url, headers=headers, timeout=30)
                if resp.status_code in (200, 206):
                    data = resp.content
                    with open(part_path, "r+b") as fp:
                        fp.seek(c_start)
                        fp.write(data)
                    return len(data)
                else:
                    time.sleep(1)
            except Exception as ex:
                if attempt == retries - 1:
                    raise ex
                time.sleep(1)
        raise RuntimeError(f"Failed chunk {c_start}-{c_end}")

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(download_chunk, c): c for c in chunks}
        for future in as_completed(futures):
            bytes_downloaded = future.result()
            completed_bytes += bytes_downloaded
            now = time.time()
            if now - last_report_time >= 5.0 or completed_bytes == total_size:
                elapsed = now - start_time
                speed = (completed_bytes / (1024 * 1024)) / (elapsed + 1e-6)
                pct = (completed_bytes / total_size) * 100
                print(f"[{output_path.name}] {completed_bytes / (1024*1024):.1f}/{total_size / (1024*1024):.1f} MB ({pct:.1f}%) - Speed: {speed:.2f} MB/s", flush=True)
                last_report_time = now

    if part_path.exists():
        if output_path.exists():
            output_path.unlink()
        part_path.rename(output_path)
        
    print(f"Download complete: {output_path} in {time.time() - start_time:.1f}s", flush=True)
    return output_path

def download_turbo_all():
    target_dir = Path("tts_benchmark/chatterbox/models/turbo")
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Download small tokenizer files & config directly
    from huggingface_hub import hf_hub_download
    small_files = ["vocab.json", "merges.txt", "added_tokens.json", "special_tokens_map.json", "tokenizer_config.json", "t3_turbo_v1.yaml", "conds.pt"]
    for sf in small_files:
        try:
            print(f"Downloading {sf}...", flush=True)
            p = hf_hub_download("ResembleAI/chatterbox-turbo", sf, local_dir=target_dir)
        except Exception as e:
            print(f"Notice: {sf} download error: {e}", flush=True)
            
    # 2. Parallel download large weights
    large_files = [
        ("s3gen_meanflow.safetensors", "https://huggingface.co/ResembleAI/chatterbox-turbo/resolve/main/s3gen_meanflow.safetensors"),
        ("t3_turbo_v1.safetensors", "https://huggingface.co/ResembleAI/chatterbox-turbo/resolve/main/t3_turbo_v1.safetensors")
    ]
    for fname, url in large_files:
        download_file_parallel(url, target_dir / fname, num_threads=16)

if __name__ == "__main__":
    download_turbo_all()
