# ParAlgoTorrent Visualizer

This small GUI demonstrates and visualizes serial vs parallel downloads using the existing `client.py` code in this repository.

Quick start

1. Install python3 from https://www.python.org/downloads/

2. Create a python virtual environmennt
```
python3 -m venv venv
```

3. Install dependencies:
```bash
python3 -m pip install -r requirements.txt
```

3. Run the visualizer:

```bash
python3 visualizer.py
```

You can also run the `client.py` from terminal if you want.


Usage

- Choose `parallel` or `serial` mode.
- Click `Start` to begin. The GUI will plot progress (%) and download rate (kB/s).
- Click `Stop` to request cancellation.

Notes

- The GUI uses `client.download_torrent` via a background thread and receives a per-second status dict.
- The code for downloading torrent is in client.py
- Serial download is emulated by restricting download connections from libtorrent settings dict.
- The pyqt visualizer was made mostly using CoPilot. Promts used are at the top of the file.

Command-line / headless usage

- `client.py` supports three interactive modes when run directly:
	- `p` — single parallel download (the original parallel mode).
	- `s` — single serial download (sequential piece order).
	- `cp` — CPU-parallel: download X torrents in parallel using up to Y CPU cores.

When you choose `cp` the script will prompt for:
	- `X`: number of torrents to download (positive integer). If you don't provide a list of torrent files, the configured torrent in `constants.py` will be used repeatedly.
	- number of CPU cores to use (leave empty to use all available cores).

Behavior and output

- Each parallel download runs in its own process and stores content under `./downloads/parallel_<timestamp>/torrent_<i>`.
- After a `cp` run the script writes a CSV results file to `./results/<timestamp>_cpu-parallel.csv` with columns:
	`index,torrent_name,total_time_seconds,average_download_rate_kB_s,total_downloaded_bytes,save_path`
- You can also call the orchestrator directly from Python:

```python
from client import download_torrents_parallel
res = download_torrents_parallel(num_torrents=3, num_cores=3)
print(res)
```

Notes and dependencies

- This project requires `libtorrent` (python binding). Install it before running `client.py` — see `requirements.txt` for other Python dependencies.
- Running multiple libtorrent sessions in parallel spawns multiple processes that each open network sockets; ensure your system allows that and you have sufficient network bandwidth and disk space.
- If you want a non-interactive CLI (flags instead of prompts) I can add an argparse wrapper — tell me if you'd like that.