"""Downloads are explicit setup actions, never part of starting a demo or running tests."""

from nous.config import model_dir


def download_model() -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id="Qwen/Qwen2.5-0.5B-Instruct",
        local_dir=model_dir(),
        allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"],
        max_workers=2,
    )


if __name__ == "__main__":
    download_model()
