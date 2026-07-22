import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from iptv_source_checker.review_server import main  # noqa: E402

if __name__ == "__main__":
    main()
