import os
import subprocess
import requests
from pathlib import Path

# Configuration
PROTO_SOURCE_URL = "https://api.github.com/repos/chromium/chromium/contents/third_party/lens_server_proto"
PROTO_RAW_BASE_URL = "https://raw.githubusercontent.com/chromium/chromium/main/third_party/lens_server_proto"
OUTPUT_DIR = Path("src/chrome_lens_py/utils/protobufs")
PROTO_TEMP_DIR = Path("temp_protos")

def fetch_proto_list():
    print(f"Fetching file list from {PROTO_SOURCE_URL}...")
    response = requests.get(PROTO_SOURCE_URL)
    response.raise_for_status()
    files = response.json()
    return [f["name"] for f in files if f["name"].endswith(".proto")]

def download_protos(proto_files):
    PROTO_TEMP_DIR.mkdir(exist_ok=True)
    for proto in proto_files:
        print(f"Downloading {proto}...")
        url = f"{PROTO_RAW_BASE_URL}/{proto}"
        resp = requests.get(url)
        resp.raise_for_status()
        (PROTO_TEMP_DIR / proto).write_text(resp.text, encoding="utf-8")

def compile_protos(proto_files):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Compiling protos using protoc...")
    for proto in proto_files:
        subprocess.run([
            "protoc",
            f"--proto_path={PROTO_TEMP_DIR}",
            f"--python_out={OUTPUT_DIR}",
            PROTO_TEMP_DIR / proto
        ], check=True)
    
    # Create __init__.py if missing
    (OUTPUT_DIR / "__init__.py").touch(exist_ok=True)

def cleanup():
    import shutil
    if PROTO_TEMP_DIR.exists():
        shutil.rmtree(PROTO_TEMP_DIR)

def main():
    try:
        proto_files = fetch_proto_list()
        download_protos(proto_files)
        compile_protos(proto_files)
        print("Successfully updated protobufs!")
        
        # Format output
        print("Formatting generated files...")
        subprocess.run(["black", str(OUTPUT_DIR)])
        subprocess.run(["isort", str(OUTPUT_DIR)])
        
    finally:
        cleanup()

if __name__ == "__main__":
    main()
