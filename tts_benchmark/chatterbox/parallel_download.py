import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

def download_file_parallel(url: str, output_path: Path, num_threads: int = 16, chunk_size: int = 2 * 1024 * 1024):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. Resolve redirect to get final AWS/CDN URL
    print(f"Resolving redirect for {url}...")
    head_resp = requests.head(url, allow_redirects=True, timeout=15)
    direct_url = head_resp.url
    total_size = int(head_resp.headers.get("content-length", 0))
    print(f"Target file: {output_path.name}")
    print(f"Total size: {total_size / (1024 * 1024):.2f} MB ({total_size} bytes)")
    
    if output_path.exists() and output_path.stat().st_size == total_size:
        print(f"File already complete: {output_path}")
        return output_path

    # Allocate file or open for writing chunks
    part_path = output_path.with_suffix(output_path.suffix + ".part")
    if not part_path.exists() or part_path.stat().st_size != total_size:
        with open(part_path, "wb") as f:
            f.seek(total_size - 1)
            f.write(b"\0")
            
    # Calculate chunks
    chunks = []
    for start in range(0, total_size, chunk_size):
        end = min(start + chunk_size - 1, total_size - 1)
        chunks.append((start, end))
        
    print(f"Divided into {len(chunks)} chunks of up to {chunk_size / (1024*1024):.1f} MB each. Downloading with {num_threads} threads...")
    
    # Track progress
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
            try:
                bytes_downloaded = future.result()
                completed_bytes += bytes_downloaded
                now = time.time()
                if now - last_report_time >= 5.0 or completed_bytes == total_size:
                    elapsed = now - start_time
                    speed = (completed_bytes / (1024 * 1024)) / (elapsed + 1e-6)
                    pct = (completed_bytes / total_size) * 100
                    print(f"Progress: {completed_bytes / (1024*1024):.1f}/{total_size / (1024*1024):.1f} MB ({pct:.1f}%) - Speed: {speed:.2f} MB/s")
                    last_report_time = now
            except Exception as exc:
                print(f"Error downloading chunk: {exc}")
                raise exc

    # Rename .part to target
    if part_path.exists():
        if output_path.exists():
            output_path.unlink()
        part_path.rename(output_path)
        
    print(f"Download completed successfully in {time.time() - start_time:.1f}s -> {output_path}")
    return output_path

if __name__ == "__main__":
    target_dir = Path("tts_benchmark/chatterbox/models/multilingual_v3")
    url = "https://huggingface.co/ResembleAI/chatterbox/resolve/main/t3_mtl23ls_v3.safetensors"
    download_file_parallel(url, target_dir / "t3_mtl23ls_v3.safetensors", num_threads=16)
